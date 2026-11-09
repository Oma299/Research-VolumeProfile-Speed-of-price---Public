"""Descriptive Day 3 Block 2 sample-size readiness assessment."""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd

import config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "events_analysis.csv"
BLOCK1_REPORT_PATH = PROJECT_ROOT / "reports" / "day3" / "block1_validation" / "VALIDATION_REPORT.md"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "day3" / "block2_sample_size"
REPORT_PATH = OUTPUT_DIR / "SAMPLE_SIZE_ASSESSMENT.md"

EXPECTED_EVENT_COUNT = 324
PROFILE_MISSING_REASON = "reference_region_outside_historical_range"

CONTROL_COLUMNS = (
    "volatility",
    "normalized_box_width_atr",
    "breakout_strength",
    "pre_trend",
    "breakout_direction",
    "hour_of_day_utc",
)
EXPOSURE_COLUMNS = ("VA", "log1p_VA")
SURVIVAL_COLUMNS = (
    "target_hit",
    "time_to_target_minutes",
    "observed_time_minutes",
    "right_censored",
    "outcome_missing",
)
REQUIRED_COLUMNS = {
    "event_id",
    "breakout_direction",
    "profile_valid",
    "va_missing",
    "va_missing_reason",
    "primary_analysis_eligible",
    "target_hit",
    "right_censored",
    "time_to_target_minutes",
    "observed_time_minutes",
    "outcome_missing",
    "r_60",
    *CONTROL_COLUMNS,
    *EXPOSURE_COLUMNS,
}


def _bool_series(values: pd.Series, missing: bool = False) -> pd.Series:
    return values.fillna(missing).astype(bool)


def _category_for_size(count: int) -> str:
    if count > 100:
        return "excellent (>100)"
    if count >= 50:
        return "good (50-100)"
    if count >= 30:
        return "minimum acceptable (30-49)"
    return "below minimum (<30)"


def assess_sample_size(events: pd.DataFrame, block1_report: str) -> Dict[str, Any]:
    """Compute deterministic readiness counts; do not fit or test any models."""
    missing_columns = REQUIRED_COLUMNS.difference(events.columns)
    if missing_columns:
        raise ValueError(f"Analysis table is missing required columns: {', '.join(sorted(missing_columns))}")
    if events["event_id"].isna().any() or events["event_id"].astype(str).duplicated().any():
        raise ValueError("event_id values must be present and unique")
    if "**Overall result: PASS** (14 pass, 0 fail)." not in block1_report:
        raise ValueError("Day 3 Block 1 validation report must record 14 PASS and 0 FAIL")
    if len(events) != EXPECTED_EVENT_COUNT:
        raise ValueError(f"Expected {EXPECTED_EVENT_COUNT} persisted event rows; found {len(events)}")

    eligible = _bool_series(events["primary_analysis_eligible"])
    profile_valid = _bool_series(events["profile_valid"]) & ~_bool_series(events["va_missing"], missing=True)
    va_valid = profile_valid & events["VA"].notna() & events["log1p_VA"].notna()
    eligible_profile_valid = eligible & va_valid
    if not eligible.equals(eligible_profile_valid):
        raise ValueError("primary_analysis_eligible does not match valid VA/profile availability")

    controls_complete = events.loc[:, CONTROL_COLUMNS].notna().all(axis=1)
    exposure_complete = events.loc[:, EXPOSURE_COLUMNS].notna().all(axis=1)
    target_hit = _bool_series(events["target_hit"])
    right_censored = _bool_series(events["right_censored"])
    outcome_missing = _bool_series(events["outcome_missing"], missing=True)
    observed_time = pd.to_numeric(events["observed_time_minutes"], errors="coerce")
    time_to_target = pd.to_numeric(events["time_to_target_minutes"], errors="coerce")

    hit_outcome_valid = (
        target_hit
        & ~right_censored
        & ~outcome_missing
        & observed_time.between(1, config.MAX_HORIZON_MINUTES)
        & time_to_target.between(1, config.MAX_HORIZON_MINUTES)
        & time_to_target.eq(observed_time)
    )
    censored_outcome_valid = (
        ~target_hit
        & right_censored
        & ~outcome_missing
        & observed_time.eq(config.MAX_HORIZON_MINUTES)
        & time_to_target.isna()
    )
    survival_complete = hit_outcome_valid | censored_outcome_valid
    primary_rows = eligible & exposure_complete & controls_complete & survival_complete
    secondary_r60_rows = eligible & exposure_complete & controls_complete & events["r_60"].notna()

    missing_profile = ~profile_valid
    missing_reason_counts = events.loc[missing_profile, "va_missing_reason"].fillna("<missing>").value_counts(dropna=False)
    missing_direction_counts = events.loc[missing_profile, "breakout_direction"].value_counts(dropna=False)
    total_direction_counts = events["breakout_direction"].value_counts(dropna=False)
    eligible_direction_counts = events.loc[eligible, "breakout_direction"].value_counts(dropna=False)
    eligible_hits = eligible & hit_outcome_valid
    eligible_censored = eligible & censored_outcome_valid

    result: Dict[str, Any] = {
        "total_events": int(len(events)),
        "unique_event_ids": int(events["event_id"].nunique()),
        "eligible_events": int(eligible.sum()),
        "eligible_va_valid": int(eligible_profile_valid.sum()),
        "missing_profile_events": int(missing_profile.sum()),
        "missing_profile_reasons": {str(key): int(value) for key, value in missing_reason_counts.items()},
        "missing_profile_by_direction": {str(key): int(value) for key, value in missing_direction_counts.items()},
        "total_by_direction": {str(key): int(value) for key, value in total_direction_counts.items()},
        "eligible_by_direction": {str(key): int(value) for key, value in eligible_direction_counts.items()},
        "eligible_target_hits": int(eligible_hits.sum()),
        "eligible_right_censored": int(eligible_censored.sum()),
        "total_target_hits": int((target_hit & ~outcome_missing).sum()),
        "total_right_censored": int((right_censored & ~outcome_missing).sum()),
        "eligible_outcome_missing": int((eligible & outcome_missing).sum()),
        "eligible_exposure_complete": int((eligible & exposure_complete).sum()),
        "eligible_survival_complete": int((eligible & survival_complete).sum()),
        "eligible_time_to_target_hit_durations": int((eligible & hit_outcome_valid).sum()),
        "eligible_intentionally_null_censored_durations": int((eligible & censored_outcome_valid).sum()),
        "eligible_r60_complete": int((eligible & events["r_60"].notna()).sum()),
        "eligible_controls_complete": int((eligible & controls_complete).sum()),
        "control_completeness": {
            column: int((eligible & events[column].notna()).sum()) for column in CONTROL_COLUMNS
        },
        "primary_analysis_available": int(primary_rows.sum()),
        "secondary_r60_analysis_available": int(secondary_r60_rows.sum()),
        "total_threshold_category": _category_for_size(len(events)),
        "eligible_threshold_category": _category_for_size(int(eligible.sum())),
        "pilot_period": f"{config.PILOT_START} through {config.PILOT_END}",
    }

    if result["missing_profile_events"] != 24:
        raise ValueError(f"Expected 24 profile-missing events; found {result['missing_profile_events']}")
    if result["missing_profile_reasons"] != {PROFILE_MISSING_REASON: 24}:
        raise ValueError(f"Unexpected profile-missing reasons: {result['missing_profile_reasons']}")
    if result["total_right_censored"] != 75 or result["eligible_outcome_missing"] != 0:
        raise ValueError("Outcome counts do not match the validated complete 240-minute outcome sample")
    if result["primary_analysis_available"] != result["eligible_events"]:
        raise ValueError("Eligible sample contains incomplete primary survival inputs")
    if result["secondary_r60_analysis_available"] != result["eligible_events"]:
        raise ValueError("Eligible sample contains missing R_60 or secondary-model controls")
    return result


def render_report(result: Mapping[str, Any]) -> str:
    total = result["total_events"]
    eligible = result["eligible_events"]
    missing = result["missing_profile_events"]
    total_missing_pct = 100 * missing / total if total else 0.0
    up_total = result["total_by_direction"].get("upward", 0)
    down_total = result["total_by_direction"].get("downward", 0)
    up_missing = result["missing_profile_by_direction"].get("upward", 0)
    down_missing = result["missing_profile_by_direction"].get("downward", 0)
    up_missing_pct = 100 * up_missing / up_total if up_total else 0.0
    down_missing_pct = 100 * down_missing / down_total if down_total else 0.0
    censor_note = (
        "Right-censored observations are complete 240-minute no-hit outcomes, not missing outcomes. "
        "Their `time_to_target_minutes` is intentionally null while `observed_time_minutes` is 240."
    )
    lines = [
        "# Day 3 Block 2 Sample-Size Readiness Assessment",
        "",
        f"**Recommendation: GO WITH CAUTION for Day 3 Block 3.** This is a descriptive readiness decision only; it is not an inferential conclusion, a power analysis, or a claim that the hypothesis is supported.",
        "",
        "## Scope and Validation Gate",
        "",
        f"The fixed Pilot v0.1 period is {result['pilot_period']}. The completed Day 3 Block 1 report records 14 PASS and 0 FAIL. No period expansion, detector-threshold change, model fitting, Kaplan–Meier curve, hypothesis test, or post-hoc power analysis was performed.",
        "",
        "## Event Counts",
        "",
        f"- **Total detected breakout event occurrences:** {total}. This is not the number of target hits.",
        f"- **Primary-analysis-eligible events with valid VA:** {eligible} ({result['eligible_threshold_category']}).",
        f"- **Profile-missing events:** {missing}/{total} ({total_missing_pct:.1f}%). Recorded reason: `{PROFILE_MISSING_REASON}` ({result['missing_profile_reasons'].get(PROFILE_MISSING_REASON, 0)} events). These rows remain outside the VA-eligible sample; no VA values were imputed.",
        f"- **Total direction counts:** UP {result['total_by_direction'].get('upward', 0)}; DOWN {result['total_by_direction'].get('downward', 0)}.",
        f"- **Eligible direction counts:** UP {result['eligible_by_direction'].get('upward', 0)}; DOWN {result['eligible_by_direction'].get('downward', 0)}.",
        f"- **Directional exposure availability:** UP profile-missing {up_missing}/{up_total} ({up_missing_pct:.1f}%); DOWN profile-missing {down_missing}/{down_total} ({down_missing_pct:.1f}%).",
        f"- **Target-hit event occurrences in the eligible sample:** {result['eligible_target_hits']}.",
        f"- **Right-censored event occurrences in the eligible sample:** {result['eligible_right_censored']}.",
        f"- For context, the full 324-row event table has {result['total_target_hits']} target hits and {result['total_right_censored']} right-censored events. A target hit is an outcome status, not another event count.",
        "",
        "## Field Availability",
        "",
        f"- Primary exposure (`VA`, `log1p_VA`): {result['eligible_exposure_complete']}/{eligible} eligible rows complete.",
        f"- Survival status and observation fields: {result['eligible_survival_complete']}/{eligible} rows complete. Exact hit durations are present for {result['eligible_time_to_target_hit_durations']} rows; {result['eligible_intentionally_null_censored_durations']} censored durations are intentionally null.",
        f"- Key secondary outcome (`r_60`): {result['eligible_r60_complete']}/{eligible} eligible rows complete.",
        f"- Prespecified controls: {result['eligible_controls_complete']}/{eligible} eligible rows have all six controls; individual completeness: "
        + ", ".join(f"`{column}` {count}/{eligible}" for column, count in result["control_completeness"].items())
        + ".",
        f"- Complete rows available by field requirements: primary Cox inputs {result['primary_analysis_available']}; secondary `R_60` inputs plus controls {result['secondary_r60_analysis_available']}.",
        "",
        "## Readiness Thresholds and Limitations",
        "",
        f"The total event set ({total}) and the primary eligible sample ({eligible}) both exceed 100, meeting the project's descriptive **excellent** category. These are descriptive thresholds only; no inferential adequacy or statistical power is asserted.",
        f"This is directional asymmetry in **exposure availability**: the historical reference-price range did not cover the profile region for 22 UP events (13.6%) and 2 DOWN events (1.2%). It is not missing outcome data and is not a detector failure. All 24 rows remain in the event table with `{PROFILE_MISSING_REASON}`; their VA remains missing and is not imputed.",
        "Later analysis must report exposure-availability patterns by direction before interpreting pooled results. This block applies no correction, weighting method, or additional exclusion rule.",
        censor_note,
        "All 75 right-censored outcomes are preserved in the full table; 69 occur in the VA-eligible sample. Outcome missingness is zero in the eligible sample.",
        "",
        "## Next Step",
        "",
        "GO WITH CAUTION means the saved eligible sample and required fields are ready to proceed to Day 3 Block 3 under its approved scope, with the directional exposure-availability asymmetry reported and examined before interpreting pooled results. It does not authorize changes to the frozen specification or imply a positive, negative, or null VA–outcome relationship.",
        "",
    ]
    return "\n".join(lines)


def write_report(report: str, output_path: Path = REPORT_PATH) -> Path:
    output_root = OUTPUT_DIR.resolve()
    target = Path(output_path).resolve()
    try:
        target.relative_to(output_root)
    except ValueError as error:
        raise ValueError("Assessment report must be written inside reports/day3/block2_sample_size/") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def run_assessment(events_path: Path = EVENTS_PATH, block1_report_path: Path = BLOCK1_REPORT_PATH) -> Dict[str, Any]:
    for path in (events_path, block1_report_path):
        if not Path(path).is_file():
            raise FileNotFoundError(f"Required readiness input is missing: {path}")
    events = pd.read_csv(events_path, low_memory=False)
    block1_report = Path(block1_report_path).read_text(encoding="utf-8")
    return assess_sample_size(events, block1_report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=EVENTS_PATH)
    parser.add_argument("--block1-report", type=Path, default=BLOCK1_REPORT_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    arguments = parser.parse_args()
    result = run_assessment(arguments.events, arguments.block1_report)
    path = write_report(render_report(result), arguments.output)
    print(f"Total event occurrences: {result['total_events']}")
    print(f"Primary eligible events: {result['eligible_events']}")
    print(f"Available primary Cox inputs: {result['primary_analysis_available']}")
    print(f"Available secondary R60 inputs: {result['secondary_r60_analysis_available']}")
    print("Recommendation: GO WITH CAUTION")
    print(f"Report: {path.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())