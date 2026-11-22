import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

with patch("sqlalchemy.create_engine"), patch("aiogram.Bot"):
    from power_herald.outage_reminder import next_outage, send_outage_reminders

from power_herald.cli import build_parser, list_notifications
from power_herald.models import Base, Chat, Outage, OutageGroup, OutageReminderNotification


class OutageReminderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.now = dt.datetime(2026, 1, 1, 9, 49, tzinfo=dt.timezone.utc)
        self.config = SimpleNamespace(
            notifications_next_scheduled_outage_reminder=600,
            timezone=dt.timezone.utc, now=lambda: self.now,
        )
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.message = {
            "emergency": False,
            "thursday": [{"start": "10:00", "end": "12:00", "status": "offline"}],
        }
        with self.sessions() as session:
            session.add_all([
                OutageGroup(id=1, name="First", external_id="1", districts=[]),
                OutageGroup(id=2, name="Second", external_id="2", districts=[]),
                Chat(id=1, chat_id="101", outage_group_id=1, enabled=True, thread_id=42),
                Chat(id=2, chat_id="102", outage_group_id=1, enabled=False),
                Chat(id=3, chat_id="103", outage_group_id=2, enabled=True),
                Chat(id=4, chat_id="104", enabled=True),
                Outage(outage_group_id=1, message_hash="first", message=self.message),
                Outage(outage_group_id=2, message_hash="second", message={"emergency": True}),
            ])
            session.commit()
        self.patches = [
            patch("power_herald.outage_reminder.Session", self.sessions),
            patch("power_herald.outage_reminder.config", self.config),
            patch("power_herald.outage_reminder.bot", self.bot),
            patch("power_herald.outage_reminder.is_emergency", return_value=False),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    async def test_lead_time_deduplication_and_cli(self):
        await send_outage_reminders()
        self.bot.send_message.assert_not_awaited()
        self.now += dt.timedelta(minutes=1)
        await send_outage_reminders()
        await send_outage_reminders()
        self.bot.send_message.assert_awaited_once_with(
            "101", "⏰ За 10 хв. заплановано відключення електроенергії о 10:00.",
            message_thread_id=42,
        )
        with self.sessions() as session:
            args = build_parser().parse_args(["outage-reminders", "--chat-id", "1", "--outage-group-id", "1"])
            records = list_notifications(session, OutageReminderNotification, args)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].starts_at, dt.datetime(2026, 1, 1, 10))

    async def test_late_expired_disabled_and_emergency(self):
        self.now = dt.datetime(2026, 1, 1, 9, 59, 30, tzinfo=dt.timezone.utc)
        self.config.notifications_next_scheduled_outage_reminder = None
        await send_outage_reminders()
        self.config.notifications_next_scheduled_outage_reminder = 600
        with patch("power_herald.outage_reminder.is_emergency", return_value=True):
            await send_outage_reminders()
        self.bot.send_message.assert_not_awaited()
        await send_outage_reminders()
        self.assertIn("1 хв.", self.bot.send_message.await_args.args[1])
        self.now += dt.timedelta(seconds=30)
        await send_outage_reminders()
        self.bot.send_message.assert_awaited_once()

    async def test_failed_send_retries_and_schedule_change_is_used(self):
        self.now += dt.timedelta(minutes=6)
        with self.sessions() as session:
            session.add(Chat(id=5, chat_id="105", outage_group_id=1, enabled=True))
            session.commit()
        self.bot.send_message.side_effect = [TelegramAPIError(method=Mock(), message="failed"), None, None]
        await send_outage_reminders()
        await send_outage_reminders()
        self.assertEqual([call.args[0] for call in self.bot.send_message.await_args_list], ["101", "105", "101"])
        with self.sessions() as session:
            session.add(Outage(outage_group_id=1, message_hash="new", message={
                "thursday": [{"start": "09:54", "end": "12:00", "status": "offline"}],
            }))
            session.commit()
        await send_outage_reminders()
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_next_day_and_continuous_midnight_outage(self):
        self.now = dt.datetime(2026, 1, 1, 23, 55, tzinfo=dt.timezone.utc)
        with self.sessions() as session:
            session.add(Outage(outage_group_id=1, message_hash="tomorrow", message={
                "friday": [{"start": "00:00", "end": "02:00", "status": "offline"}],
            }))
            session.commit()
        await send_outage_reminders()
        self.assertIn("00:00", self.bot.send_message.await_args.args[1])
        continuous = {
            "thursday": [{"start": "23:00", "end": "24:00", "status": "offline"}],
            "friday": [{"start": "00:00", "end": "02:00", "status": "offline"}],
        }
        self.assertNotEqual(next_outage(continuous, self.now).date(), dt.date(2026, 1, 2))

    async def test_changed_schedule_is_rechecked_between_chats(self):
        self.now += dt.timedelta(minutes=6)
        with self.sessions() as session:
            session.add(Chat(id=5, chat_id="105", outage_group_id=1, enabled=True))
            session.commit()

        async def change_schedule(*args, **kwargs):
            with self.sessions() as session:
                session.add(Outage(outage_group_id=1, message_hash="new", message={
                    "thursday": [{"start": "11:00", "end": "12:00", "status": "offline"}],
                }))
                session.commit()

        self.bot.send_message.side_effect = change_schedule
        await send_outage_reminders()
        self.bot.send_message.assert_awaited_once()
        self.now = dt.datetime(2026, 1, 1, 10, 50, tzinfo=dt.timezone.utc)
        self.bot.send_message.side_effect = None
        await send_outage_reminders()
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_local_time_and_unspecified_day(self):
        self.config.timezone = ZoneInfo("Europe/Kyiv")
        self.now = dt.datetime(2026, 1, 1, 7, 50, tzinfo=dt.timezone.utc)
        await send_outage_reminders()
        self.assertIn("10:00", self.bot.send_message.await_args.args[1])
        self.message["unspecified"] = ["thursday"]
        next_start = next_outage(self.message, self.now)
        self.assertIsNone(next_start)
