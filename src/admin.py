# src/admin.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import Chat, PowerSource, MaintenanceMode, Subscription, PowerSourceType, StateChangeType
from src.config import get_config
from src.messages import bot_greeting, get_message
from src.generator import set_generator_state

config = get_config()
engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

router = Router()


def chat_is_enabled(chat_id: int) -> bool:
    session = Session()
    try:
        return session.query(Chat).filter_by(chat_id=str(chat_id), enabled=True).first() is not None
    finally:
        session.close()


def chat_is_admin(chat_id: int) -> bool:
    return str(chat_id) in config.admin_chat_ids

def generator_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=get_message("generator.start_button"))],
            [KeyboardButton(text=get_message("generator.stop_button"))],
        ],
        resize_keyboard=True,
    )

@router.message(Command("activate"))
async def activate_cmd(message: types.Message):
    if chat_is_enabled(message.chat.id) and message.chat.type == "private":
        await message.answer(
            get_message("admin.error.chat_already_activated"),
            reply_markup=generator_keyboard(),
        )
        return
    if chat_is_enabled(message.chat.id) and message.chat.type != "private":
        await message.answer(get_message("admin.error.chat_already_activated"))
        return
    session = Session()
    chat_id = str(message.chat.id)
    chat = session.query(Chat).filter_by(chat_id=chat_id).first()
    if not chat:
        chat = Chat(
            chat_id=chat_id,
            title=message.chat.title or "",
            thread_id=message.message_thread_id,
            is_private=message.chat.type == "private",
            enabled=False,
        )
        session.add(chat)
    else:
        chat.title = message.chat.title or ""
        chat.thread_id = message.message_thread_id
        chat.is_private = message.chat.type == "private"
    session.commit()
    # Notify admin
    for admin_id in config.admin_chat_ids:
        activation_message = get_message("admin.activation_requested", title=chat.title, chat_id=chat.id)
        await message.bot.send_message(admin_id, activation_message)
    response_message = get_message("admin.activation_request_sent")
    await message.answer(response_message)
    session.close()

@router.message(Command("approve"))
async def approve_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        response_message = get_message("admin.error.not_authorized")
        await message.answer(response_message)
        return
    args = message.text.split()
    if len(args) < 2:
        response_message = get_message("bot.usage.approve")
        await message.answer(response_message)
        return
    chat_id = args[1]
    session = Session()
    chat = session.query(Chat).filter_by(id=chat_id).first()
    if chat:
        chat.enabled = True
        session.commit()
        response_message = get_message("admin.chat_activated", title=chat.title, chat_id=chat.id)
        await message.answer(response_message)
        activation_message = get_message("admin.chat_activated_for_user")
        await message.bot.send_message(
            chat.chat_id,
            activation_message,
            message_thread_id=chat.thread_id,
            reply_markup=generator_keyboard() if chat.is_private else None,
        )
    else:
        response_message = get_message("admin.error.chat_not_found")
        await message.answer(response_message)
    session.close()


@router.message(Command("subscribe"))
async def subscribe_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer(get_message("admin.error.not_authorized"))
        return
    args = message.text.split()
    if len(args) < 3:
        await message.answer(get_message("bot.usage.subscribe"))
        return

    chat_id, source_id_text = args[1:3]
    try:
        source_id = int(source_id_text)
    except ValueError:
        await message.answer(get_message("admin.error.source_not_found"))
        return

    session = Session()
    chat = session.query(Chat).filter_by(id=chat_id).first()
    source = session.query(PowerSource).filter_by(id=source_id, enabled=True).first()
    if not chat:
        await message.answer(get_message("admin.error.chat_not_found"))
    elif not source:
        await message.answer(get_message("admin.error.source_not_found"))
    else:
        subscription = session.query(Subscription).filter_by(
            chat_id=chat.id, source_id=source.id
        ).first()
        if subscription:
            subscription.enabled = True
        else:
            session.add(Subscription(chat_id=chat.id, source_id=source.id))
        session.commit()
        await message.answer(
            get_message("admin.subscription_added", chat_id=chat.id, title=chat.title, source_id=source.id, source_name=source.name)
        )
    session.close()


@router.message(Command("sources"))
async def sources_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer(get_message("admin.error.not_authorized"))
        return
    session = Session()
    sources = session.query(PowerSource).order_by(PowerSource.id).all()
    session.close()
    if not sources:
        await message.answer(get_message("admin.error.no_sources"))
        return
    lines = [
        get_message(
            "admin.source_list_item",
            source_id=source.id,
            source_name=source.name,
            source_type=source.type.value,
            status="enabled" if source.enabled else "disabled",
        )
        for source in sources
    ]
    await message.answer("\n".join(lines))


@router.message(Command("chats"))
async def chats_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        await message.answer(get_message("admin.error.not_authorized"))
        return
    session = Session()
    chats = session.query(Chat).order_by(Chat.id).all()
    session.close()
    if not chats:
        await message.answer(get_message("admin.error.no_chats"))
        return
    lines = [
        get_message(
            "admin.chat_list_item",
            chat_id=chat.id,
            title=chat.title or "",
            status="enabled" if chat.enabled else "disabled",
        )
        for chat in chats
    ]
    await message.answer("\n".join(lines))

@router.message(Command("maintenance"))
async def maintenance_cmd(message: types.Message):
    if str(message.chat.id) not in config.admin_chat_ids:
        response_message = get_message("admin.error.not_authorized")
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
async def activate_cmd(message: types.Message):
    if not chat_is_enabled(message.chat.id):
        await message.answer(get_message("admin.error.not_authorized"))
        return
    if message.chat.type != "private":
        await message.answer(get_message("admin.error.generator_private_only"))
        return
    session = Session()
    source = session.query(PowerSource).filter_by(
        type=PowerSourceType.GENERATOR, enabled=True
    ).first()
    session.close()
    if not source:
        await message.answer(get_message("admin.error.generator_not_found"))
        return
    await message.answer(
        get_message("generator.status", source_name=source.name),
        reply_markup=generator_keyboard(),
    )


async def _generator_state_cmd(message: types.Message, state: StateChangeType):
    session = Session()
    chat = session.query(Chat).filter_by(chat_id=str(message.chat.id), enabled=True).first()
    source = session.query(PowerSource).filter_by(
        type=PowerSourceType.GENERATOR, enabled=True
    ).first()
    session.close()
    if (not chat or not source) and not chat_is_admin(message.chat.id):
        response_message = get_message("admin.error.not_authorized") if not chat else get_message("admin.error.generator_not_found")
        await message.answer(response_message)
        return
    changed = await set_generator_state(source.id, state)
    status_key = "generator.started" if state == StateChangeType.ONLINE else "generator.stopped"
    status = get_message(status_key, source_name=source.name) if changed else get_message("generator.already_in_state", state=state.value)
    await message.answer(status, reply_markup=generator_keyboard())


@router.message(F.text == get_message("generator.start_button"))
async def start_generator_cmd(message: types.Message):
    await _generator_state_cmd(message, StateChangeType.ONLINE)


@router.message(F.text == get_message("generator.stop_button"))
async def stop_generator_cmd(message: types.Message):
    await _generator_state_cmd(message, StateChangeType.OFFLINE)
