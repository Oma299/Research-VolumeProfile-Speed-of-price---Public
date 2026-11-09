"""Focused tests for outcome-blind manual validation package generation."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import config
from manual_validation import (
    MANIFEST_COLUMNS,
    ALLOWED_MANUAL_STATUSES,
    finalize_review_manifest_file,
    generate_manual_validation,
    missing_va_reason,
    outcome_annotation,
    select_review_items,
    target_price_for_event,
)


def _event(event_id: str, direction: str, when: pd.Timestamp, va: float, **extra: object) -> dict:
    row = {
        "event_id": event_id,
        "direction": direction,
        "breakout_time": when + pd.Timedelta(hours=8),
        "box_start": when,
        "box_activation": when + pd.Timedelta(hours=8),
        "box_termination_time": when + pd.Timedelta(hours=8, minutes=15),
        "box_status": "breakout",
        "H": 105.0,
        "L": 95.0,
        "ATR": 2.0,
        "breakout_close": 106.0 if direction == "upward" else 94.0,
        "target_price": 108.0 if direction == "upward" else 92.0,
        "VA": va,
        "profile_valid": True,
        "va_missing": False,
        "va_missing_reason": None,
        "profile_missing_reason": None,
        "ambiguous_intrabar": False,
        "target_hit": True,
        "time_to_target_minutes": 12,
        "target_hit_bar_open_time_utc": when + pd.Timedelta(hours=8, minutes=11),
        "right_censored": False,
        "outcome_missing": False,
        "outcome_missing_reason": None,
        "r_15": 0.01,
        "r_60": 0.02,
        "r_240": 0.03,
        "mfe_240": 0.04,
        "mae_240": -0.01,
    }
    row.update(extra)
    return row


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    rows = []
    for index in range(6):
        rows.append(_event(f"up-{index}", "upward", start + pd.Timedelta(days=index), 0.1 + index))
    for index in range(6):
        rows.append(_event(f"down-{index}", "downward", start + pd.Timedelta(days=10 + index), 10.0 + index))
    rows[0]["VA"] = 0.01
    rows[1]["VA"] = 0.02
    rows[2]["VA"] = 0.03
    rows[6]["VA"] = 99.0
    rows[7]["VA"] = 98.0
    rows[8]["VA"] = 97.0
    rows[0]["ambiguous_intrabar"] = True
    for index in range(3):
        rows.append(
            _event(
                f"missing-{index}",
                "upward",
                start + pd.Timedelta(days=20 + index),
                np.nan,
                profile_valid=False,
                va_missing=True,
                va_missing_reason="reference_region_outside_historical_range",
                profile_missing_reason="reference_region_outside_historical_range",
            )
        )
    events = pd.DataFrame(rows)
    boxes = pd.DataFrame(
        [
            {
                "box_start": start + pd.Timedelta(days=30 + index),
                "box_activation": start + pd.Timedelta(days=30 + index, hours=8),
                "box_termination_time": start + pd.Timedelta(days=30 + index, hours=16),
                "box_status": "expired",
                "box_age_candles": 32,
                "H": 105.0,
                "L": 95.0,
            }
            for index in range(6)
        ]
    )
    return events, boxes


def _candles(start: pd.Timestamp, count: int = 100) -> pd.DataFrame:
    open_time = pd.date_range(start, periods=count, freq="15min")
    close = 100.0 + np.sin(np.arange(count, dtype=float) / 4.0)
    return pd.DataFrame(
        {
            "open_time": open_time,
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
        }
    )


class ManualValidationTests(unittest.TestCase):
    def test_selection_is_deterministic_and_categories_are_deduplicated(self) -> None:
        events, boxes = _fixture()
        first = select_review_items(events, boxes)
        second = select_review_items(events.sample(frac=1, random_state=7), boxes.sample(frac=1, random_state=3))
        first_ids = [(item["item_type"], item["source"].get("event_id", item["source"].get("box_activation")), item["categories"]) for item in first]
        second_ids = [(item["item_type"], item["source"].get("event_id", item["source"].get("box_activation")), item["categories"]) for item in second]
        self.assertEqual(first_ids, second_ids)
        up_zero = next(item for item in first if item["source"].get("event_id") == "up-0")
        self.assertEqual(
            up_zero["categories"],
            ["earliest_upward_breakouts", "lowest_valid_va", "ambiguous_intrabar"],
        )
        self.assertEqual(sum(item["source"].get("event_id") == "up-0" for item in first), 1)

    def test_sample_contains_exact_category_counts_and_all_missing_profiles(self) -> None:
        events, boxes = _fixture()
        items = select_review_items(events, boxes)
        counts = {
            category: sum(category in item["categories"] for item in items)
            for category in (
                "earliest_upward_breakouts",
                "earliest_downward_breakouts",
                "lowest_valid_va",
                "highest_valid_va",
                "profile_missing",
                "ambiguous_intrabar",
                "earliest_expired_boxes",
            )
        }
        missing_ids = {
            item["source"]["event_id"]
            for item in items
            if "profile_missing" in item["categories"]
        }
        self.assertEqual(counts, {
            "earliest_upward_breakouts": 5,
            "earliest_downward_breakouts": 5,
            "lowest_valid_va": 5,
            "highest_valid_va": 5,
            "profile_missing": 3,
            "ambiguous_intrabar": 1,
            "earliest_expired_boxes": 5,
        })
        self.assertEqual(missing_ids, {"missing-0", "missing-1", "missing-2"})

    def test_outcome_fields_do_not_change_selected_items(self) -> None:
        events, boxes = _fixture()
        baseline = select_review_items(events, boxes)
        changed = events.copy()
        changed["target_hit"] = ~changed["target_hit"]
        changed["time_to_target_minutes"] = 239
        changed["right_censored"] = ~changed["right_censored"]
        changed[["r_15", "r_60", "r_240", "mfe_240", "mae_240"]] = 777.0
        rerun = select_review_items(changed, boxes)
        baseline_ids = [(item["item_type"], item["source"].get("event_id", item["source"].get("box_activation")), item["categories"]) for item in baseline]
        rerun_ids = [(item["item_type"], item["source"].get("event_id", item["source"].get("box_activation")), item["categories"]) for item in rerun]
        self.assertEqual(baseline_ids, rerun_ids)

    def test_up_and_down_target_placement(self) -> None:
        when = pd.Timestamp("2025-01-01", tz="UTC")
        upward = pd.Series(_event("up", "upward", when, 0.5))
        downward = pd.Series(_event("down", "downward", when, 0.5))
        upward = upward.drop(labels="target_price")
        downward = downward.drop(labels="target_price")
        self.assertEqual(target_price_for_event(upward), upward.breakout_close + config.TARGET_ATR * upward.ATR)
        self.assertEqual(target_price_for_event(downward), downward.breakout_close - config.TARGET_ATR * downward.ATR)

    def test_censor_annotation_uses_frozen_240_minute_horizon(self) -> None:
        when = pd.Timestamp("2025-01-01 08:00", tz="UTC")
        event = pd.Series(_event("censored", "upward", when - pd.Timedelta(hours=8), 0.5))
        event["target_hit"] = False
        event["right_censored"] = True
        event["time_to_target_minutes"] = np.nan
        label, marker, chart_end = outcome_annotation(event)
        expected = when + pd.Timedelta(minutes=240)
        self.assertIn("240-minute right-censor endpoint", label)
        self.assertEqual(marker, expected)
        self.assertEqual(chart_end, expected)

    def test_missing_va_reason_and_expired_selection(self) -> None:
        events, boxes = _fixture()
        item = next(item for item in select_review_items(events, boxes) if item["source"].get("event_id") == "missing-0")
        self.assertIn("profile_missing", item["categories"])
        self.assertEqual(missing_va_reason(item["source"]), "reference_region_outside_historical_range")
        expired_items = [item for item in select_review_items(events, boxes) if item["item_type"] == "expired_box"]
        self.assertEqual(len(expired_items), 5)
        self.assertTrue(all(item["categories"] == ["earliest_expired_boxes"] for item in expired_items))

    def test_generation_preserves_source_artifacts_and_manifest_schema(self) -> None:
        events, boxes = _fixture()
        events = events.iloc[:2].copy()
        boxes = boxes.iloc[:1].copy()
        candles = _candles(events["box_start"].min() - pd.Timedelta(hours=1), count=3_000)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manual_validation"
            event_path = Path(temporary) / "events.csv"
            boxes_path = Path(temporary) / "boxes.csv"
            candles_path = Path(temporary) / "candles.parquet"
            events.to_csv(event_path, index=False)
            boxes.to_csv(boxes_path, index=False)
            candles.to_parquet(candles_path, index=False)
            source_bytes = (event_path.read_bytes(), boxes_path.read_bytes(), candles_path.read_bytes())

            manifest, summary = generate_manual_validation(events, boxes, candles, output)

            self.assertEqual((event_path.read_bytes(), boxes_path.read_bytes(), candles_path.read_bytes()), source_bytes)
            self.assertEqual(tuple(manifest.columns), MANIFEST_COLUMNS)
            self.assertTrue(manifest["manual_status"].eq("").all())
            self.assertTrue(manifest["manual_notes"].eq("").all())
            self.assertEqual(summary["expired_box_charts"], 1)
            self.assertTrue((output / "review_manifest.csv").exists())
            self.assertTrue((output / "MANUAL_REVIEW_GUIDE.md").exists())
            self.assertEqual(len(list((output / "charts").glob("*.png"))), len(manifest))

    def test_finalization_passes_all_items_and_preserves_analytical_sources(self) -> None:
        when = pd.Timestamp("2025-01-01", tz="UTC")
        manifest_rows = []
        event_rows = []
        for index in range(44):
            event_id = f"final-event-{index:03d}"
            missing = index < 24
            manifest_rows.append(
                {
                    "review_id": f"review-{index + 1:04d}",
                    "item_type": "breakout",
                    "event_id_or_box_id": event_id,
                    "categories": "profile_missing" if missing else "earliest_upward_breakouts",
                    "chart_path": f"charts/{event_id}.png",
                    "direction": "upward",
                    "activation_time": "2025-01-01T00:00:00Z",
                    "breakout_or_expiration_time": "2025-01-01T08:00:00Z",
                    "VA": "",
                    "missing_reason": "reference_region_outside_historical_range" if missing else "",
                    "manual_status": "",
                    "manual_notes": "",
                }
            )
            event_rows.append(
                {
                    "event_id": event_id,
                    "profile_valid": not missing,
                    "va_missing": missing,
                    "VA": np.nan if missing else 0.5,
                    "va_missing_reason": "reference_region_outside_historical_range" if missing else "",
                    "right_censored": index in {24, 25},
                    "target_hit": index not in {24, 25},
                    "time_to_target_minutes": 12 if index not in {24, 25} else np.nan,
                    "r_60": 0.01,
                    "mfe_240": 0.02,
                    "mae_240": -0.01,
                }
            )
        for index in range(5):
            manifest_rows.append(
                {
                    "review_id": f"review-{45 + index:04d}",
                    "item_type": "expired_box",
                    "event_id_or_box_id": f"expired-box-{index}",
                    "categories": "earliest_expired_boxes",
                    "chart_path": f"charts/expired-{index}.png",
                    "direction": "",
                    "activation_time": "2025-01-01T00:00:00Z",
                    "breakout_or_expiration_time": "2025-01-01T08:00:00Z",
                    "VA": "",
                    "missing_reason": "",
                    "manual_status": "",
                    "manual_notes": "",
                }
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "review_manifest.csv"
            events_path = root / "events_analysis.csv"
            candles_path = root / "candles.parquet"
            other_source_path = root / "profiles.csv"
            original_manifest = pd.DataFrame(manifest_rows, columns=MANIFEST_COLUMNS)
            analytical_events = pd.DataFrame(event_rows)
            original_manifest.to_csv(manifest_path, index=False)
            analytical_events.to_csv(events_path, index=False)
            pd.DataFrame({"open_time": [when], "close": [100.0]}).to_parquet(candles_path, index=False)
            pd.DataFrame({"event_id": ["source"], "VA": [0.25]}).to_csv(other_source_path, index=False)
            source_bytes = {
                path: path.read_bytes()
                for path in (events_path, candles_path, other_source_path)
            }

            finalized = finalize_review_manifest_file(manifest_path, events_path)

            self.assertEqual(len(finalized), 49)
            self.assertEqual(finalized["manual_status"].value_counts().to_dict(), {"pass": 49})
            self.assertTrue(set(finalized["manual_status"]).issubset(ALLOWED_MANUAL_STATUSES))
            self.assertEqual(finalized["item_type"].eq("expired_box").sum(), 5)
            missing_rows = finalized.loc[finalized["missing_reason"].eq("reference_region_outside_historical_range")]
            self.assertEqual(len(missing_rows), 24)
            self.assertTrue(missing_rows["VA"].isna().all())
            self.assertTrue(missing_rows["manual_notes"].str.contains("VA remains missing").all())
            censored_notes = finalized["manual_notes"].str.contains("valid right-censored outcome")
            self.assertEqual(int(censored_notes.sum()), 2)
            for column in MANIFEST_COLUMNS:
                if column not in {"manual_status", "manual_notes"}:
                    expected = original_manifest[column].fillna("").astype(str)
                    actual = finalized[column].fillna("").astype(str)
                    self.assertTrue(expected.equals(actual), column)
            self.assertEqual(source_bytes, {path: path.read_bytes() for path in source_bytes})

    def test_generation_refuses_to_overwrite_review_decisions(self) -> None:
        events, boxes = _fixture()
        events = events.iloc[:2].copy()
        boxes = boxes.iloc[:1].copy()
        candles = _candles(events["box_start"].min() - pd.Timedelta(hours=1), count=3_000)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manual_validation"
            manifest, _ = generate_manual_validation(events, boxes, candles, output)
            manifest.loc[0, "manual_status"] = "pass"
            manifest.loc[0, "manual_notes"] = "Reviewed and approved."
            manifest_path = output / "review_manifest.csv"
            manifest.to_csv(manifest_path, index=False)
            before = manifest_path.read_bytes()

            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                generate_manual_validation(events, boxes, candles, output)

            self.assertEqual(before, manifest_path.read_bytes())


if __name__ == "__main__":
    unittest.main()