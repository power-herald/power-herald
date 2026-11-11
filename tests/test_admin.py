import unittest
from unittest.mock import AsyncMock, Mock, patch

with patch("sqlalchemy.create_engine"), patch("aiogram.Bot"):
    from power_herald.admin import _activation_requested_message, generator_cmd
from power_herald.messages import get_message
from power_herald.models import Chat, PowerSource, PowerSourceType, StateChangeType


class ActivationRequestedMessageTests(unittest.TestCase):
    def test_chat_without_source_uses_source_independent_message(self):
        chat = Chat(id=12, title="Community")

        message = _activation_requested_message(chat)

        self.assertEqual(message, "Activation requested for chat [12] Community.")

    def test_chat_with_source_includes_source_details(self):
        source = PowerSource(id=7, name="Generator", type=PowerSourceType.MANUAL)
        chat = Chat(id=12, title="Private", source_id=7, source=source)

        message = _activation_requested_message(chat)

        self.assertEqual(
            message,
            "Activation requested for chat [12] Private for source [7] Generator.",
        )


class GeneratorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def _invoke_generator_command(self, current_state):
        chat = Mock(source_id=7)
        source = Mock()
        source.id = 7
        source.name = "Generator"
        session = Mock()
        chat_query, source_query = Mock(), Mock()
        session.query.side_effect = [chat_query, source_query]
        chat_query.filter_by.return_value.first.return_value = chat
        source_query.filter_by.return_value.first.return_value = source
        message = Mock()
        message.chat.id = 123
        message.chat.type = "private"
        message.answer = AsyncMock()
        keyboard = object()

        with (
            patch("power_herald.admin.Session", return_value=session),
            patch("power_herald.admin.chat_is_enabled", return_value=True),
            patch("power_herald.admin.latest_state", return_value=current_state),
            patch("power_herald.admin.generator_keyboard", return_value=keyboard),
            patch("power_herald.admin._log_command"),
        ):
            await generator_cmd(message)

        return message, session, keyboard

    async def test_displays_current_generator_state(self):
        message, session, keyboard = await self._invoke_generator_command(
            Mock(state=StateChangeType.ONLINE)
        )

        message.answer.assert_awaited_once_with(
            get_message(
                "admin.generator_status",
                source_name="Generator",
                status="online",
            ),
            reply_markup=keyboard,
        )
        session.close.assert_called_once()

    async def test_displays_unknown_when_generator_state_is_not_recorded(self):
        message, _, keyboard = await self._invoke_generator_command(None)

        message.answer.assert_awaited_once_with(
            get_message(
                "admin.generator_status",
                source_name="Generator",
                status="unknown",
            ),
            reply_markup=keyboard,
        )
