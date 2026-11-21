import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

with patch("sqlalchemy.create_engine"), patch("aiogram.Bot"):
    from power_herald.generator import send_stop_reminders

from power_herald.models import (
    Base, Chat, GeneratorSource, GeneratorStopNotification, PowerSource,
    PowerSourceType, SourceState, StateChange, StateChangeType,
)
from power_herald.cli import build_parser, list_notifications


class GeneratorReminderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.start = dt.datetime(2026, 1, 1, 8, 3, tzinfo=dt.timezone.utc)
        self.now = dt.datetime(2026, 1, 1, 8, 44, tzinfo=dt.timezone.utc)
        self.config = SimpleNamespace(
            generator_stop_reminder=900, generator_rounding=600,
            timezone=dt.timezone.utc, now=lambda: self.now,
        )
        self.bot = SimpleNamespace(send_message=AsyncMock())
        with self.sessions() as session:
            session.add_all([
                PowerSource(id=1, name="Generator", type=PowerSourceType.MANUAL,
                            enabled=True, is_generator=True,
                            generator=GeneratorSource(work_duration_minutes=60)),
                PowerSource(id=2, name="Other", type=PowerSourceType.MANUAL,
                            enabled=True, is_generator=False,
                            generator=GeneratorSource(work_duration_minutes=60)),
                Chat(id=1, chat_id="101", source_id=1, enabled=True, is_private=True),
                Chat(id=2, chat_id="102", source_id=1, enabled=False, is_private=True),
                Chat(id=3, chat_id="103", source_id=1, enabled=True, is_private=False),
                Chat(id=4, chat_id="104", source_id=2, enabled=True, is_private=True),
                StateChange(id=1, source_id=1, state=StateChangeType.ONLINE, timestamp=self.start),
                SourceState(source_id=1, state=StateChangeType.ONLINE, last_updated_at=self.start),
                StateChange(id=2, source_id=2, state=StateChangeType.ONLINE, timestamp=self.start),
                SourceState(source_id=2, state=StateChangeType.ONLINE, last_updated_at=self.start),
            ])
            session.commit()
        self.patches = [
            patch("power_herald.generator.Session", self.sessions),
            patch("power_herald.generator.config", self.config),
            patch("power_herald.generator.bot", self.bot),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    async def test_reminder_uses_rounded_deadline_and_is_persisted_per_chat_and_run(self):
        await send_stop_reminders()
        self.bot.send_message.assert_not_awaited()

        self.now += dt.timedelta(minutes=1)
        await send_stop_reminders()
        self.bot.send_message.assert_awaited_once_with(
            "101", "За 15 хв. необхідно зупинити генератор Generator на технічну перерву.",
            message_thread_id=None,
        )
        await send_stop_reminders()
        self.assertEqual(self.bot.send_message.await_count, 1)
        with self.sessions() as session:
            self.assertEqual(session.query(GeneratorStopNotification).count(), 1)
            arguments = build_parser().parse_args([
                "generator-stop-notifications", "--state-change-id", "1", "--chat-id", "1",
            ])
            self.assertEqual(len(list_notifications(session, GeneratorStopNotification, arguments)), 1)
            session.add_all([
                StateChange(source_id=1, state=StateChangeType.OFFLINE, timestamp=self.now),
                SourceState(source_id=1, state=StateChangeType.OFFLINE, last_updated_at=self.now),
            ])
            session.commit()
        await send_stop_reminders()
        self.assertEqual(self.bot.send_message.await_count, 1)

        self.now += dt.timedelta(minutes=1)
        with self.sessions() as session:
            session.add_all([
                StateChange(source_id=1, state=StateChangeType.ONLINE, timestamp=self.now),
                SourceState(source_id=1, state=StateChangeType.ONLINE, last_updated_at=self.now),
            ])
            session.commit()
        self.now = dt.datetime(2026, 1, 1, 9, 36, tzinfo=dt.timezone.utc)
        await send_stop_reminders()
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_late_reminder_uses_remaining_time_and_skips_expired_deadline(self):
        self.now = dt.datetime(2026, 1, 1, 8, 59, 30, tzinfo=dt.timezone.utc)
        await send_stop_reminders()
        self.assertIn("1 хв.", self.bot.send_message.await_args.args[1])
        with self.sessions() as session:
            session.query(GeneratorStopNotification).delete()
            session.commit()
        self.now = dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
        await send_stop_reminders()
        self.assertEqual(self.bot.send_message.await_count, 1)

    async def test_remaining_time_rounds_to_nearest_minute(self):
        deadline = dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.timezone.utc)
        for seconds, expected in ((29.999, "0 хв."), (30, "1 хв."),
                                  (89.999, "1 хв."), (90, "2 хв.")):
            with self.subTest(seconds=seconds):
                with self.sessions() as session:
                    session.query(GeneratorStopNotification).delete()
                    session.commit()
                self.bot.send_message.reset_mock()
                self.now = deadline - dt.timedelta(seconds=seconds)
                await send_stop_reminders()
                self.bot.send_message.assert_awaited_once_with(
                    "101",
                    f"За {expected} необхідно зупинити генератор Generator на технічну перерву.",
                    message_thread_id=None,
                )

    async def test_short_run_is_reminded_immediately_with_actual_remaining_time(self):
        with self.sessions() as session:
            session.get(GeneratorSource, 1).work_duration_minutes = 10
            session.commit()
        self.now = self.start
        await send_stop_reminders()
        self.assertIn("7 хв.", self.bot.send_message.await_args.args[1])

    async def test_disabled_reminder_does_not_send(self):
        self.config.generator_stop_reminder = None
        await send_stop_reminders()
        self.bot.send_message.assert_not_awaited()

    async def test_failed_send_is_retried_without_blocking_other_chats(self):
        with self.sessions() as session:
            session.add(Chat(id=5, chat_id="105", source_id=1, enabled=True, is_private=True))
            session.commit()
        self.now = dt.datetime(2026, 1, 1, 8, 50, tzinfo=dt.timezone.utc)
        self.bot.send_message.side_effect = [
            TelegramAPIError(method=Mock(), message="failed"), None, None,
        ]
        await send_stop_reminders()
        await send_stop_reminders()
        self.assertEqual([call.args[0] for call in self.bot.send_message.await_args_list],
                         ["101", "105", "101"])
        with self.sessions() as session:
            self.assertEqual(session.query(GeneratorStopNotification).count(), 2)

    async def test_stop_during_send_cancels_reminders_for_other_chats(self):
        with self.sessions() as session:
            session.add(Chat(id=5, chat_id="105", source_id=1, enabled=True, is_private=True))
            session.commit()
        self.now = dt.datetime(2026, 1, 1, 8, 50, tzinfo=dt.timezone.utc)

        async def stop_generator(*args, **kwargs):
            with self.sessions() as session:
                session.add_all([
                    StateChange(source_id=1, state=StateChangeType.OFFLINE, timestamp=self.now),
                    SourceState(source_id=1, state=StateChangeType.OFFLINE, last_updated_at=self.now),
                ])
                session.commit()

        self.bot.send_message.side_effect = stop_generator
        await send_stop_reminders()
        self.bot.send_message.assert_awaited_once()
