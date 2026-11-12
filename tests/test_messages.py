import datetime as dt
import unittest

from power_herald.messages import generator_state_change_message, group_state_change_message


class GeneratorStateChangeMessageTests(unittest.TestCase):
    def test_pause_includes_maintenance_duration_and_end_time(self):
        message = generator_state_change_message(
            "generator",
            None,
            "offline",
            maintenance_duration=dt.timedelta(minutes=90),
            next_working_window="12:30",
        )

        self.assertEqual(
            message,
            "⏸ Генератор призупинено (generator)\n"
            "⏱ Технічна перерва: 1 год. 30 хв.\n"
            "⏱ Кінець технічної перерви 12:30",
        )

    def test_stop_does_not_mention_maintenance(self):
        message = generator_state_change_message("generator", None, "offline")

        self.assertEqual(message, "⚠️ Генератор зупинено (generator)")


class GroupStateChangeMessageTests(unittest.TestCase):
    def test_same_durations_are_reported_once(self):
        message = group_state_change_message(
            "group",
            None,
            "offline",
            [("first", dt.timedelta(hours=2)), ("second", dt.timedelta(hours=2))],
        )

        self.assertEqual(message, "❌ Світло зникло (group)\n⏱ Було 2 год.")

    def test_durations_with_same_minute_period_are_reported_once(self):
        message = group_state_change_message(
            "group",
            None,
            "offline",
            [
                ("first", dt.timedelta(minutes=1, seconds=10)),
                ("second", dt.timedelta(minutes=1, seconds=59)),
            ],
        )

        self.assertEqual(message, "❌ Світло зникло (group)\n⏱ Було 1 хв.")

    def test_different_durations_are_reported_per_source(self):
        message = group_state_change_message(
            "group",
            None,
            "online",
            [("first", dt.timedelta(hours=2)), ("second", dt.timedelta(hours=1))],
        )

        self.assertEqual(
            message,
            "✅ Світло з'явилось (group)\n⏱ first: не було 2 год.\n⏱ second: не було 1 год.",
        )

    def test_single_source_keeps_its_name_and_duration(self):
        message = group_state_change_message(
            "group",
            None,
            "offline",
            [("first", dt.timedelta(hours=2))],
        )

        self.assertEqual(message, "❌ Світло зникло (group)\n⏱ first: було 2 год.")

    def test_unknown_duration_prevents_combining(self):
        message = group_state_change_message(
            "group",
            None,
            "online",
            [("first", None), ("second", dt.timedelta(hours=2))],
        )

        self.assertEqual(
            message,
            "✅ Світло з'явилось (group)\n⏱ first: не було (невідомо)\n⏱ second: не було 2 год.",
        )
