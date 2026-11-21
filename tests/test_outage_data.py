import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.config import Config
from power_herald.emergency import broadcast_emergency
from power_herald.messages import get_message, schedule_message_from_json
from power_herald.models import (
    Base, Chat, EmergencyNotification, Outage, OutageGroup, OutageNotification,
    OutageNotificationType,
)
from power_herald.outage_data import (
    WEEKDAYS,
    fetch_outage_data,
    has_offline_periods,
    is_unspecified,
    prepare_messages,
)
from power_herald.schedule import send_messages, send_schedule_once, update_once


class PrepareMessagesEmergencyTests(unittest.TestCase):
    def test_duplicate_group_names_are_rejected(self):
        groups = [
            OutageGroup(external_id="1", name="same", districts=[]),
            OutageGroup(external_id="2", name="same", districts=[]),
        ]
        with self.assertRaisesRegex(ValueError, "Duplicate outage group name"):
            prepare_messages({}, groups)

    def test_emergency_flags(self):
        groups = [
            OutageGroup(external_id="1", name="first", districts=["Дарницький", "Дарницкого"]),
            OutageGroup(external_id="2", name="second", districts=["Оболонський"]),
            OutageGroup(external_id="3", name="third", districts=[]),
        ]
        cases = [
            ({"enabled": True, "enabled_districts": None}, [True, True, True]),
            ({"enabled": False, "enabled_districts": "район ДАРНИЦКОГО"}, [True, False, False]),
            ({"enabled": False, "enabled_districts": None}, [False, False, False]),
            ({}, [False, False, False]),
        ]
        with patch("power_herald.outage_data.merge_data", return_value={}):
            for emergency, expected in cases:
                with self.subTest(emergency=emergency):
                    result = prepare_messages({"emergency": emergency}, groups)
                    self.assertEqual([result[group.name]["emergency"] for group in groups], expected)


class StabilizingTests(unittest.TestCase):
    groups = [OutageGroup(external_id="1", name="first", districts=[])]
    # 2026-11-08 is Sunday, 2026-11-09 is Monday.
    sunday = dt.date(2026, 11, 8)
    monday = dt.date(2026, 11, 9)

    def _prepare(self, stabilizing, merged):
        data = {"stabilizing": {"enabled": stabilizing}}
        with patch("power_herald.outage_data.merge_data", return_value=merged):
            return prepare_messages(data, self.groups)["first"]

    def test_empty_days_are_unspecified_when_stabilizing(self):
        message = self._prepare(True, {})
        self.assertEqual(message["unspecified"], list(WEEKDAYS))
        self.assertTrue(is_unspecified(message, self.sunday))

    def test_all_online_day_is_unspecified_when_stabilizing(self):
        with patch("power_herald.outage_data._periods_for_day", return_value=[("online", "00:00", "24:00")]):
            message = self._prepare(True, {"1": {"7": {"1": "yes"}}})
        self.assertIn("sunday", message["unspecified"])

    def test_day_with_offline_periods_is_specified(self):
        periods = [("offline", "00:00", "04:00"), ("online", "04:00", "24:00")]
        with patch("power_herald.outage_data._periods_for_day", return_value=periods):
            message = self._prepare(True, {})
        self.assertEqual(message["unspecified"] if "unspecified" in message else [], [])
        self.assertFalse(is_unspecified(message, self.sunday))

    def test_not_unspecified_without_stabilizing(self):
        message = self._prepare(False, {})
        self.assertNotIn("unspecified", message)
        self.assertFalse(has_offline_periods({"first": message}, self.sunday))

    def test_has_offline_periods_true_when_unspecified(self):
        message = self._prepare(True, {})
        self.assertTrue(has_offline_periods({"first": message}, self.sunday))

    def test_messages_use_unspecified_keys(self):
        message = self._prepare(True, {})
        today_text = schedule_message_from_json(message, today=True, date=self.sunday.isoformat())
        tomorrow_text = schedule_message_from_json(message, today=False, date=self.monday.isoformat())
        self.assertIn("стабілізаційні", today_text)
        self.assertIn("стабілізаційні", tomorrow_text)
        plain = self._prepare(False, {})
        self.assertNotIn("стабілізаційні", schedule_message_from_json(plain, date=self.sunday.isoformat()))


class AutomaticEmergencyTests(unittest.IsolatedAsyncioTestCase):
    def seed_groups(self, engine, groups):
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as session:
            session.add_all(groups)
            session.commit()

    async def test_schedule_messages_go_only_to_assigned_enabled_chats(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [
            OutageGroup(external_id="1", name="first", districts=[]),
            OutageGroup(external_id="2", name="second", districts=[]),
        ])
        with sessionmaker(bind=engine)() as session:
            session.add_all([
                Chat(chat_id="first", enabled=True, outage_group_id=1, thread_id=42),
                Chat(chat_id="also-first", enabled=True, outage_group_id=1),
                Chat(chat_id="second", enabled=True, outage_group_id=2),
                Chat(chat_id="unassigned", enabled=True),
                Chat(chat_id="disabled", enabled=False, outage_group_id=1),
            ])
            session.commit()
        config = Mock(db_url="sqlite://", db_engine_options={})
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock(send_message=AsyncMock())
        bot.session.close = AsyncMock()
        messages = [
            {"name": "first", "outage_group_id": 1, "emergency": False},
            {"name": "second", "outage_group_id": 2, "emergency": False},
        ]
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.schedule_message_from_json",
            side_effect=lambda message, **kwargs: message["name"],
        ):
            await send_messages("token", messages, date=dt.date(2026, 11, 8))
            self.assertEqual(bot.send_message.await_args_list, [
                call("first", "first", message_thread_id=42, parse_mode="MarkdownV2"),
                call("also-first", "first", message_thread_id=None, parse_mode="MarkdownV2"),
                call("second", "second", message_thread_id=None, parse_mode="MarkdownV2"),
            ])
            bot.session.close.assert_awaited_once()

    async def test_update_and_timed_schedule_use_current_chat_assignment(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [
            OutageGroup(external_id="1", name="first", districts=[]),
            OutageGroup(external_id="2", name="second", districts=[]),
        ])
        with sessionmaker(bind=engine)() as session:
            session.add(Chat(chat_id="chat", enabled=True, outage_group_id=1))
            session.commit()
        config = Mock(db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token")
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock(send_message=AsyncMock())
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", return_value={}
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.schedule_message_from_json",
            side_effect=lambda message, **kwargs: message["name"],
        ):
            await update_once()
            self.assertEqual([item.args[1] for item in bot.send_message.await_args_list], ["first"])
            with sessionmaker(bind=engine)() as session:
                session.query(Chat).one().outage_group_id = 2
                session.commit()
            bot.send_message.reset_mock()
            await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9))
            self.assertEqual([item.args[1] for item in bot.send_message.await_args_list], ["second"])

    async def test_schedule_reads_updated_groups_from_database(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [OutageGroup(external_id="old", name="first", districts=[])])
        config = Mock(db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token")
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        feed = {
            "preset": {
                "data": {"new": {"1": {"1": "no"}}},
                "time_zone": {"1": ["", "00:00", "01:00"]},
            },
        }
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", return_value=feed
        ), patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            with sessionmaker(bind=engine)() as session:
                group = session.get(OutageGroup, 1)
                group.external_id = "new"
                group.name = "updated"
                session.commit()
            with sessionmaker(bind=engine)() as session:
                outage = session.query(Outage).order_by(Outage.id.desc()).first()
                self.assertEqual(outage.outage_group_id, 1)
                self.assertEqual(outage.outage_group.name, "updated")
            self.assertTrue(await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9)))
            message = send.await_args.args[1][0]
            self.assertEqual(message["name"], "updated")
            self.assertEqual(message["monday"], [{"start": "00:00", "end": "01:00", "status": "offline"}])
            await update_once()
            self.assertEqual(send.await_args.args[1][0]["name"], "updated")

    async def test_forced_update_resends_previously_notified_schedule(self):
        for notification_type in OutageNotificationType:
            with self.subTest(notification_type=notification_type):
                engine = create_engine("sqlite://")
                self.addCleanup(engine.dispose)
                self.seed_groups(engine, [OutageGroup(external_id="1", name="first", districts=[])])
                with sessionmaker(bind=engine)() as session:
                    session.add(Chat(chat_id="chat", enabled=True, outage_group_id=1))
                    session.commit()
                config = Mock(
                    db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
                )
                config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
                bot = Mock(send_message=AsyncMock())
                bot.session.close = AsyncMock()
                with patch("power_herald.schedule.config", config), patch(
                    "power_herald.schedule.create_engine", return_value=engine
                ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
                    "power_herald.schedule.fetch_outage_data", return_value={}
                ), patch("power_herald.schedule.Bot", return_value=bot), patch(
                    "power_herald.schedule.schedule_message_from_json", return_value="schedule"
                ):
                    await update_once()
                    with sessionmaker(bind=engine)() as session:
                        session.query(OutageNotification).one().type = notification_type
                        session.commit()
                    bot.send_message.reset_mock()
                    await update_once(force=True)
                    bot.send_message.assert_awaited_once_with(
                        "chat", "schedule", message_thread_id=None, parse_mode="MarkdownV2",
                    )
                    bot.send_message.reset_mock()
                    await update_once()
                    bot.send_message.assert_not_awaited()
                with sessionmaker(bind=engine)() as session:
                    self.assertEqual(session.query(Outage).count(), 1)
                    self.assertEqual(session.query(OutageNotification).count(), 2)

    async def test_forced_update_respects_emergency_conditions(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [
            OutageGroup(external_id="1", name="first", districts=["First"]),
            OutageGroup(external_id="2", name="second", districts=["Second"]),
        ])
        config = Mock(db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token")
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", side_effect=[False, False, True]), patch(
            "power_herald.schedule.fetch_outage_data",
            return_value={"emergency": {"enabled_districts": "First"}},
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ) as broadcast, patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            await update_once(force=True)
            self.assertEqual([message["name"] for message in send.await_args.args[1]], ["second"])
            self.assertEqual(broadcast.await_count, 1)
            send.reset_mock()
            self.assertFalse(await update_once(force=True))
            send.assert_not_awaited()

    async def test_update_checks_tomorrow_hash_even_when_immediate_is_newer(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        messages = [
            {"first": {
                "name": "first", "outage_group_id": 1, "emergency": False,
                "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
            }},
            {"first": {
                "name": "first", "outage_group_id": 1, "emergency": False,
                "sunday": [{"start": "04:00", "end": "08:00", "status": "offline"}],
            }},
        ]
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data",
            side_effect=[{"revision": 1}, {"revision": 2}, {"revision": 3}],
        ), patch(
            "power_herald.schedule.prepare_messages", side_effect=[messages[0], messages[1], messages[0]]
        ), patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            await update_once()
            with sessionmaker(bind=engine)() as session:
                first_notification = (
                    session.query(OutageNotification)
                    .order_by(OutageNotification.id)
                    .first()
                )
                first_notification.type = OutageNotificationType.TOMORROW
                first_notification.posted_at = config.now() - dt.timedelta(days=1)
                session.commit()
            await update_once()

        self.assertEqual([call.args[1] for call in send.await_args_list], [
            [messages[0]["first"]],
            [messages[1]["first"]],
            [],
        ])

    async def test_today_schedule_skips_hash_already_sent_as_immediate(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        messages = {"first": {
            "name": "first", "outage_group_id": 1, "emergency": False,
            "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
        }}
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", return_value={"revision": 1}
        ), patch("power_herald.schedule.prepare_messages", return_value=messages), patch(
            "power_herald.schedule.send_messages", new_callable=AsyncMock
        ) as send:
            await update_once()
            send.reset_mock()
            with sessionmaker(bind=engine)() as session:
                session.add(
                    OutageNotification(
                        posted_at=config.now() + dt.timedelta(minutes=1),
                        type=OutageNotificationType.TODAY,
                        posted_for=config.now().date(),
                        schedule_hash="different-hash",
                    )
                )
                session.commit()
            self.assertFalse(await send_schedule_once(OutageNotificationType.TODAY, config.now().date()))
            send.assert_not_awaited()

    async def test_update_notification_hash_uses_only_todays_schedule(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        messages = [
            {"first": {
                "name": "first", "outage_group_id": 1, "emergency": False,
                "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
                "monday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
            }},
            {"first": {
                "name": "first", "outage_group_id": 1, "emergency": False,
                "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
                "monday": [{"start": "04:00", "end": "08:00", "status": "offline"}],
            }},
            {"first": {
                "name": "first", "outage_group_id": 1, "emergency": False,
                "sunday": [{"start": "04:00", "end": "08:00", "status": "offline"}],
                "monday": [{"start": "04:00", "end": "08:00", "status": "offline"}],
            }},
        ]
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", side_effect=[{"revision": 1}, {"revision": 2}, {"revision": 3}]
        ), patch("power_herald.schedule.prepare_messages", side_effect=messages), patch(
            "power_herald.schedule.send_messages", new_callable=AsyncMock
        ) as send:
            await update_once()
            await update_once()
            await update_once()

        self.assertEqual([call.args[1] for call in send.await_args_list], [
            [messages[0]["first"]],
            [],
            [messages[2]["first"]],
        ])
        with sessionmaker(bind=engine)() as session:
            notifications = session.query(OutageNotification).order_by(OutageNotification.id).all()
            self.assertEqual(len(notifications), 2)
            self.assertNotEqual(notifications[0].schedule_hash, notifications[1].schedule_hash)

    async def test_updates_broadcast_transitions_and_skip_affected_schedules(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [
            OutageGroup(external_id="1", name="first", districts=["First"]),
            OutageGroup(external_id="2", name="second", districts=["Second"]),
        ])
        now = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = now
        bot = Mock()
        bot.session.close = AsyncMock()
        feeds = [
            {"emergency": {"enabled": False, "enabled_districts": None}},
            {"emergency": {"enabled": False, "enabled_districts": "FIRST"}},
            {"emergency": {"enabled": False, "enabled_districts": "first"}, "extra": 1},
            {"emergency": {"enabled": False, "enabled_districts": "Second"}},
            {"emergency": {"enabled": True, "enabled_districts": None}},
            {"emergency": {"enabled": False, "enabled_districts": None}},
        ]
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", side_effect=feeds
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ) as broadcast, patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            for _ in feeds:
                await update_once()
            self.assertEqual(broadcast.await_args_list, [call(bot, True), call(bot, False)])
            self.assertEqual(bot.session.close.await_count, 2)
            self.assertEqual([message["name"] for message in send.await_args_list[1].args[1]], [])
            self.assertEqual([message["name"] for message in send.await_args_list[3].args[1]], ["first"])
            self.assertEqual(send.await_args_list[4].args[1], [])
            self.assertEqual(
                [message["name"] for message in send.await_args_list[5].args[1]], ["first", "second"]
            )
        with sessionmaker(bind=engine)() as session:
            records = session.query(EmergencyNotification).order_by(EmergencyNotification.id).all()
            self.assertEqual([record.state for record in records], [True, False])
            self.assertEqual([record.posted_at for record in records], [now.replace(tzinfo=None)] * 2)

    async def test_removed_emergency_group_still_broadcasts_all_clear(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [OutageGroup(external_id="1", name="first", districts=[])])
        config = Mock(db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token")
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", return_value={"emergency": {"enabled": True}}
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ) as broadcast, patch("power_herald.schedule.send_messages", new_callable=AsyncMock):
            await update_once()
            with sessionmaker(bind=engine)() as session:
                session.delete(session.query(OutageGroup).one())
                session.query(Outage).delete()
                session.commit()
            await update_once()
            await update_once()
        self.assertEqual(broadcast.await_args_list, [call(bot, True), call(bot, False)])

    async def test_failed_emergency_broadcast_is_retried(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [OutageGroup(external_id="1", name="first", districts=[])])
        config = Mock(db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token")
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", return_value={"emergency": {"enabled": True}}
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock,
            side_effect=[RuntimeError("broadcast failed"), None],
        ) as broadcast, patch("power_herald.schedule.send_messages", new_callable=AsyncMock):
            with self.assertRaisesRegex(RuntimeError, "broadcast failed"):
                await update_once()
            with sessionmaker(bind=engine)() as session:
                self.assertEqual(session.query(EmergencyNotification).count(), 0)
            await update_once()
            await update_once()
        self.assertEqual(broadcast.await_args_list, [call(bot, True), call(bot, True)])
        with sessionmaker(bind=engine)() as session:
            self.assertEqual([record.state for record in session.query(EmergencyNotification)], [True])

    async def test_timed_schedule_skips_emergency_groups(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [OutageGroup(external_id="1", name="first", districts=["First"])])
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data",
            return_value={"emergency": {"enabled": True, "enabled_districts": None}},
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ), patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            send.reset_mock()
            result = await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9))
            self.assertFalse(result)
            send.assert_not_awaited()

    async def test_all_clear_resends_unchanged_pre_emergency_schedule(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [OutageGroup(external_id="1", name="first", districts=[])])
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data", side_effect=[
                {"emergency": {"enabled": False}},
                {"emergency": {"enabled": True}},
                {"emergency": {"enabled": False}},
            ],
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ), patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            await update_once()
            await update_once()
            self.assertEqual([message["name"] for message in send.await_args.args[1]], ["first"])

    async def test_partial_emergency_tomorrow_hash_is_target_day_scoped(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.seed_groups(engine, [
            OutageGroup(external_id="1", name="first", districts=["First"]),
            OutageGroup(external_id="2", name="second", districts=["Second"]),
        ])
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        bot = Mock()
        bot.session.close = AsyncMock()
        with patch("power_herald.schedule.config", config), patch(
            "power_herald.schedule.create_engine", return_value=engine
        ), patch("power_herald.schedule.is_emergency", return_value=False), patch(
            "power_herald.schedule.fetch_outage_data",
            return_value={"emergency": {"enabled": False, "enabled_districts": "First"}},
        ), patch("power_herald.schedule.Bot", return_value=bot), patch(
            "power_herald.schedule.broadcast_emergency", new_callable=AsyncMock
        ), patch("power_herald.schedule.send_messages", new_callable=AsyncMock) as send:
            await update_once()
            self.assertTrue(await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9)))
            self.assertEqual([message["name"] for message in send.await_args.args[1]], ["second"])
            send.reset_mock()
            self.assertFalse(await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9)))
            send.assert_not_awaited()

    async def test_broadcast_uses_manual_alert_and_enabled_chats(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as session:
            session.add_all([
                Chat(chat_id="enabled", enabled=True, thread_id=42),
                Chat(chat_id="disabled", enabled=False),
            ])
            session.commit()
        bot = Mock(send_message=AsyncMock())
        with patch("power_herald.emergency.Session", sessions):
            await broadcast_emergency(bot, True, "details")
            await broadcast_emergency(bot, False)
        self.assertEqual(bot.send_message.await_args_list, [
            call("enabled", f"{get_message('notification.emergency.enabled')}\n"
                 f"{get_message('notification.emergency.comment', comment='details')}", message_thread_id=42),
            call("enabled", get_message("notification.emergency.disabled"), message_thread_id=42),
        ])


class OutageDataSourceTests(unittest.TestCase):
    def setUp(self):
        self.config = Config.__new__(Config)
        self.config.data = {
            "outages": {
                "source": "api",
                "json_url": "https://example.com/public.json",
                "json_api": {
                    "url": "https://example.com/private.json",
                    "token": "github_pat_test",
                },
            }
        }
        self.response = Mock()
        self.response.json.return_value = {"schedule": {}}

    def test_api_sends_token(self):
        with patch("power_herald.outage_data.get_config", return_value=self.config), patch(
            "power_herald.outage_data.requests.get", return_value=self.response
        ) as get:
            self.assertEqual(fetch_outage_data(), {"schedule": {}})
        get.assert_called_once_with(
            "https://example.com/private.json",
            headers={"Authorization": "token github_pat_test"},
            timeout=30,
        )
        self.response.raise_for_status.assert_called_once()

    def test_url_does_not_send_token(self):
        with patch("power_herald.outage_data.get_config", return_value=self.config), patch(
            "power_herald.outage_data.requests.get", return_value=self.response
        ) as get:
            self.assertEqual(fetch_outage_data(source="url"), {"schedule": {}})
        get.assert_called_once_with("https://example.com/public.json", timeout=30)

    def test_file_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outages.json"
            path.write_text(json.dumps({"schedule": {}}), encoding="utf-8")
            with patch("power_herald.outage_data.get_config", return_value=self.config):
                self.assertEqual(fetch_outage_data(source="file", file_path=str(path)), {"schedule": {}})

    def test_api_requires_token(self):
        self.config.data["outages"]["json_api"]["token"] = ""
        with patch("power_herald.outage_data.get_config", return_value=self.config):
            with self.assertRaisesRegex(ValueError, "outages.json_api.token"):
                fetch_outage_data()

    def test_invalid_source(self):
        self.config.data["outages"]["source"] = "invalid"
        with self.assertRaisesRegex(ValueError, "outages.source"):
            self.config.outage_data_source


if __name__ == "__main__":
    unittest.main()