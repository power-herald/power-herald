import datetime as dt
import tempfile
import unittest
from pathlib import Path

from power_herald.config import Config, parse_duration, round_datetime_to_interval


class ParseDurationTests(unittest.TestCase):
    def test_parses_seconds_minutes_and_hours(self):
        self.assertEqual(parse_duration("10s", "duration"), 10)
        self.assertEqual(parse_duration("10m", "duration"), 600)
        self.assertEqual(parse_duration("1h", "duration"), 3600)


class GeneratorRoundingTests(unittest.TestCase):
    def test_default_rounding_is_ten_minutes(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("{}")

            self.assertEqual(Config(str(config_path)).generator_rounding, 600)

    def test_rounding_can_be_configured_in_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("generator:\n  rounding: 1h\n")

            self.assertEqual(Config(str(config_path)).generator_rounding, 3600)

    def test_rounds_calculated_timestamp_not_duration(self):
        timestamp = dt.datetime(2026, 1, 1, 12, 0) + dt.timedelta(minutes=48)

        rounded_timestamp = round_datetime_to_interval(timestamp, 10 * 60)

        self.assertEqual(rounded_timestamp, dt.datetime(2026, 1, 1, 12, 50))

    def test_rounds_timestamp_across_midnight(self):
        timestamp = dt.datetime(2026, 1, 1, 23, 58)

        rounded_timestamp = round_datetime_to_interval(timestamp, 10 * 60)

        self.assertEqual(rounded_timestamp, dt.datetime(2026, 1, 2, 0, 0))


class GeneratorReminderConfigTests(unittest.TestCase):
    def test_reminder_is_disabled_by_default_and_accepts_a_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("{}")
            self.assertIsNone(Config(str(config_path)).generator_stop_reminder)
            config_path.write_text("generator:\n  stop_reminder: 15m\n")
            self.assertEqual(Config(str(config_path)).generator_stop_reminder, 900)
            config_path.write_text("generator:\n  stop_reminder: false\n")
            self.assertIsNone(Config(str(config_path)).generator_stop_reminder)
            config_path.write_text("generator:\n  stop_reminder: invalid\n")
            with self.assertRaisesRegex(ValueError, "generator.stop_reminder"):
                Config(str(config_path)).generator_stop_reminder

    def test_outage_reminder_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            for value, expected in (("", None), ("false", None), ("10m", 600)):
                config_path.write_text(f"notifications:\n  next_scheduled_outage_reminder: {value}\n")
                self.assertEqual(Config(str(config_path)).notifications_next_scheduled_outage_reminder, expected)
            config_path.write_text("notifications:\n  next_scheduled_outage_reminder: invalid\n")
            with self.assertRaisesRegex(ValueError, "notifications.next_scheduled_outage_reminder"):
                Config(str(config_path)).notifications_next_scheduled_outage_reminder
