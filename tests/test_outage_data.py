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
from power_herald.models import Base, Chat, OutageNotification, OutageNotificationType
from power_herald.outage_data import (
    WEEKDAYS,
    fetch_outage_data,
    has_offline_periods,
    is_unspecified,
    prepare_messages,
)
from power_herald.schedule import send_schedule_once, update_once


class PrepareMessagesEmergencyTests(unittest.TestCase):
    def test_emergency_flags(self):
        groups = [
            {"id": "1", "name": "first", "district": ["Дарницький", "Дарницкого"]},
            {"id": "2", "name": "second", "district": ["Оболонський"]},
            {"id": "3", "name": "third"},
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
                    self.assertEqual([result[group["name"]]["emergency"] for group in groups], expected)


class StabilizingTests(unittest.TestCase):
    groups = [{"id": "1", "name": "first"}]
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
    async def test_update_notification_hash_uses_only_todays_schedule(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
            gpvs=[{"id": "1", "name": "first"}],
        )
        config.now.return_value = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        messages = [
            {"first": {
                "name": "first", "emergency": False,
                "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
                "monday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
            }},
            {"first": {
                "name": "first", "emergency": False,
                "sunday": [{"start": "00:00", "end": "04:00", "status": "offline"}],
                "monday": [{"start": "04:00", "end": "08:00", "status": "offline"}],
            }},
            {"first": {
                "name": "first", "emergency": False,
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
        now = dt.datetime(2026, 11, 8, 12, tzinfo=dt.timezone.utc)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
            gpvs=[
                {"id": "1", "name": "first", "district": ["First"]},
                {"id": "2", "name": "second", "district": ["Second"]},
            ],
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

    async def test_timed_schedule_skips_emergency_groups(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
            gpvs=[{"id": "1", "name": "first", "district": ["First"]}],
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
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
            gpvs=[{"id": "1", "name": "first"}],
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

    async def test_partial_emergency_timed_schedule_hashes_target_day(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        config = Mock(
            db_url="sqlite://", db_engine_options={}, outage_data_source="file", bot_token="token",
            gpvs=[
                {"id": "1", "name": "first", "district": ["First"]},
                {"id": "2", "name": "second", "district": ["Second"]},
            ],
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
            send.reset_mock()
            self.assertFalse(await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 8)))
            send.assert_not_awaited()
            self.assertTrue(await send_schedule_once(OutageNotificationType.TOMORROW, dt.date(2026, 11, 9)))
            self.assertEqual([message["name"] for message in send.await_args.args[1]], ["second"])

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