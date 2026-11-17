import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.cli import main
from power_herald.models import EmergencyNotification, Outage


class OutageGroupCliTests(unittest.TestCase):
    def test_emergency_notification_history_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            db_url = f"sqlite:///{Path(directory) / 'test.db'}"
            stdout = io.StringIO()
            with patch("sys.argv", ["ph-cli", "--db-url", db_url, "db", "restore"]), \
                    contextlib.redirect_stdout(stdout):
                self.assertEqual(main(), 0)
            engine = create_engine(db_url)
            self.addCleanup(engine.dispose)
            with sessionmaker(bind=engine)() as session:
                session.add_all([
                    EmergencyNotification(state=True),
                    EmergencyNotification(state=False),
                ])
                session.commit()
            stdout = io.StringIO()
            with patch("sys.argv", [
                "ph-cli", "--db-url", db_url, "emergency-notifications", "--state", "1", "--json"
            ]), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(), 0)
            records = json.loads(stdout.getvalue())
            self.assertEqual(len(records), 1)
            self.assertEqual(set(records[0]), {"id", "posted_at", "state"})
            self.assertTrue(records[0]["state"])

    def test_crud_and_district_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            db_url = f"sqlite:///{Path(directory) / 'test.db'}"

            def invoke(*args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["ph-cli", "--db-url", db_url, *args]), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = main()
                return result, stdout.getvalue(), stderr.getvalue()

            self.assertEqual(invoke("db", "restore")[0], 0)
            result, output, _ = invoke(
                "outage-groups", "add", "--external-id", "GPV38.1",
                "--name", "Kyiv", "--description", "Example",
                "--districts", '["Дарницький", "Дарницкого"]',
            )
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output), {
                "id": 1, "external_id": "GPV38.1", "name": "Kyiv",
                "description": "Example", "districts": ["Дарницький", "Дарницкого"],
            })
            _, output, _ = invoke("outage-groups", "add", "--external-id", "GPV2", "--name", "Other")
            self.assertEqual(json.loads(output)["districts"], [])
            result, output, _ = invoke("outage-groups", "update", "1", "--districts", "[]")
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output)["districts"], [])
            for value in ('"district"', '["ok", 1]', 'not-json'):
                with self.subTest(value=value), self.assertRaises(SystemExit) as error:
                    invoke("outage-groups", "update", "1", "--districts", value)
                self.assertEqual(error.exception.code, 2)
            _, output, _ = invoke("outage-groups", "list", "--json")
            self.assertEqual([group["districts"] for group in json.loads(output)], [[], []])
            self.assertEqual(invoke("outage-groups", "remove", "1")[0], 0)
            _, output, _ = invoke("outage-groups", "list", "--json")
            self.assertEqual([group["external_id"] for group in json.loads(output)], ["GPV2"])

    def test_chat_outage_group_assignment_and_clearing(self):
        with tempfile.TemporaryDirectory() as directory:
            db_url = f"sqlite:///{Path(directory) / 'test.db'}"

            def invoke(*args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["ph-cli", "--db-url", db_url, *args]), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = main()
                return result, stdout.getvalue(), stderr.getvalue()

            self.assertEqual(invoke("db", "restore")[0], 0)
            self.assertEqual(invoke("outage-groups", "add", "--external-id", "1", "--name", "First")[0], 0)
            result, output, _ = invoke("chats", "add", "--chat-id", "123", "--outage-group-id", "1")
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output)["outage_group_id"], 1)
            result, output, _ = invoke("chats", "update", "1", "--title", "Updated")
            self.assertEqual(json.loads(output)["outage_group_id"], 1)
            result, _, error = invoke("outage-groups", "remove", "1")
            self.assertEqual(result, 2)
            self.assertIn("assigned to a chat", error)
            result, _, error = invoke("chats", "update", "1", "--outage-group-id", "999")
            self.assertEqual(result, 2)
            self.assertIn("not found", error)
            result, output, _ = invoke("chats", "update", "1", "--outage-group-id", "null")
            self.assertEqual(result, 0)
            self.assertIsNone(json.loads(output)["outage_group_id"])
            engine = create_engine(db_url)
            self.addCleanup(engine.dispose)
            with sessionmaker(bind=engine)() as session:
                session.add(Outage(
                    outage_group_id=1, message_hash="hash", message={"name": "First"}
                ))
                session.commit()
            result, _, error = invoke("outage-groups", "remove", "1")
            self.assertEqual(result, 2)
            self.assertIn("has outage records", error)
            with sessionmaker(bind=engine)() as session:
                session.query(Outage).delete()
                session.commit()
            self.assertEqual(invoke("outage-groups", "remove", "1")[0], 0)
