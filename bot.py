# ==========================================
# Telegram Bot Template
# aiogram 3.15+
# SQLite + Groq AI
# ==========================================

import asyncio
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from groq import AsyncGroq


# =========================================================
# НАСТРОЙКИ
# =========================================================

# =========================================================
# ВСТАВЬ СВОИ ДАННЫЕ СЮДА ДЛЯ ТЕСТА
# =========================================================
BOT_TOKEN = os.getenv("API_TOKEN")
GROQ_API_KEY = "gsk_2OI8TXfFBgUZP7AkmFf2WGdyb3FYHCXN6
ADMIN_ID = int("881455985")

if not ADMIN_ID:
    raise ValueError("ADMIN_ID не задан.")

# Внутренний набор используется только для общих проверок и очистки чата.
ADMIN_IDS = {ADMIN_ID}

def is_admin(user_id):
    return user_id == ADMIN_ID


AI_PROMPT = "Ты - вежливый AI-помощник Максима Зверева, мастера спорта международного класса.\n\nТвоя основная задача - помогать людям записываться на тренировки и другие услуги, отвечать на вопросы и рассказывать об актуальных товарах и акциях.\n\nТы имеешь доступ к списку товаров и акций. Используй только информацию, которая есть в этих списках. Не придумывай цены, услуги, условия, расписание или другие факты.\n\nНе выдавай себя за Максима Зверева и не говори от его имени. Если тебя спрашивают, кто ты, честно отвечай, что ты AI-помощник.\n\nОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:\n1. УСЛУГА\n2. ВРЕМЯ\n3. ИМЯ ЧЕЛОВЕКА\n4. ДОП. КОММЕНТАРИЙ\n\nТвоя задача - постепенно узнать все обязательные требования и после этого предложить человеку подтвердить запись.\n\nНе задавай все вопросы сразу. Веди обычный живой диалог и задавай по одному вопросу, учитывая ответы человека.\n\nЕсли человек сам уже сообщил какую-либо информацию, не спрашивай её повторно.\n\nЕсли человек задаёт дополнительные вопросы, сначала нормально ответь на них, а затем продолжи диалог по записи.\n\nОтвечай максимально коротко, естественно и по делу. Пиши как настоящий вежливый помощник, а не как робот или официальный оператор.\n\nНе используй эмодзи, звёздочки, Markdown, списки с декоративными символами, хэштеги и другие лишние символы. Обычный текст и обычная пунктуация.\n\nНе сообщай пользователю о внутренних ограничениях, количестве сообщений, паузах между блоками или технической работе AI.\n\nНе говори пользователю, что тебе нужно собрать обязательные требования. Просто естественно получай необходимую информацию в процессе разговора.\n\nКогда все обязательные требования получены, больше не задавай лишних вопросов и предложи подтвердить запись."

PHOTO_MAIN = "AgACAgIAAxkBAANXar4r9EOBPT4rzLl9OrVUVW15nykAAlceaxtVi_BJLqPjGMRL1BIBAAMCAAN4AAM9BA"
WELCOME_TEXT = "Здравствуйте! Я - помощник Максима Зверева. Помогу вам найти информацию и записаться на тренировку."

PHOTO_INFO = "AgACAgIAAxkBAANSar4rStWE7PI0yeaECOVw21-FNqIAAlEeaxtVi_BJ3jJJp0j-qQsBAAMCAAN4AAM9BA"
INFO_TEXT = "Максим Зверев - профессиональный игрок в русский бильярд, мастер спорта международного класса и основатель Академии бильярда Максима Зверева.\n\nМаксим занимается бильярдом много лет и сам прошёл путь от спортсмена до тренера. За его карьеру было много серьёзных соревнований и побед, в том числе два Кубка мира и восемь чемпионств России среди мужчин.\n\nВ Академии занимаются дети и взрослые, как начинающие, так и уже опытные игроки. На тренировках разбирают технику, постановку удара, стойку, точность, тактику и игровые ситуации.\n\nГлавная задача академии - не просто научить правильно бить по шарам, а помочь человеку действительно понимать игру и постепенно повышать свой уровень.\n\nЗаписаться на тренировку или узнать подробности можно через кнопку «Записаться»."

DATA_FOLDER = "/app/data"
if not os.path.isdir(DATA_FOLDER):
    DATA_FOLDER = "."

DB_PATH = os.path.join(DATA_FOLDER, "bot.db")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан.")

# Лимиты AI:
AI_BLOCK_SIZE = 15
AI_WAIT_MINUTES = 10
AI_MAX_BLOCKS = 3


# =========================================================
# BOT
# =========================================================

class CleanChatBot(Bot):
    """
    Держит пользовательский чат чистым: перед отправкой нового
    сообщения удаляет последнее сообщение бота в этом чате.

    Админский чат не трогаем, чтобы не удалять историю заявок
    и служебные сообщения администратора.
    """

    _last_bot_messages = {}

    async def _delete_previous(self, chat_id):
        if chat_id in ADMIN_IDS:
            return

        previous_id = self._last_bot_messages.get(chat_id)
        if not previous_id:
            return

        try:
            await super().delete_message(chat_id=chat_id, message_id=previous_id)
        except Exception:
            pass

        self._last_bot_messages.pop(chat_id, None)

    def _remember(self, chat_id, message_id):
        if chat_id not in ADMIN_IDS:
            self._last_bot_messages[chat_id] = message_id

    async def send_message(self, chat_id, text, **kwargs):
        await self._delete_previous(chat_id)
        result = await super().send_message(chat_id=chat_id, text=text, **kwargs)
        self._remember(chat_id, result.message_id)
        return result

    async def send_photo(self, chat_id, photo, **kwargs):
        await self._delete_previous(chat_id)
        result = await super().send_photo(chat_id=chat_id, photo=photo, **kwargs)
        self._remember(chat_id, result.message_id)
        return result


bot = CleanChatBot(token=BOT_TOKEN)
dp = Dispatcher()

async def safe_edit_text(message, text, reply_markup=None):
    """Редактирует текстовое сообщение. Если callback пришёл от фото,
    Telegram не позволяет edit_text - тогда заменяем сообщение новым.
    """
    try:
        return await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if "there is no text in the message to edit" not in str(error).lower():
            raise
        try:
            await message.delete()
        except Exception:
            pass
        return await message.answer(text, reply_markup=reply_markup)

groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


# =========================================================
# FSM
# =========================================================

class BookingState(StatesGroup):
    waiting_ai = State()


class ProductAddState(StatesGroup):
    text = State()
    photo = State()


class ProductEditState(StatesGroup):
    text = State()
    photo = State()


class PromotionAddState(StatesGroup):
    text = State()
    photo = State()


class PromotionEditState(StatesGroup):
    text = State()
    photo = State()


class FileIdState(StatesGroup):
    photo = State()


class BroadcastState(StatesGroup):
    message = State()
    add_button = State()
    button_text = State()
    button_url = State()
    button_style = State()


# =========================================================
# DATABASE
# =========================================================

def db():
    os.makedirs(DATA_FOLDER, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def column_names(connection, table_name: str):
    rows = connection.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return {row[1] for row in rows}


def ensure_column(connection, table_name: str, column_name: str, definition: str):
    if column_name not in column_names(connection, table_name):
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def _normalize_products_table(connection):
    """Приводит products к актуальной схеме даже если база создана старой версией бота."""
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
    ).fetchone()
    if not tables:
        connection.execute("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                photo_file_id TEXT NOT NULL DEFAULT ''
            )
        """)
        return

    columns = column_names(connection, "products")
    legacy = {"name", "price", "description"} & columns

    if not legacy:
        ensure_column(connection, "products", "text", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "products", "photo_file_id", "TEXT NOT NULL DEFAULT ''")
        return

    # Старые версии имели обязательный products.name.
    # Простого ALTER TABLE недостаточно: SQLite продолжит требовать name.
    # Поэтому создаём чистую таблицу и переносим данные.
    rows = connection.execute("SELECT * FROM products ORDER BY id").fetchall()
    old_columns = [row[1] for row in connection.execute("PRAGMA table_info(products)").fetchall()]
    index = {name: i for i, name in enumerate(old_columns)}

    def value(row, name, default=""):
        i = index.get(name)
        return row[i] if i is not None and row[i] is not None else default

    connection.execute("DROP TABLE IF EXISTS products_new")
    connection.execute("""
        CREATE TABLE products_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            photo_file_id TEXT NOT NULL DEFAULT ''
        )
    """)

    for row in rows:
        text_value = value(row, "text", "").strip()
        if not text_value:
            parts = []
            name = value(row, "name", "").strip()
            price = value(row, "price", "").strip()
            description = value(row, "description", "").strip()
            if name:
                parts.append(name)
            if price:
                parts.append(f"Цена: {price}")
            if description:
                parts.append(description)
            text_value = "\n".join(parts) or "Без названия"

        photo = value(row, "photo_file_id", "")
        if not photo:
            photo = value(row, "photo", "")

        connection.execute(
            "INSERT INTO products_new (id, text, photo_file_id) VALUES (?, ?, ?)",
            (value(row, "id", None), text_value, photo),
        )

    connection.execute("DROP TABLE products")
    connection.execute("ALTER TABLE products_new RENAME TO products")


def _normalize_promotions_table(connection):
    """Приводит promotions к актуальной схеме без потери старых записей."""
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='promotions'"
    ).fetchone()
    if not tables:
        connection.execute("""
            CREATE TABLE promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                photo_file_id TEXT NOT NULL DEFAULT ''
            )
        """)
        return

    columns = column_names(connection, "promotions")
    legacy = {"name", "description"} & columns

    if not legacy:
        ensure_column(connection, "promotions", "text", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "promotions", "photo_file_id", "TEXT NOT NULL DEFAULT ''")
        return

    rows = connection.execute("SELECT * FROM promotions ORDER BY id").fetchall()
    old_columns = [row[1] for row in connection.execute("PRAGMA table_info(promotions)").fetchall()]
    index = {name: i for i, name in enumerate(old_columns)}

    def value(row, name, default=""):
        i = index.get(name)
        return row[i] if i is not None and row[i] is not None else default

    connection.execute("DROP TABLE IF EXISTS promotions_new")
    connection.execute("""
        CREATE TABLE promotions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            photo_file_id TEXT NOT NULL DEFAULT ''
        )
    """)

    for row in rows:
        text_value = value(row, "text", "").strip()
        if not text_value:
            parts = []
            name = value(row, "name", "").strip()
            description = value(row, "description", "").strip()
            if name:
                parts.append(name)
            if description:
                parts.append(description)
            text_value = "\n".join(parts) or "Без названия"

        photo = value(row, "photo_file_id", "")
        if not photo:
            photo = value(row, "photo", "")

        connection.execute(
            "INSERT INTO promotions_new (id, text, photo_file_id) VALUES (?, ?, ?)",
            (value(row, "id", None), text_value, photo),
        )

    connection.execute("DROP TABLE promotions")
    connection.execute("ALTER TABLE promotions_new RENAME TO promotions")


def init_db():
    connection = db()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)
        ensure_column(connection, "users", "username", "TEXT")
        ensure_column(connection, "users", "first_name", "TEXT")
        ensure_column(connection, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")

        _normalize_products_table(connection)
        _normalize_promotions_table(connection)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                user_id INTEGER PRIMARY KEY,
                messages_json TEXT NOT NULL DEFAULT '[]',
                ai_answers INTEGER NOT NULL DEFAULT 0,
                block_number INTEGER NOT NULL DEFAULT 1,
                available_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        ensure_column(connection, "conversations", "messages_json", "TEXT NOT NULL DEFAULT '[]'")
        ensure_column(connection, "conversations", "ai_answers", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "conversations", "block_number", "INTEGER NOT NULL DEFAULT 1")
        ensure_column(connection, "conversations", "available_at", "TEXT")
        ensure_column(connection, "conversations", "updated_at", "TEXT NOT NULL DEFAULT ''")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_id INTEGER,
                buttons_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)
        ensure_column(connection, "broadcasts", "text", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "broadcasts", "photo_file_id", "TEXT NOT NULL DEFAULT ''")

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# =========================================================
# USERS
# =========================================================

def save_user(message: Message):
    connection = db()
    connection.execute("""
        INSERT INTO users (id, username, first_name, is_active)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            is_active = 1
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    ))
    connection.commit()
    connection.close()


def deactivate_user(user_id: int):
    connection = db()
    connection.execute(
        "UPDATE users SET is_active = 0 WHERE id = ?",
        (user_id,)
    )
    connection.commit()
    connection.close()


def get_all_user_ids():
    connection = db()
    rows = connection.execute(
        "SELECT id FROM users WHERE is_active = 1"
    ).fetchall()
    connection.close()
    return [row[0] for row in rows]


# =========================================================
# PRODUCTS
# =========================================================

def add_product(text: str, photo_file_id: str):
    connection = db()
    connection.execute(
        "INSERT INTO products (text, photo_file_id) VALUES (?, ?)",
        (text, photo_file_id)
    )
    connection.commit()
    connection.close()


def get_products():
    connection = db()
    rows = connection.execute(
        "SELECT id, text, photo_file_id FROM products ORDER BY id DESC"
    ).fetchall()
    connection.close()
    return rows


def get_product(product_id: int):
    connection = db()
    row = connection.execute(
        "SELECT id, text, photo_file_id FROM products WHERE id = ?",
        (product_id,)
    ).fetchone()
    connection.close()
    return row


def update_product(product_id: int, text: str, photo_file_id: str):
    connection = db()
    connection.execute("""
        UPDATE products
        SET text = ?, photo_file_id = ?
        WHERE id = ?
    """, (text, photo_file_id, product_id))
    connection.commit()
    connection.close()


def delete_product(product_id: int):
    connection = db()
    connection.execute(
        "DELETE FROM products WHERE id = ?",
        (product_id,)
    )
    connection.commit()
    connection.close()


# =========================================================
# PROMOTIONS
# =========================================================

def add_promotion(text: str, photo_file_id: str):
    connection = db()
    connection.execute(
        "INSERT INTO promotions (text, photo_file_id) VALUES (?, ?)",
        (text, photo_file_id)
    )
    connection.commit()
    connection.close()


def get_promotions():
    connection = db()
    rows = connection.execute(
        "SELECT id, text, photo_file_id FROM promotions ORDER BY id DESC"
    ).fetchall()
    connection.close()
    return rows


def get_promotion(promotion_id: int):
    connection = db()
    row = connection.execute(
        "SELECT id, text, photo_file_id FROM promotions WHERE id = ?",
        (promotion_id,)
    ).fetchone()
    connection.close()
    return row


def update_promotion(promotion_id: int, text: str, photo_file_id: str):
    connection = db()
    connection.execute("""
        UPDATE promotions
        SET text = ?, photo_file_id = ?
        WHERE id = ?
    """, (text, photo_file_id, promotion_id))
    connection.commit()
    connection.close()


def delete_promotion(promotion_id: int):
    connection = db()
    connection.execute(
        "DELETE FROM promotions WHERE id = ?",
        (promotion_id,)
    )
    connection.commit()
    connection.close()


# =========================================================
# CONVERSATIONS
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def get_conversation(user_id: int):
    connection = db()
    row = connection.execute("""
        SELECT messages_json, ai_answers, block_number, available_at
        FROM conversations
        WHERE user_id = ?
    """, (user_id,)).fetchone()
    connection.close()

    if not row:
        return {
            "messages": [],
            "ai_answers": 0,
            "block_number": 1,
            "available_at": None,
        }

    try:
        messages = json.loads(row[0])
    except Exception:
        messages = []

    return {
        "messages": messages,
        "ai_answers": int(row[1] or 0),
        "block_number": int(row[2] or 1),
        "available_at": row[3],
    }


def save_conversation(
    user_id: int,
    messages: list,
    ai_answers: int,
    block_number: int,
    available_at: Optional[str],
):
    connection = db()
    connection.execute("""
        INSERT INTO conversations
            (user_id, messages_json, ai_answers, block_number, available_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            messages_json = excluded.messages_json,
            ai_answers = excluded.ai_answers,
            block_number = excluded.block_number,
            available_at = excluded.available_at,
            updated_at = excluded.updated_at
    """, (
        user_id,
        json.dumps(messages, ensure_ascii=False),
        ai_answers,
        block_number,
        available_at,
        iso_now(),
    ))
    connection.commit()
    connection.close()


def clear_conversation(user_id: int):
    connection = db()
    connection.execute(
        "DELETE FROM conversations WHERE user_id = ?",
        (user_id,)
    )
    connection.commit()
    connection.close()


# =========================================================
# SAFE PHOTO SENDING
# =========================================================

async def safe_answer_photo(
    message: Message,
    photo_id: str,
    caption: str,
    reply_markup=None,
):
    photo_id = (photo_id or "").strip()

    if photo_id:
        try:
            return await message.answer_photo(
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        except TelegramBadRequest as error:
            logging.warning(
                "Не удалось отправить фото. FILE_ID=%r ERROR=%s",
                photo_id,
                error,
            )
        except Exception as error:
            logging.exception(
                "Неожиданная ошибка отправки фото: %s",
                error,
            )

    return await message.answer(
        caption,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def safe_edit_or_send_photo(
    callback: CallbackQuery,
    photo_id: str,
    caption: str,
    reply_markup=None,
):
    photo_id = (photo_id or "").strip()

    if photo_id:
        try:
            new_message = await callback.message.answer_photo(
                photo=photo_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )

            try:
                await callback.message.delete()
            except Exception:
                pass

            return new_message

        except TelegramBadRequest as error:
            logging.warning(
                "Неверный FILE_ID. Использую текстовый вариант. %s",
                error,
            )
        except Exception as error:
            logging.exception(
                "Ошибка фото. Использую текстовый вариант: %s",
                error,
            )

    try:
        await safe_edit_text(callback.message, 
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return callback.message
    except Exception:
        return await callback.message.answer(
            caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


# =========================================================
# KEYBOARDS
# Все кнопки по одной в строке.
# Смайлики в кнопках не используются.
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Записаться",
            callback_data="booking",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Информация",
            callback_data="info",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Услуги",
            callback_data="products",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Акции",
            callback_data="promotions",
            style="primary"
        )],
    ])


def back_keyboard(callback_data="back"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data=callback_data,
            style="danger"
        )]
    ])


def role_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Покупатель",
            callback_data="role_buyer",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Продавец",
            callback_data="role_seller",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back",
            style="danger"
        )],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Товары",
            callback_data="admin_products",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Акции",
            callback_data="admin_promotions",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Рассылка",
            callback_data="admin_broadcast",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Получить file_id фото",
            callback_data="file_id_tool",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="admin_back",
            style="danger"
        )],
    ])


def product_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Добавить товар",
            callback_data="product_add",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Список товаров",
            callback_data="product_list",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="admin",
            style="danger"
        )],
    ])


def promotion_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Добавить акцию",
            callback_data="promotion_add",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Список акций",
            callback_data="promotion_list",
            style="primary"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="admin",
            style="danger"
        )],
    ])


def cancel_keyboard(callback_data):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Отмена",
            callback_data=callback_data,
            style="danger"
        )]
    ])


def confirm_delete_keyboard(kind: str, item_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Да",
            callback_data=f"confirm_delete_{kind}:{item_id}",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Нет",
            callback_data=f"{kind}_list",
            style="danger"
        )],
    ])


def booking_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Подтвердить запись",
            callback_data="booking_confirm",
            style="success"
        )],
        [InlineKeyboardButton(
            text="Отменить",
            callback_data="booking_cancel",
            style="danger"
        )],
    ])


# =========================================================
# AI
# =========================================================

def get_ai_products_context() -> str:
    """Возвращает актуальный список товаров из SQLite для контекста AI."""
    rows = get_products()

    if not rows:
        return (
            "АКТУАЛЬНЫЙ СПИСОК ТОВАРОВ:\n"
            "Товаров пока нет. Не придумывай товары, цены, характеристики "
            "или наличие, которых нет в этом списке."
        )

    parts = [
        "АКТУАЛЬНЫЙ СПИСОК ТОВАРОВ ИЗ БАЗЫ БОТА:",
        "Используй этот список, когда пользователь спрашивает о товарах. "
        "Отвечай только по данным из него и не придумывай отсутствующие "
        "цены, характеристики, наличие или условия.",
    ]

    for number, (product_id, text, _photo_file_id) in enumerate(rows, start=1):
        parts.append(f"\nТовар {number} (ID {product_id}):\n{text.strip()}")

    return "\n".join(parts)


def get_ai_promotions_context() -> str:
    """Возвращает актуальный список акций из SQLite для контекста AI."""
    rows = get_promotions()

    if not rows:
        return (
            "АКТУАЛЬНЫЙ СПИСОК АКЦИЙ:\n"
            "Акций пока нет. Не придумывай акции, скидки, сроки или условия, "
            "которых нет в этом списке."
        )

    parts = [
        "АКТУАЛЬНЫЙ СПИСОК АКЦИЙ ИЗ БАЗЫ БОТА:",
        "Используй этот список, когда пользователь спрашивает об акциях, "
        "скидках или специальных условиях. Не придумывай отсутствующие "
        "сроки, скидки или условия.",
    ]

    for number, (promotion_id, text, _photo_file_id) in enumerate(rows, start=1):
        parts.append(f"\nАкция {number} (ID {promotion_id}):\n{text.strip()}")

    return "\n".join(parts)


def get_ai_catalog_context() -> str:
    return get_ai_products_context() + "\n\n" + get_ai_promotions_context()


def clean_plain_text(text: str) -> str:
    """Убирает Markdown и декоративные маркеры из AI-ответов."""
    if not text:
        return ""
    text = text.replace("**", "").replace("__", "")
    text = text.replace("###", "").replace("##", "").replace("#", "")
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^(?:[-*•]+)\s*", "", line)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def get_booking_rules_context() -> str:
    return """
ПРАВИЛА ЗАВЕРШЕНИЯ ЗАПИСИ:

1. В основном AI_PROMPT может быть раздел «Обязательные параметры».
2. Если такой раздел есть, используй именно перечисленные там параметры как обязательные.
3. Нужно определить по ВСЕМУ диалогу, какие параметры пользователь уже сообщил.
4. Не считай параметр известным, если пользователь дал слишком расплывчатый ответ. При необходимости задай уточняющий вопрос.
5. Если в AI_PROMPT нет раздела «Обязательные параметры», используй стандартный список:
   - Услуга
   - Время
   - Имя человека
   - Дополнительный комментарий
6. Пока хотя бы одного обязательного параметра не хватает, НЕ завершай запись.
7. Когда все обязательные параметры известны и уточнений больше не нужно, дай короткий нормальный ответ пользователю и в самом конце добавь служебную метку [[BOOKING_READY]].
8. Метку [[BOOKING_READY]] пользователь видеть не должен. Не объясняй её и не выводи её отдельно.
"""


async def ask_ai(messages: list) -> Optional[str]:
    if not groq_client:
        return None

    try:
        catalog_context = get_ai_catalog_context()
        booking_rules = get_booking_rules_context()
        system_content = f"{AI_PROMPT}\n\n{booking_rules}\n\n{catalog_context}"

        response = await groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": system_content,
                },
                *messages,
            ],
            temperature=0.7,
            max_tokens=700,
        )

        answer = response.choices[0].message.content
        return answer.strip() if answer else None

    except Exception as error:
        logging.exception("AI error: %s", error)
        return None


# =========================================================
# BOOKING / AI AGENT
# =========================================================


async def process_ai_message(
    message: Message,
):
    user_id = message.from_user.id
    conversation = get_conversation(user_id)

    # Проверяем временную блокировку.
    available_at = conversation.get("available_at")

    if available_at:
        try:
            available_time = datetime.fromisoformat(available_at)

            if now_utc() < available_time:
                remaining = available_time - now_utc()
                minutes = max(1, int(remaining.total_seconds() // 60) + 1)

                await message.answer(
                    f"Следующий блок ответов будет доступен примерно через {minutes} мин."
                )
                return

            # Окно ожидания закончилось.
            conversation["available_at"] = None
            conversation["ai_answers"] = 0
            conversation["block_number"] += 1

        except Exception:
            conversation["available_at"] = None

    # После третьего блока новые ответы AI не выдаём.
    if conversation["block_number"] > AI_MAX_BLOCKS:
        await message.answer(
            "Вы точно готовы записаться?",
            reply_markup=booking_confirm_keyboard(),
        )
        return

    text = (message.text or message.caption or "").strip()

    if not text:
        await message.answer("Пожалуйста, отправьте сообщение текстом.")
        return

    conversation["messages"].append({
        "role": "user",
        "content": text,
    })

    answer = await ask_ai(conversation["messages"])

    if not answer:
        # Не считаем неуспешный запрос за ответ AI.
        conversation["messages"].pop()
        await message.answer(
            "Сейчас не удалось получить ответ AI. Попробуйте ещё раз."
        )
        return

    booking_ready = "[[BOOKING_READY]]" in answer
    answer = answer.replace("[[BOOKING_READY]]", "").strip()
    answer = clean_plain_text(answer)

    conversation["messages"].append({
        "role": "assistant",
        "content": answer,
    })

    conversation["ai_answers"] += 1

    # Если AI определил по обязательным параметрам, что запись полностью подготовлена,
    # сразу переводим пользователя на подтверждение - без ожидания лимита.
    if booking_ready:
        save_conversation(
            user_id,
            conversation["messages"],
            conversation["ai_answers"],
            conversation["block_number"],
            conversation["available_at"],
        )

        if answer:
            await message.answer(
                answer,
                    )

        await message.answer(
            "Подтвердить запись?",
            reply_markup=booking_confirm_keyboard(),
        )
        return

    # После последнего допустимого ответа блока ставим 10 минут.
    if conversation["ai_answers"] >= AI_BLOCK_SIZE:
        if conversation["block_number"] >= AI_MAX_BLOCKS:
            save_conversation(
                user_id,
                conversation["messages"],
                conversation["ai_answers"],
                conversation["block_number"],
                None,
            )
            await message.answer(
                answer,
                    )
            await message.answer(
                "Вы точно готовы записаться?",
                reply_markup=booking_confirm_keyboard(),
            )
            return

        available_time = now_utc() + timedelta(minutes=AI_WAIT_MINUTES)
        conversation["available_at"] = available_time.isoformat()

        save_conversation(
            user_id,
            conversation["messages"],
            conversation["ai_answers"],
            conversation["block_number"],
            conversation["available_at"],
        )

        await message.answer(
            answer,
            )
        await message.answer(
            f"Лимит в {AI_BLOCK_SIZE} ответов достигнут. "
            f"Следующий блок будет доступен через {AI_WAIT_MINUTES} минут."
        )
        return

    save_conversation(
        user_id,
        conversation["messages"],
        conversation["ai_answers"],
        conversation["block_number"],
        conversation["available_at"],
    )

    await message.answer(
        answer,
    )


@dp.callback_query(F.data == "booking")
async def booking_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.clear()

    # Начинаем новый диалог записи.
    clear_conversation(callback.from_user.id)
    save_conversation(
        callback.from_user.id,
        [],
        0,
        1,
        None,
    )
    await state.set_state(BookingState.waiting_ai)

    await callback.message.answer(
        "Здравствуйте! Я менеджер. Помогу вам с записью.\n\n"
        "Расскажите, на какую услугу хотите записаться.",
    )

    await callback.answer()


@dp.callback_query(F.data == "booking_confirm")
async def booking_confirm(
    callback: CallbackQuery,
    state: FSMContext,
):
    user_id = callback.from_user.id
    conversation = get_conversation(user_id)

    if not conversation["messages"]:
        await callback.answer(
            "Диалог не найден.",
            show_alert=True,
        )
        return

    messages = conversation["messages"]

    username = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else "без username"
    )

    summary_prompt = """
Проанализируй весь диалог пользователя с AI-помощником.
Сделай короткую понятную запись для администратора.
Не придумывай факты, которых не было в диалоге.

Укажи только то, что относится к записи:
- услуга;
- время;
- имя человека;
- дополнительный комментарий;
- важные детали и пожелания;
- краткое резюме разговора.

Не используй Markdown, звёздочки, двойные звёздочки, подчёркивания, маркеры списков или декоративные символы.
Пиши обычным текстом, коротко и понятно.
Если какого-то поля в диалоге нет, напиши «не указано».
"""

    summary = await ask_ai([
        *messages,
        {
            "role": "user",
            "content": summary_prompt,
        },
    ])

    if not summary:
        summary = "\n".join(
            f"{item['role']}: {item['content']}"
            for item in messages
        )

    summary = clean_plain_text(summary)

    admin_text = (
        "Новая заявка на запись\n\n"
        f"Имя: {escape(callback.from_user.full_name)}\n"
        f"Username: {escape(username)}\n"
        f"Telegram ID: <code>{user_id}</code>\n\n"
        f"Резюме:\n{escape(summary)}"
    )

    failed_admins = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_text,
            )
        except Exception as error:
            failed_admins += 1
            logging.exception("Не удалось отправить заявку админу %s: %s", admin_id, error)

    if failed_admins == len(ADMIN_IDS):
        await callback.answer(
            "Не удалось отправить заявку. Попробуйте ещё раз.",
            show_alert=True,
        )
        return

    # После подтверждения история полностью удаляется.
    clear_conversation(user_id)
    await state.clear()

    await callback.message.answer(
        "Спасибо! Ваша заявка отправлена. "
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "booking_cancel")
async def booking_cancel(
    callback: CallbackQuery,
    state: FSMContext,
):
    clear_conversation(callback.from_user.id)
    await state.clear()

    await callback.message.answer(
        "Запись отменена.",
        reply_markup=main_keyboard(),
    )
    await callback.answer()


# =========================================================
# AI MESSAGES
# =========================================================

@dp.message(BookingState.waiting_ai)
async def ai_active_message(message: Message):
    save_user(message)
    await process_ai_message(message)


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    clear_conversation(message.from_user.id)
    save_user(message)

    await safe_answer_photo(
        message,
        PHOTO_MAIN,
        WELCOME_TEXT,
        main_keyboard(),
    )


# =========================================================
# INFO
# =========================================================

@dp.callback_query(F.data == "info")
async def info_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.clear()

    await safe_edit_or_send_photo(
        callback,
        PHOTO_INFO,
        INFO_TEXT,
        back_keyboard(),
    )

    await callback.answer()


# =========================================================
# BACK
# =========================================================

@dp.callback_query(F.data == "back")
async def back_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    await state.clear()
    clear_conversation(callback.from_user.id)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await safe_answer_photo(
        callback.message,
        PHOTO_MAIN,
        WELCOME_TEXT,
        main_keyboard(),
    )

    await callback.answer()


# =========================================================
# КАТАЛОГ: НАВИГАЦИЯ КАК В ОБЪЕКТАХ
# =========================================================

def catalog_keyboard(prefix: str, index: int, total: int):
    previous_index = (index - 1) % total
    next_index = (index + 1) % total

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="←",
                callback_data=f"{prefix}_{previous_index}",
            ),
            InlineKeyboardButton(
                text=f"{index + 1}/{total}",
                callback_data="noop",
            ),
            InlineKeyboardButton(
                text="→",
                callback_data=f"{prefix}_{next_index}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="back",
                style="danger",
            )
        ],
    ])


async def show_catalog_item(
    callback: CallbackQuery,
    items,
    index: int,
    prefix: str,
):
    total = len(items)
    index %= total

    _, text, photo_id = items[index]
    markup = catalog_keyboard(prefix, index, total)

    # Сначала отправляем новый экран, затем удаляем старый.
    # Поэтому при проблеме с file_id старый экран не пропадёт раньше времени.
    new_message = await safe_answer_photo(
        callback.message,
        photo_id,
        text or "Без описания.",
        markup,
    )

    if new_message is not callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    await callback.answer()


# =========================================================
# PRODUCTS - USER
# =========================================================

@dp.callback_query(F.data == "products")
async def products_callback(
    callback: CallbackQuery,
):
    products = get_products()

    if not products:
        await safe_edit_text(callback.message, 
            "Товары пока не добавлены.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return

    await show_catalog_item(
        callback,
        products,
        0,
        "product_view",
    )


@dp.callback_query(F.data.startswith("product_view_"))
async def product_view_callback(
    callback: CallbackQuery,
):
    products = get_products()

    if not products:
        await safe_edit_text(callback.message, 
            "Товары пока не добавлены.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return

    try:
        index = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка навигации.", show_alert=True)
        return

    await show_catalog_item(
        callback,
        products,
        index,
        "product_view",
    )


# =========================================================
# PROMOTIONS - USER
# =========================================================

@dp.callback_query(F.data == "promotions")
async def promotions_callback(
    callback: CallbackQuery,
):
    promotions = get_promotions()

    if not promotions:
        await safe_edit_text(callback.message, 
            "Акций пока нет.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return

    await show_catalog_item(
        callback,
        promotions,
        0,
        "promotion_view",
    )


@dp.callback_query(F.data.startswith("promotion_view_"))
async def promotion_view_callback(
    callback: CallbackQuery,
):
    promotions = get_promotions()

    if not promotions:
        await safe_edit_text(callback.message, 
            "Акций пока нет.",
            reply_markup=back_keyboard(),
        )
        await callback.answer()
        return

    try:
        index = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка навигации.", show_alert=True)
        return

    await show_catalog_item(
        callback,
        promotions,
        index,
        "promotion_view",
    )


# =========================================================
# ADMIN
# =========================================================

@dp.message(Command("admin"))
async def admin_command(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        await message.answer("Нет доступа.")
        return

    await state.clear()

    await message.answer(
        "Админ-панель",
        reply_markup=admin_keyboard(),
    )


@dp.callback_query(F.data == "admin")
async def admin_callback(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.clear()

    await safe_edit_text(callback.message, 
        "Админ-панель",
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "file_id_tool")
async def file_id_tool(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.clear()
    await state.set_state(FileIdState.photo)

    await safe_edit_text(callback.message, 
        "Отправьте фотографию.\n\n"
        "Я пришлю её Telegram file_id, который можно использовать в коде бота.",
        reply_markup=cancel_keyboard("admin"),
    )
    await callback.answer()


@dp.message(FileIdState.photo)
async def file_id_photo(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    if not message.photo:
        await message.answer("Отправьте именно фотографию.")
        return

    photo_id = message.photo[-1].file_id
    await state.clear()

    await message.answer(
        f"file_id фото:\n\n{photo_id}",
        reply_markup=admin_keyboard(),
    )


@dp.callback_query(F.data == "admin_back")
async def admin_back(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await state.clear()

    await callback.message.delete()

    await safe_answer_photo(
        callback.message,
        PHOTO_MAIN,
        WELCOME_TEXT,
        main_keyboard(),
    )

    await callback.answer()


# =========================================================
# ADMIN PRODUCTS
# =========================================================

@dp.callback_query(F.data == "admin_products")
async def admin_products(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await safe_edit_text(callback.message, 
        "Управление товарами",
        reply_markup=product_admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "product_add")
async def product_add(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    await state.clear()
    await state.set_state(ProductAddState.text)

    await safe_edit_text(callback.message, 
        "Отправьте товар одним сообщением.\n\n"
        "Можно отправить обычный текст или фотографию с подписью.\n"
        "Фотография автоматически сохранится как Telegram file_id.",
        reply_markup=cancel_keyboard("admin_products"),
    )
    await callback.answer()


@dp.message(ProductAddState.text)
async def product_add_content(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    if message.photo:
        photo_id = message.photo[-1].file_id
        text = (message.caption or "").strip()
    else:
        photo_id = ""
        text = (message.text or "").strip()

    if not text and not photo_id:
        await message.answer(
            "Отправьте текст товара или фотографию с подписью."
        )
        return

    add_product(text, photo_id)
    await state.clear()

    result_text = "Товар добавлен."
    if photo_id:
        result_text += f"\n\nfile_id фото:\n{photo_id}"

    await message.answer(
        result_text,
        reply_markup=product_admin_keyboard(),
    )


@dp.callback_query(F.data == "product_list")
async def product_list(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    products = get_products()

    if not products:
        await safe_edit_text(callback.message, 
            "Товаров пока нет.",
            reply_markup=product_admin_keyboard(),
        )
        await callback.answer()
        return

    await safe_edit_text(callback.message, 
        "Список товаров",
    )

    for product_id, text, photo_id in products:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Изменить",
                    callback_data=f"edit_product:{product_id}",
                    style="primary",
                )],
                [InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"delete_product:{product_id}",
                    style="danger",
                )],
            ]),
        )

    await callback.message.answer(
        "Управление товарами",
        reply_markup=product_admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_product:"))
async def edit_product(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":")[1])
    product = get_product(product_id)

    if not product:
        await callback.answer("Товар не найден.", show_alert=True)
        return

    await state.clear()
    await state.update_data(product_id=product_id)
    await state.set_state(ProductEditState.text)

    await safe_edit_text(callback.message, 
        "Отправьте новый полный текст товара.",
        reply_markup=cancel_keyboard("product_list"),
    )
    await callback.answer()


@dp.message(ProductEditState.text)
async def product_edit_text(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    text = (message.text or message.caption or "").strip()

    if not text:
        await message.answer("Отправьте полный текст товара.")
        return

    await state.update_data(text=text)
    await state.set_state(ProductEditState.photo)

    await message.answer(
        "Отправьте новую фотографию товара.\n\n"
        "Если нужно оставить старое фото, напишите «Оставить».\n"
        "Если фото нужно убрать, напишите «Без фото»."
    )


@dp.message(ProductEditState.photo)
async def product_edit_photo(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    old_product = get_product(data["product_id"])

    if not old_product:
        await state.clear()
        await message.answer(
            "Товар не найден.",
            reply_markup=product_admin_keyboard(),
        )
        return

    if message.photo:
        photo_id = message.photo[-1].file_id
    else:
        command = (message.text or "").strip().lower()

        if command == "оставить":
            photo_id = old_product[2]
        elif command == "без фото":
            photo_id = ""
        else:
            await message.answer(
                "Отправьте фотографию, «Оставить» или «Без фото»."
            )
            return

    update_product(
        data["product_id"],
        data["text"],
        photo_id,
    )

    await state.clear()

    await message.answer(
        "Товар обновлён.",
        reply_markup=product_admin_keyboard(),
    )


@dp.callback_query(F.data.startswith("delete_product:"))
async def delete_product_confirm(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":")[1])

    await safe_edit_text(callback.message, 
        "Удалить этот товар?",
        reply_markup=confirm_delete_keyboard("product", product_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete_product:"))
async def delete_product_final(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    product_id = int(callback.data.split(":")[1])
    delete_product(product_id)

    await safe_edit_text(callback.message, 
        "Товар удалён.",
        reply_markup=product_admin_keyboard(),
    )
    await callback.answer()


# =========================================================
# ADMIN PROMOTIONS
# =========================================================

@dp.callback_query(F.data == "admin_promotions")
async def admin_promotions(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    await safe_edit_text(callback.message, 
        "Управление акциями",
        reply_markup=promotion_admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data == "promotion_add")
async def promotion_add(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    await state.clear()
    await state.set_state(PromotionAddState.text)

    await safe_edit_text(callback.message, 
        "Отправьте акцию одним сообщением.\n\n"
        "Можно отправить обычный текст или фотографию с подписью.\n"
        "Фотография автоматически сохранится как Telegram file_id.",
        reply_markup=cancel_keyboard("admin_promotions"),
    )
    await callback.answer()


@dp.message(PromotionAddState.text)
async def promotion_add_content(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    if message.photo:
        photo_id = message.photo[-1].file_id
        text = (message.caption or "").strip()
    else:
        photo_id = ""
        text = (message.text or "").strip()

    if not text and not photo_id:
        await message.answer(
            "Отправьте текст акции или фотографию с подписью."
        )
        return

    add_promotion(text, photo_id)
    await state.clear()

    result_text = "Акция добавлена."
    if photo_id:
        result_text += f"\n\nfile_id фото:\n{photo_id}"

    await message.answer(
        result_text,
        reply_markup=promotion_admin_keyboard(),
    )


@dp.callback_query(F.data == "promotion_list")
async def promotion_list(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    promotions = get_promotions()

    if not promotions:
        await safe_edit_text(callback.message, 
            "Акций пока нет.",
            reply_markup=promotion_admin_keyboard(),
        )
        await callback.answer()
        return

    await safe_edit_text(callback.message, 
        "Список акций",
    )

    for promotion_id, text, photo_id in promotions:
        await callback.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Изменить",
                    callback_data=f"edit_promotion:{promotion_id}",
                    style="primary",
                )],
                [InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"delete_promotion:{promotion_id}",
                    style="danger",
                )],
            ]),
        )

    await callback.message.answer(
        "Управление акциями",
        reply_markup=promotion_admin_keyboard(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("edit_promotion:"))
async def edit_promotion(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    promotion_id = int(callback.data.split(":")[1])
    promotion = get_promotion(promotion_id)

    if not promotion:
        await callback.answer("Акция не найдена.", show_alert=True)
        return

    await state.clear()
    await state.update_data(promotion_id=promotion_id)
    await state.set_state(PromotionEditState.text)

    await safe_edit_text(callback.message, 
        "Отправьте новый полный текст акции.",
        reply_markup=cancel_keyboard("promotion_list"),
    )
    await callback.answer()


@dp.message(PromotionEditState.text)
async def promotion_edit_text(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    text = (message.text or message.caption or "").strip()

    if not text:
        await message.answer("Отправьте полный текст акции.")
        return

    await state.update_data(text=text)
    await state.set_state(PromotionEditState.photo)

    await message.answer(
        "Отправьте новую фотографию акции.\n\n"
        "Если нужно оставить старое фото, напишите «Оставить».\n"
        "Если фото нужно убрать, напишите «Без фото»."
    )


@dp.message(PromotionEditState.photo)
async def promotion_edit_photo(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    old_promotion = get_promotion(data["promotion_id"])

    if not old_promotion:
        await state.clear()
        await message.answer(
            "Акция не найдена.",
            reply_markup=promotion_admin_keyboard(),
        )
        return

    if message.photo:
        photo_id = message.photo[-1].file_id
    else:
        command = (message.text or "").strip().lower()

        if command == "оставить":
            photo_id = old_promotion[2]
        elif command == "без фото":
            photo_id = ""
        else:
            await message.answer(
                "Отправьте фотографию, «Оставить» или «Без фото»."
            )
            return

    update_promotion(
        data["promotion_id"],
        data["text"],
        photo_id,
    )

    await state.clear()

    await message.answer(
        "Акция обновлена.",
        reply_markup=promotion_admin_keyboard(),
    )


@dp.callback_query(F.data.startswith("delete_promotion:"))
async def delete_promotion_confirm(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    promotion_id = int(callback.data.split(":")[1])

    await safe_edit_text(callback.message, 
        "Удалить эту акцию?",
        reply_markup=confirm_delete_keyboard("promotion", promotion_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("confirm_delete_promotion:"))
async def delete_promotion_final(
    callback: CallbackQuery,
):
    if not is_admin(callback.from_user.id):
        return

    promotion_id = int(callback.data.split(":")[1])
    delete_promotion(promotion_id)

    await safe_edit_text(callback.message, 
        "Акция удалена.",
        reply_markup=promotion_admin_keyboard(),
    )
    await callback.answer()


# =========================================================
# BROADCAST
# =========================================================

def broadcast_button_keyboard(buttons):
    if not buttons:
        return None

    rows = []

    for index, button in enumerate(buttons):
        rows.append([
            InlineKeyboardButton(
                text=button["text"],
                url=button["url"],
                style=button.get("style", "primary"),
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_controls():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Добавить кнопку",
            callback_data="broadcast_add_button",
            style="primary",
        )],
        [InlineKeyboardButton(
            text="Предпросмотр",
            callback_data="broadcast_preview",
            style="primary",
        )],
        [InlineKeyboardButton(
            text="Отправить",
            callback_data="broadcast_send",
            style="success",
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="broadcast_cancel",
            style="danger",
        )],
    ])


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    await state.clear()
    await state.set_state(BroadcastState.message)

    await safe_edit_text(callback.message, 
        "Отправьте сообщение для рассылки.\n\n"
        "Можно отправить обычный текст или фотографию с подписью.",
        reply_markup=cancel_keyboard("admin"),
    )
    await callback.answer()


@dp.message(BroadcastState.message)
async def broadcast_message(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    if message.photo:
        # Telegram already provides the stable file_id for the uploaded photo.
        photo_id = message.photo[-1].file_id
        text = (message.caption or "").strip()
    else:
        photo_id = ""
        text = (message.text or "").strip()

    if not text and not photo_id:
        await message.answer(
            "Отправьте текст или фотографию с подписью."
        )
        return

    await state.update_data(
        broadcast_text=text,
        broadcast_photo_file_id=photo_id,
        broadcast_buttons=[],
    )
    await state.set_state(BroadcastState.add_button)

    if photo_id:
        await message.answer(
            "Фото получено и сохранено как Telegram file_id.\n\n"
            "Теперь можно добавить кнопки или отправить рассылку.",
            reply_markup=broadcast_controls(),
        )
    else:
        await message.answer(
            "Сообщение получено.\n\n"
            "Теперь можно добавить кнопки или отправить рассылку.",
            reply_markup=broadcast_controls(),
        )


@dp.callback_query(F.data == "broadcast_add_button")
async def broadcast_add_button(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(BroadcastState.button_text)

    await callback.message.answer(
        "Введите название кнопки."
    )
    await callback.answer()


@dp.message(BroadcastState.button_text)
async def broadcast_button_text(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()

    if not text:
        await message.answer("Введите название кнопки.")
        return

    await state.update_data(current_button_text=text)
    await state.set_state(BroadcastState.button_url)

    await message.answer("Отправьте ссылку кнопки.")


@dp.message(BroadcastState.button_url)
async def broadcast_button_url(
    message: Message,
    state: FSMContext,
):
    if not is_admin(message.from_user.id):
        return

    url = (message.text or "").strip()

    if not (
        url.startswith("https://")
        or url.startswith("http://")
        or url.startswith("tg://")
    ):
        await message.answer(
            "Ссылка должна начинаться с https://, http:// или tg://."
        )
        return

    await state.update_data(current_button_url=url)
    await state.set_state(BroadcastState.button_style)

    await message.answer(
        "Выберите стиль кнопки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Синий",
                callback_data="broadcast_style_primary",
                style="primary",
            )],
            [InlineKeyboardButton(
                text="Зелёный",
                callback_data="broadcast_style_success",
                style="success",
            )],
            [InlineKeyboardButton(
                text="Красный",
                callback_data="broadcast_style_danger",
                style="danger",
            )],
        ]),
    )


async def finish_broadcast_button(
    callback: CallbackQuery,
    state: FSMContext,
    style: str,
):
    data = await state.get_data()
    buttons = data.get("broadcast_buttons", [])

    buttons.append({
        "text": data["current_button_text"],
        "url": data["current_button_url"],
        "style": style,
    })

    await state.update_data(broadcast_buttons=buttons)
    await state.set_state(BroadcastState.add_button)

    await callback.message.answer(
        "Кнопка добавлена.",
        reply_markup=broadcast_controls(),
    )
    await callback.answer()


@dp.callback_query(F.data == "broadcast_style_primary")
async def broadcast_style_primary(
    callback: CallbackQuery,
    state: FSMContext,
):
    await finish_broadcast_button(callback, state, "primary")


@dp.callback_query(F.data == "broadcast_style_success")
async def broadcast_style_success(
    callback: CallbackQuery,
    state: FSMContext,
):
    await finish_broadcast_button(callback, state, "success")


@dp.callback_query(F.data == "broadcast_style_danger")
async def broadcast_style_danger(
    callback: CallbackQuery,
    state: FSMContext,
):
    await finish_broadcast_button(callback, state, "danger")


@dp.callback_query(F.data == "broadcast_preview")
async def broadcast_preview(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    photo_id = data.get("broadcast_photo_file_id", "")
    buttons = data.get("broadcast_buttons", [])
    markup = broadcast_button_keyboard(buttons)

    try:
        if photo_id:
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=photo_id,
                caption=text or None,
                reply_markup=markup,
            )
        else:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=text,
                reply_markup=markup,
            )
    except Exception as error:
        logging.exception("Ошибка предпросмотра рассылки: %s", error)
        await callback.message.answer(
            "Не удалось показать предпросмотр. Проверьте фотографию или текст."
        )

    await callback.answer()


@dp.callback_query(F.data == "broadcast_send")
async def broadcast_send(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    photo_id = data.get("broadcast_photo_file_id", "")
    buttons = data.get("broadcast_buttons", [])
    markup = broadcast_button_keyboard(buttons)

    if not text and not photo_id:
        await callback.answer("Сообщение не найдено.", show_alert=True)
        return

    user_ids = get_all_user_ids()

    await callback.message.answer(
        f"Рассылка началась.\nПолучателей: {len(user_ids)}"
    )
    await callback.answer()

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            if photo_id:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=photo_id,
                    caption=text or None,
                    reply_markup=markup,
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    reply_markup=markup,
                )
            sent += 1

        except Exception as error:
            failed += 1
            logging.warning(
                "Рассылка пользователю %s не удалась: %s",
                user_id,
                error,
            )

            error_text = str(error).lower()
            if (
                "blocked" in error_text
                or "chat not found" in error_text
                or "user is deactivated" in error_text
            ):
                deactivate_user(user_id)

        await asyncio.sleep(0.05)

    await state.clear()

    await callback.message.answer(
        "Рассылка завершена.\n\n"
        f"Всего: {len(user_ids)}\n"
        f"Доставлено: {sent}\n"
        f"Не доставлено: {failed}",
        reply_markup=admin_keyboard(),
    )


@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(
    callback: CallbackQuery,
    state: FSMContext,
):
    if not is_admin(callback.from_user.id):
        return

    await state.clear()

    await callback.message.answer(
        "Рассылка отменена.",
        reply_markup=admin_keyboard(),
    )
    await callback.answer()


# =========================================================
# Обычные сообщения
# =========================================================

@dp.message()
async def fallback(message: Message):
    save_user(message)

    await message.answer(
        "Используйте кнопки меню.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# GLOBAL ERROR HANDLER
# =========================================================

@dp.errors()
async def global_error_handler(event):
    logging.exception(
        "Unhandled bot error: %s",
        getattr(event, "exception", event),
    )
    return True


# =========================================================
# STARTUP
# =========================================================

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    init_db()

    logging.info("Bot started.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
