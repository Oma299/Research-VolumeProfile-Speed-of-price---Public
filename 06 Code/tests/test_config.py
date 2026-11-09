"""Базовые проверки обязательных параметров конфигурации Pilot v0.1."""

import unittest

import config


class ConfigTests(unittest.TestCase):
    def test_required_parameters_match_frozen_specification(self) -> None:
        expected_parameters = {
            "SYMBOL": "BTCUSDT",
            "MARKET": "spot",
            "TIMEZONE": "UTC",
            "PILOT_START": "2025-01-01",
            "PILOT_END": "2025-06-30",
            "WARMUP_START": "2024-11-01",
            "BOX_LENGTH": 32,
            "BOX_MAX_AGE": 32,
            "WIDTH_QUANTILE": 0.20,
            "WIDTH_LOOKBACK_DAYS": 60,
            "ER_THRESHOLD": 0.30,
            "CENTRAL_CLOSES_MIN": 23,
            "ATR_LENGTH": 14,
            "BREAKOUT_BUFFER_ATR": 0.10,
            "PROFILE_LOOKBACK_DAYS": 30,
            "BIN_WIDTH_ATR": 0.05,
            "AHEAD_DISTANCE_ATR": 1.0,
            "REFERENCE_DISTANCE_ATR": 5.0,
            "TARGET_ATR": 1.0,
            "MAX_HORIZON_MINUTES": 240,
        }

        for parameter_name, expected_value in expected_parameters.items():
            with self.subTest(parameter=parameter_name):
                self.assertEqual(getattr(config, parameter_name), expected_value)

    def test_periods_and_numeric_parameters_have_valid_types(self) -> None:
        for parameter_name in ("PILOT_START", "PILOT_END", "WARMUP_START"):
            with self.subTest(parameter=parameter_name):
                self.assertIsInstance(getattr(config, parameter_name), str)

        numeric_parameters = (
            "BOX_LENGTH",
            "BOX_MAX_AGE",
            "WIDTH_QUANTILE",
            "WIDTH_LOOKBACK_DAYS",
            "ER_THRESHOLD",
            "CENTRAL_CLOSES_MIN",
            "ATR_LENGTH",
            "BREAKOUT_BUFFER_ATR",
            "PROFILE_LOOKBACK_DAYS",
            "BIN_WIDTH_ATR",
            "AHEAD_DISTANCE_ATR",
            "REFERENCE_DISTANCE_ATR",
            "TARGET_ATR",
            "MAX_HORIZON_MINUTES",
        )
        for parameter_name in numeric_parameters:
            with self.subTest(parameter=parameter_name):
                self.assertIsInstance(getattr(config, parameter_name), (int, float))
                self.assertGreater(getattr(config, parameter_name), 0)


if __name__ == "__main__":
    unittest.main()