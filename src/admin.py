# src/admin.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import Chat, PowerSource, MaintenanceMode, Subscription, Base
import os
from src.config import get_config
from src.messages import get_message

config = get_config()
engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

router = Router()

@router.message(Command("activate"))
async def activate_cmd(message: types.Message):
    session = Session()
    chat_id = str(message.chat.id)
    chat = session.query(Chat).filter_by(chat_id=chat_id).first()
    if not chat:
        chat = Chat(chat_id=chat_id, title=message.chat.title or "", enabled=False)
        session.add(chat)
        session.commit()
    # Notify admin
    for admin_id in config.admin_chat_ids:
        activation_message = get_message("admin.activation_requested", title=chat.title, chat_id=chat_id)
        await message.bot.send_message(admin_id, activation_message)
    response_message = get_message("admin.activation_request_sent")
    await message.answer(response_message)
    session.close()

@router.message(Command("approve"))
async def approve_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        response_message = get_message("admin.not_authorized")
        await message.answer(response_message)
        return
    args = message.text.split()
    if len(args) < 2:
        response_message = get_message("bot.usage.approve")
        await message.answer(response_message)
        return
    chat_id = args[1]
    session = Session()
    chat = session.query(Chat).filter_by(chat_id=chat_id).first()
    if chat:
        chat.enabled = True
        session.commit()
        response_message = get_message("admin.chat_activated", title=chat.title, chat_id=chat_id)
        await message.answer(response_message)
        activation_message = get_message("admin.chat_activated_for_user")
        await message.bot.send_message(chat_id, activation_message)
    else:
        response_message = get_message("admin.chat_not_found")
        await message.answer(response_message)
    session.close()

@router.message(Command("maintenance"))
async def maintenance_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        response_message = get_message("admin.not_authorized")
        await message.answer(response_message)
        return
    # Example: /maintenance <source_id> <on|off> [comment]
    args = message.text.split()
    if len(args) < 3:
        response_message = get_message("bot.usage.maintenance")
        await message.answer(response_message)
        return
    source_id = None if args[1] == "global" else int(args[1])
    enabled = args[2] == "on"
    comment = " ".join(args[3:]) if len(args) > 3 else None
    from src.maintenance import set_maintenance
    set_maintenance(enabled, source_id, comment)
    response_message = get_message(
        "admin.maintenance_status",
        status="enabled" if enabled else "disabled",
        scope="global" if source_id is None else source_id,
    )
    await message.answer(response_message)

@router.message(Command("generator"))
async def generator_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        response_message = get_message("admin.not_authorized")
        await message.answer(response_message)
        return
    # /generator <source_id> <on|off> to enable/disable generator notifications for this chat
    args = message.text.split()
    if len(args) < 3:
        response_message = get_message("bot.usage.generator")
        await message.answer(response_message)
        return
    source_id = int(args[1])
    notify = args[2] == "on"
    session = Session()
    from src.models import PowerSourceType
    source = session.query(PowerSource).filter_by(id=source_id, type=PowerSourceType.GENERATOR).first()
    if not source:
        response_message = get_message("admin.generator_not_found")
        await message.answer(response_message)
        session.close()
        return
    # This would need the chat_id to be available; for now, notify admin
    response_message = get_message(
        "admin.generator_status",
        source_name=source.name,
        status="on" if notify else "off",
    )
    await message.answer(response_message)
    session.close()
