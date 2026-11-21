import datetime as dt
import unittest
from unittest.mock import Mock, patch

with patch("sqlalchemy.create_engine"), patch("aiogram.Bot"):
    from power_herald.notify import generator_notification_message
from power_herald.models import StateChangeType


class GeneratorNotificationMessageTests(unittest.TestCase):
    def _message(self, state, period=None, maintenance_pause=False):
        source = Mock()
        source.id = 7
        source.name = "Generator"
        source.description = None
        source.generator.work_duration_minutes = 60
        source.generator.maintenance_duration_minutes = 30

        query = Mock()
        query.filter.return_value.order_by.return_value.first.return_value = period
        session = Mock()
        session.query.return_value = query

        timestamp = dt.datetime(2025, 1, 1, 8, 0, tzinfo=dt.timezone.utc)
        with patch(
            "power_herald.notify.round_datetime_to_interval",
            side_effect=[
                dt.datetime(2025, 1, 1, 9, 0, tzinfo=dt.timezone.utc),
                dt.datetime(2025, 1, 1, 9, 30, tzinfo=dt.timezone.utc),
            ],
        ) as round_time:
            message = generator_notification_message(
                session,
                source,
                state,
                timestamp,
                maintenance_pause,
            )
        return message, round_time

    def test_started_includes_maintenance_window(self):
        message, round_time = self._message(StateChangeType.ONLINE)

        self.assertIn("⏱ Технічна перерва 09:00 - 09:30", message)
        self.assertEqual(round_time.call_count, 2)

    def test_paused_includes_maintenance_duration_and_next_working_window(self):
        message, round_time = self._message(StateChangeType.OFFLINE, maintenance_pause=True)

        self.assertIn("⏱ Технічна перерва: 30 хв.", message)
        self.assertIn("⏱ Кінець технічної перерви 09:00", message)
        self.assertEqual(round_time.call_count, 1)

    def test_stopped_includes_offline_duration(self):
        period = Mock(
            started_at=dt.datetime(2025, 1, 1, 6, 0, tzinfo=dt.timezone.utc),
            finished_at=dt.datetime(2025, 1, 1, 8, 0, tzinfo=dt.timezone.utc),
        )

        message, round_time = self._message(StateChangeType.OFFLINE, period=period)

        self.assertIn("⏱ Працював: 2 год.", message)
        round_time.assert_not_called()
