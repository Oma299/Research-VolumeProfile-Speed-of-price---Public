"""Focused tests for descriptive sample-size readiness assessment."""

import tempfile
import unittest
import hashlib
from pathlib import Path

import pandas as pd

import sample_size_assessment as assessment


class SampleSizeAssessmentTests(unittest.TestCase):
    def _inputs(self):
        events = pd.read_csv(assessment.EVENTS_PATH, low_memory=False)
        report = assessment.BLOCK1_REPORT_PATH.read_text(encoding="utf-8")
        return events, report

    def test_persisted_counts_and_readiness_are_deterministic(self) -> None:
        events, report = self._inputs()
        original = events.copy(deep=True)

        first = assessment.assess_sample_size(events, report)
        second = assessment.assess_sample_size(events.sample(frac=1, random_state=4), report)

        self.assertEqual(first, second)
        self.assertEqual(first["total_events"], 324)
        self.assertEqual(first["unique_event_ids"], 324)
        self.assertEqual(first["eligible_events"], 300)
        self.assertEqual(first["missing_profile_events"], 24)
        self.assertEqual(first["missing_profile_reasons"], {assessment.PROFILE_MISSING_REASON: 24})
        self.assertEqual(first["missing_profile_by_direction"], {"downward": 2, "upward": 22})
        self.assertEqual(first["total_by_direction"], {"downward": 162, "upward": 162})
        self.assertEqual(first["eligible_by_direction"], {"downward": 160, "upward": 140})
        self.assertEqual(first["eligible_target_hits"], 231)
        self.assertEqual(first["eligible_right_censored"], 69)
        self.assertEqual(first["primary_analysis_available"], 300)
        self.assertEqual(first["secondary_r60_analysis_available"], 300)
        self.assertEqual(first["eligible_threshold_category"], "excellent (>100)")
        pd.testing.assert_frame_equal(events, original)

    def test_target_hits_censoring_and_intentional_null_duration_are_distinct(self) -> None:
        events, report = self._inputs()
        result = assessment.assess_sample_size(events, report)

        self.assertEqual(result["total_target_hits"], 249)
        self.assertEqual(result["total_right_censored"], 75)
        self.assertEqual(result["eligible_time_to_target_hit_durations"], 231)
        self.assertEqual(result["eligible_intentionally_null_censored_durations"], 69)
        self.assertEqual(result["eligible_outcome_missing"], 0)

    def test_report_distinguishes_event_counts_and_outcome_occurrences(self) -> None:
        events, block1 = self._inputs()
        report = assessment.render_report(assessment.assess_sample_size(events, block1))

        self.assertIn("Total detected breakout event occurrences:** 324", report)
        self.assertIn("Target-hit event occurrences in the eligible sample:** 231", report)
        self.assertIn("Right-censored event occurrences in the eligible sample:** 69", report)
        self.assertIn("Right-censored observations are complete 240-minute no-hit outcomes", report)
        self.assertIn("post-hoc power analysis was performed", report)
        self.assertIn("Total detected breakout event occurrences:** 324", report)
        self.assertIn("Primary-analysis-eligible events with valid VA:** 300", report)

    def test_report_flags_directional_exposure_availability_asymmetry(self) -> None:
        events, block1 = self._inputs()
        result = assessment.assess_sample_size(events, block1)
        report = assessment.render_report(result)

        self.assertIn("GO WITH CAUTION", report)
        self.assertIn("UP profile-missing 22/162 (13.6%)", report)
        self.assertIn("DOWN profile-missing 2/162 (1.2%)", report)
        self.assertIn("directional asymmetry in **exposure availability**", report)
        self.assertIn("It is not missing outcome data and is not a detector failure", report)
        self.assertIn("with `reference_region_outside_historical_range`", report)
        self.assertIn("Later analysis must report exposure-availability patterns by direction before interpreting pooled results", report)
        self.assertIn("no correction, weighting method, or additional exclusion rule", report)

    def test_file_based_assessment_does_not_modify_input_artifacts(self) -> None:
        source_paths = (assessment.EVENTS_PATH, assessment.BLOCK1_REPORT_PATH)
        before = {
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in source_paths
        }

        result = assessment.run_assessment()

        after = {
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in source_paths
        }
        self.assertEqual(before, after)
        self.assertEqual(result["total_events"], 324)

    def test_report_writer_is_confined_to_approved_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "reports" / "day3" / "block2_sample_size"
            path = root / "SAMPLE_SIZE_ASSESSMENT.md"
            original_root = assessment.OUTPUT_DIR
            try:
                assessment.OUTPUT_DIR = root
                written = assessment.write_report("readiness", path)
                self.assertEqual(written, path.resolve())
                self.assertEqual(written.read_text(encoding="utf-8"), "readiness")
                with self.assertRaisesRegex(ValueError, "inside reports/day3/block2_sample_size"):
                    assessment.write_report("outside", Path(temporary) / "outside.md")
            finally:
                assessment.OUTPUT_DIR = original_root


if __name__ == "__main__":
    unittest.main()