import datetime as dt
import unittest

from power_herald.messages import group_state_change_message


class GroupStateChangeMessageTests(unittest.TestCase):
    def test_same_durations_are_reported_once(self):
        message = group_state_change_message(
            "group",
            None,
            "offline",
            [("first", dt.timedelta(hours=2)), ("second", dt.timedelta(hours=2))],
        )

        self.assertEqual(message, "❌ Світло зникло (group)\n⏱ Було 2 год.")

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
