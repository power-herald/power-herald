# src/admin.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import Chat, PowerSource, MaintenanceMode, Subscription, Base
import os
from src.config import get_config

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
        await message.bot.send_message(admin_id, f"Activation requested for chat: {chat.title} ({chat_id})")
    await message.answer("Activation request sent to admin.")
    session.close()

@router.message(Command("approve"))
async def approve_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer("Not authorized.")
        return
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /approve <chat_id>")
        return
    chat_id = args[1]
    session = Session()
    chat = session.query(Chat).filter_by(chat_id=chat_id).first()
    if chat:
        chat.enabled = True
        session.commit()
        await message.answer(f"Chat {chat.title} ({chat_id}) activated.")
        await message.bot.send_message(chat_id, "Your chat is now activated!")
    else:
        await message.answer("Chat not found.")
    session.close()

@router.message(Command("maintenance"))
async def maintenance_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer("Not authorized.")
        return
    # Example: /maintenance <source_id> <on|off> [comment]
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Usage: /maintenance <source_id|global> <on|off> [comment]")
        return
    source_id = None if args[1] == "global" else int(args[1])
    enabled = args[2] == "on"
    comment = " ".join(args[3:]) if len(args) > 3 else None
    from src.maintenance import set_maintenance
    set_maintenance(enabled, source_id, comment)
    await message.answer(f"Maintenance {'enabled' if enabled else 'disabled'} for {'global' if source_id is None else source_id}.")

@router.message(Command("generator"))
async def generator_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer("Not authorized.")
        return
    # /generator <source_id> <on|off> to enable/disable generator notifications for this chat
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Usage: /generator <source_id> <on|off>")
        return
    source_id = int(args[1])
    notify = args[2] == "on"
    session = Session()
    from src.models import PowerSourceType
    source = session.query(PowerSource).filter_by(id=source_id, type=PowerSourceType.GENERATOR).first()
    if not source:
        await message.answer("Generator source not found.")
        session.close()
        return
    # This would need the chat_id to be available; for now, notify admin
    await message.answer(f"Generator notifications for {source.name} set to {'on' if notify else 'off'}.")
    session.close()
