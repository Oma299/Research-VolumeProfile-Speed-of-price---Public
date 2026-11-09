"""Focused tests for read-only Day 3 Block 1 validation."""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

import validation


class ValidationTests(unittest.TestCase):
    def _load(self):
        return validation.load_artifacts()

    def test_existing_artifacts_evaluate_all_frozen_checks_without_mutation(self) -> None:
        events, raw_events, boxes, minute_bars, candles_15m = self._load()
        originals = [frame.copy(deep=True) for frame in (events, raw_events, boxes, minute_bars, candles_15m)]

        checks = validation.evaluate_validation_checks(events, raw_events, boxes, minute_bars, candles_15m)

        section_checks = [item for item in checks if item["id"].startswith("17.")]
        self.assertEqual([item["id"] for item in section_checks], [f"17.{number}" for number in range(1, 11)])
        results = {item["id"]: item["status"] for item in checks}
        self.assertEqual(results["17.1"], "PASS")
        self.assertEqual(results["17.2"], "PASS")
        self.assertEqual(results["17.3"], "PASS")
        self.assertEqual(results["17.4"], "PASS")
        self.assertEqual(results["17.5"], "PASS")
        self.assertEqual(results["17.6"], "PASS")
        self.assertEqual(results["17.7"], "PASS")
        self.assertEqual(results["17.8"], "PASS")
        self.assertEqual(results["17.9"], "PASS")
        self.assertEqual(results["17.10"], "PASS")
        self.assertEqual(results["I.1"], "PASS")
        self.assertEqual(results["I.2"], "PASS")
        self.assertEqual(results["I.3"], "PASS")
        self.assertEqual(results["I.4"], "PASS")
        formation = next(item for item in checks if item["id"] == "17.1")
        lifecycle = next(item for item in checks if item["id"] == "I.1")
        self.assertIn("exactly-32-valid=373", formation["observed"])
        self.assertIn("validates the formation interval", formation["note"])
        self.assertIn("first breakout at terminal candle=324/324", lifecycle["observed"])
        self.assertIn("expired without breakout=49/49", lifecycle["observed"])
        for current, original in zip((events, raw_events, boxes, minute_bars, candles_15m), originals):
            pd.testing.assert_frame_equal(current, original)

    def test_formation_check_is_independent_of_active_lifecycle_age(self) -> None:
        events, raw_events, boxes, minute_bars, candles_15m = self._load()

        changed_age = boxes.copy(deep=True)
        changed_age.loc[0, "box_age_candles"] = 1
        age_checks = validation.evaluate_validation_checks(
            events, raw_events, changed_age, minute_bars, candles_15m
        )
        self.assertEqual(next(item for item in age_checks if item["id"] == "17.1")["status"], "PASS")
        self.assertEqual(next(item for item in age_checks if item["id"] == "I.1")["status"], "FAIL")

        changed_formation = boxes.copy(deep=True)
        changed_formation.loc[0, "box_start"] += pd.Timedelta(minutes=15)
        formation_checks = validation.evaluate_validation_checks(
            events, raw_events, changed_formation, minute_bars, candles_15m
        )
        self.assertEqual(next(item for item in formation_checks if item["id"] == "17.1")["status"], "FAIL")

    def test_synthetic_up_down_profile_and_outcome_symmetry(self) -> None:
        profile = validation._synthetic_profile_symmetry()
        outcome = validation._synthetic_outcome_symmetry()

        self.assertTrue(profile["passed"])
        self.assertTrue(outcome["passed"])
        self.assertEqual(profile["up"]["ahead_volume"], profile["down"]["ahead_volume"])
        self.assertEqual(outcome["up"]["time_to_target_minutes"], outcome["down"]["time_to_target_minutes"])
        self.assertAlmostEqual(outcome["up"]["r_60"], outcome["down"]["r_60"])

    def test_missing_va_zero_imputation_fails_section_17_10(self) -> None:
        events, raw_events, boxes, minute_bars, candles_15m = self._load()
        changed = events.copy(deep=True)
        missing_index = changed.index[~changed["profile_valid"]].tolist()[0]
        changed.loc[missing_index, "VA"] = 0.0

        checks = validation.evaluate_validation_checks(changed, raw_events, boxes, minute_bars, candles_15m)

        result = next(item for item in checks if item["id"] == "17.10")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("missing VA is null=False", result["observed"])

    def test_missing_artifact_or_column_fails_clearly(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "Required validation artifacts are missing"):
            validation._require_artifacts([Path("/definitely/missing/validation-input.csv")])
        with self.assertRaisesRegex(ValueError, "Required columns missing from test input: VA"):
            validation._require_columns(pd.DataFrame({"event_id": ["x"]}), {"event_id", "VA"}, "test input")

    def test_report_writer_is_confined_to_approved_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "reports" / "day3" / "block1_validation"
            output_path = output_root / "VALIDATION_REPORT.md"
            original_root = validation.OUTPUT_DIR
            try:
                validation.OUTPUT_DIR = output_root
                written = validation.write_validation_report("read-only test", output_path)
                self.assertEqual(written, output_path.resolve())
                self.assertEqual(written.read_text(encoding="utf-8"), "read-only test")
                with self.assertRaisesRegex(ValueError, "inside reports/day3/block1_validation"):
                    validation.write_validation_report("forbidden", Path(temporary) / "outside.md")
            finally:
                validation.OUTPUT_DIR = original_root


if __name__ == "__main__":
    unittest.main()