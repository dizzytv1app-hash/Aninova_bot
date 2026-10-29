import functools
import html
import random
import logging
import os
import traceback
import shutil
import re
import asyncio
import difflib
import time
from collections import deque
import sqlite3
import threading
import json
import tempfile
import zipfile
import io
from functools import wraps
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from telegram import (
    Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton, LinkPreviewOptions
)
from telegram.error import RetryAfter, Forbidden, BadRequest, NetworkError
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler,
    ChatJoinRequestHandler, TypeHandler, ApplicationHandlerStop, filters
)

# ==================== CONFIG ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip("\"'")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN secret is required to start the Telegram bot.")
ADMIN_ID = 6222096713
ADMIN_USERNAME = "@Reyimberganov_i"
ADMIN_CONTACT_URL = f"https://t.me/{ADMIN_USERNAME.lstrip('@')}"
CHANNEL_USERNAME = "@AniNavo1"
CHANNEL_LINK = "https://t.me/AniNavo1"
BOT_USERNAME = "AniNavo1Bot"  # @ belgisiz, deep-link uchun (t.me/<BOT_USERNAME>?start=kod)
DEFAULT_REQUIRED_CHANNEL_TITLE = "AniNavo1"
BACKUP_TIMEZONE_NAME = os.environ.get("BOT_TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent"
try:
    BACKUP_TIMEZONE = ZoneInfo(BACKUP_TIMEZONE_NAME)
except Exception:
    BACKUP_TIMEZONE_NAME = "Asia/Tashkent"
    BACKUP_TIMEZONE = timezone(timedelta(hours=5), name=BACKUP_TIMEZONE_NAME)

# Anime qo'shishda tanlash uchun janrlar ro'yxati (stikersiz)
GENRE_LIST = [
    "Jangari", "Sarguzasht", "Komediya", "Romantika", "Drama",
    "Fantastika", "Boshqa dunyo (Isekai)", "Ilmiy fantastika",
    "Qo'rqinchli", "Sirli", "Psixologik", "G'ayritabiiy",
    "Maktab", "Kundalik hayot", "Hentai", "Harem", "Ecchi",
    "Sport", "Jang san'ati", "Samuray",
]
GENRE_MIN_SELECT = 3
GENRE_MAX_SELECT = 4

ANIME_STATUSES = {
    "ongoing": "🟢 Davom etmoqda",
    "finished": "🔵 Tugagan",
    "soon": "🟡 Tez orada",
    "paused": "⏸ Tanaffusda",
}

# ==================== BOT SOZLAMALARI (tahrirlanadigan matnlar) ====================
_DEFAULT_START_TEXT = (
    "👋 Assalomu aleykum botimizga xush kelibsiz.\n\n"
    "🖥 Botimizda animelerni yuklab olib, tomosha qilishingiz mumkin.\n\n"
    "‼️ Botga anime kodini yoki nomini yuborishingiz mumkin!"
)
_DEFAULT_REKLAMA_TEXT = (
    "📢 *REKLAMA NARXLARI*\n\n"
    "⏳ 7 kun — 25 000 so'm\n"
    "⏳ 14 kun — 40 000 so'm\n"
    "⏳ 30 kun — 70 000 so'm\n\n"
    "💬 Kerakli muddat yuqorida ko'rsatilmagan bo'lsa, admin bilan bog'laning — boshqa muddatlar bo'yicha ham kelishib olamiz.\n\n"
    "🚫 Qimor, betting yoki 18+ kanallar joylashtirilmaydi!\n\n"
    "📩 Reklama berish uchun admin bilan bog'laning:"
)
_DEFAULT_GUIDE_TEXT = (
    "📖 QO'LLANMA — AniNavo bot\n\n"
    "Bu bot orqali animelarni to'g'ridan-to'g'ri Telegram'da tomosha qilishingiz mumkin. "
    "Quyida botning barcha imkoniyatlari qisqacha tushuntirilgan.\n\n"
    "━━━━━━━━━━━━━━━\n"
    "1️⃣ BOTNI BOSHLASH\n"
    "• /start bosing — bosh menyu chiqadi.\n"
    "• Botdan foydalanish uchun majburiy kanallarga obuna bo'lishingiz kerak. Obuna bo'lmagan bo'lsangiz, bot kanallar ro'yxatini ko'rsatadi, obuna bo'lgach davom etasiz. Yopiq kanalda qo'shilish so'rovini yuborsangiz ham bo'ladi.\n\n"
    "2️⃣ ANIME TOPISH\n"
    "Eng oson usul — anime kodini yoki nomini botga yozib yuboring:\n"
    "• Kod — faqat raqam (masalan: 123). Anime kodlarini rasmiy Instagram sahifamizdan olasiz (havola pastda, savol-javob bo'limida).\n"
    "• Nom — kamida 4 harf (masalan: Naruto). Nomni xato yozsangiz, bot «Balki siz shu animeni qidiryapsiz» deb o'xshash animelarni taklif qiladi.\n\n"
    "Yoki 🔍 Anime Izlash tugmasini bosing:\n"
    "🔢 Kod orqali izlash — kodni yozasiz\n"
    "🔤 Nom orqali izlash — nomini yozasiz\n"
    "🎭 Janr orqali izlash — janrni tanlaysiz, shu janrdagi animelar chiqadi\n"
    "🆕 So'ngi yuklanganlar — eng yangi animelar\n"
    "⭐ Reytingi baland — eng yuqori reytingli animelar\n"
    "👁 Ko'p ko'rilgan — eng ko'p ko'rilgan animelar\n"
    "📚 Barcha animelar — hamma animelar ro'yxati\n"
    "📋 Animelar ro'yxati — kanaldagi to'liq ro'yxatga o'tadi\n\n"
    "3️⃣ ANIME SAHIFASI\n"
    "Anime topilganda poster, nom, holati, janr, qismlar soni va tavsif chiqadi.\n"
    "• Anime bir nechta fasldan iborat bo'lsa, avval fasl tanlanadi.\n"
    "• Pastdagi raqamlar — qismlar. Raqamni bossangiz, shu qism videosi yuboriladi.\n"
    "• Qismlar ko'p bo'lsa, ⏮ ⏭ tugmalari bilan sahifalarni almashtiring.\n"
    "• Holatlar: 🟢 Davom etmoqda, 🔵 Tugagan, 🟡 Tez orada, ⏸ Tanaffusda.\n\n"
    "4️⃣ YANGI QISM HAQIDA XABAR\n"
    "Anime sahifasidagi «🔔 Yangi qism chiqsa xabar bering» tugmasini bossangiz, shu animening yangi qismi yuklanganda bot sizga o'zi xabar yuboradi va ▶️ Tomosha qilish tugmasi bilan o'sha faslni ochadi. Bekor qilish uchun shu tugmani yana bosing (🔕).\n\n"
    "5️⃣ KANAL POSTLARIDAN KIRISH\n"
    "Kanalimizdagi anime postining ostida ▶️ Tomosha qilish tugmasi bor. Uni bossangiz, bot ochiladi va to'g'ridan-to'g'ri shu anime sahifasi chiqadi.\n\n"
    "6️⃣ BOSH MENYU TUGMALARI\n"
    "⚙️ Kabinet — ismingiz, ID raqamingiz va botga qo'shilgan sana\n"
    "📺 Animelar Kanali — rasmiy kanalimizga o'tish\n"
    "📢 Reklama — reklama narxlari va admin bilan bog'lanish\n\n"
    "7️⃣ MUHIM QOIDALAR\n"
    "• Tugmalarni juda tez bosmang: qisqa vaqtda ko'p harakat qilsangiz, bot sizni bir necha soniya e'tiborsiz qoldiradi va «Juda tez» deb yozadi.\n"
    "• Kanaldan chiqib ketsangiz, bot qayta obuna bo'lishni so'rashi mumkin.\n"
    "• Anime nomini yozganda kamida 4 harf kiriting.\n\n"
    "8️⃣ SAVOL-JAVOB\n"
    "❓ Anime kodini qayerdan olaman?\n"
    "Anime kodlari rasmiy Instagram sahifamizda joylanadi.\n\n"
    "❓ Instagram sahifangiz qayerda?\n"
    "📸 Instagram:\n"
    "https://www.instagram.com/aninavo1?exln=MWQ5ZXp1ZTB3OWRmeA==\n\n"
    "❓ Anime topilmadi?\n"
    "Kodni tekshiring, nomni boshqacha yozib ko'ring yoki 🔍 Anime Izlash orqali janr bo'yicha qidiring.\n\n"
    "❓ Qism ochilmayapti?\n"
    "Majburiy kanallarga obuna bo'lganingizni tekshiring va /start bosing.\n\n"
    "❓ Reklama bermoqchiman?\n"
    "📢 Reklama bo'limiga kiring.\n\n"
    "Yoqimli tomosha! 🍿"
)

# setting_id -> (ko'rsatiladigan nom, app_meta kaliti, standart matn, o'chirib qo'yish mumkinmi)
_BOT_TEXT_SETTINGS = {
    "start":   ("📝 Start xabari",   "text_start",   _DEFAULT_START_TEXT,   False),
    "reklama": ("📢 Reklama matni",  "text_reklama", _DEFAULT_REKLAMA_TEXT, True),
    "guide":   ("📖 Qo'llanma matni", "text_guide",   _DEFAULT_GUIDE_TEXT,   True),
}

_START_BUTTON_SETTINGS = {
    "search":  ("🔍 Anime qidirish tugmasi", "button_search", "🔍 Anime Izlash"),
    "cabinet": ("⚙️ Kabinet tugmasi",         "button_cabinet", "⚙️ Kabinet"),
    "guide":   ("📖 Qo'llanma tugmasi",        "button_guide", "📖 Qo'llanma"),
    "channel": ("📺 Kanal tugmasi",            "button_channel", "📺 Animelar Kanali"),
    "ad":      ("📢 Reklama tugmasi",          "button_ad", "📢 Reklama"),
}

def _bot_text_enabled(setting_id):
    _, key, _, can_disable = _BOT_TEXT_SETTINGS[setting_id]
    if not can_disable:
        return True
    return get_bot_setting(f"{key}_enabled", "1") != "0"

def _bot_text_value(setting_id):
    _, key, default, _ = _BOT_TEXT_SETTINGS[setting_id]
    return get_bot_setting(key, default)

def _start_button_value(setting_id):
    _, key, default = _START_BUTTON_SETTINGS[setting_id]
    return get_bot_setting(key, default)

def _start_gif_file_id():
    return get_bot_setting("start_gif_file_id", "")

def _start_gif_enabled():
    return bool(_start_gif_file_id()) and get_bot_setting("start_gif_enabled", "0") == "1"

# ==================== STATES ====================
(
    WAIT_ANIME_CODE, WAIT_ANIME_NAME, WAIT_ANIME_YEAR, WAIT_ANIME_GENRE,
    WAIT_ANIME_EPISODES, WAIT_ANIME_DESC, WAIT_ANIME_POSTER,
    WAIT_EPISODE_ANIME, WAIT_EPISODE_NUM, WAIT_EPISODE_VIDEO,
    WAIT_DELETE_CODE, WAIT_DELETE_CONFIRM, WAIT_ADD_CHANNEL,
    WAIT_EDIT_CODE, WAIT_EDIT_FIELD, WAIT_EDIT_VALUE,
    WAIT_BROADCAST_MSG, WAIT_EPM_ANIME, WAIT_EPM_ACTION, WAIT_EPM_NEWNUM,
    WAIT_NEWSEASON_EPISODES, WAIT_NEWSEASON_POSTER, WAIT_ANIME_STATUS,
    WAIT_ANIME_ORIGINAL, WAIT_ANIME_RATING, WAIT_EPISODE_POSTER,
    WAIT_ANIME_BULK,
) = range(27)

# ==================== BUTTON TEXTS (rejected during conversations) ====================
ADMIN_BUTTONS = {
    "➕ Anime Qo'shish", "📺 Qism Qo'shish", "📋 Animeler Ro'yxati",
    "📊 Statistika", "🗑 Anime O'chirish", "✏️ Anime Tahrirlash", "📡 Kanallar",
    "📣 Xabar Yuborish", "🔙 Asosiy Menu", "📤 Kanalga Yuborish", "👥 Adminlar",
    "🆕 Yangi Qismlar", "🛠 Qism Boshqarish", "💾 Backup Olish", "♻️ Backup Tiklash", "🏷 Anime Holati",
    "🔍 Anime Izlash", "📖 Qo'llanma", "📢 Reklama", "📺 Animelar Kanali",
    "⚙️ Bot Sozlamalari", "📊 So'rovnomalar",
}

# Filter matching every reply-keyboard button — used as a universal conversation escape
_MENU_BTN_FILTER = filters.Regex(
    r"^(➕ Anime Qo'shish|📺 Qism Qo'shish|📋 Animeler Ro'yxati"
    r"|📊 Statistika|🗑 Anime O'chirish|✏️ Anime Tahrirlash|📡 Kanallar"
    r"|📣 Xabar Yuborish|🔙 Asosiy Menu|🔍 Anime Izlash"
    r"|📢 Reklama|📺 Animelar Kanali|📤 Kanalga Yuborish|👥 Adminlar|🆕 Yangi Qismlar|🛠 Qism Boshqarish|💾 Backup Olish|♻️ Backup Tiklash|🏷 Anime Holati|📖 Qo'llanma|⏭ Shorts.*|⚙️ Bot Sozlamalari|📊 So'rovnomalar)$"
)

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Telegram HTTP request URLs contain the bot token; keep those URLs out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

async def _check_menu_escape(update, context):
    """Raqam/matn so'raladigan holatlarda admin menyu tugmasini bossa,
    'faqat raqam yuboring' deb ushlab qolish o'rniga o'sha tugmaga o'tkazadi."""
    txt = update.message.text.strip() if update.message and update.message.text else ""
    if txt in ADMIN_BUTTONS:
        return await _interrupt_fallback(update, context)
    return None

# ==================== DATABASE ====================
# Bitta connection ishlatiladi, lekin uning barcha SQLite amallari bitta re-entrant
# lock bilan himoyalanadi. Python-Telegram handlerlari bir vaqtda ishlaganda ham
# transactionlar bir-birining ustiga chiqib ketmaydi.
_DB_CONN = None
_DB_LOCK = threading.RLock()
_DB_PATH = os.path.abspath("anime.db")


def _db_locked(func):
    """SQLite connection/cursor ishlatiladigan funksiyani thread-safe qiladi.

    Re-entrant lock kerak, chunki masalan get_required_channels() ichida
    cleanup_expired_channels() ham chaqiriladi.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with _DB_LOCK:
            try:
                return func(*args, **kwargs)
            except Exception:
                if _DB_CONN is not None:
                    try:
                        _DB_CONN.rollback()
                    except sqlite3.Error:
                        pass
                raise
    return wrapper

def get_db():
    global _DB_CONN
    with _DB_LOCK:
        if _DB_CONN is None:
            _DB_CONN = sqlite3.connect(
                _DB_PATH,
                check_same_thread=False,
                timeout=30.0,
            )
            _DB_CONN.execute("PRAGMA busy_timeout=30000")
            _DB_CONN.execute("PRAGMA journal_mode=WAL")
            _DB_CONN.execute("PRAGMA synchronous=NORMAL")
            _DB_CONN.execute("PRAGMA foreign_keys=ON")
            _DB_CONN.execute("PRAGMA cache_size=-10000")
        return _DB_CONN


def _create_pre_migration_backup(conn):
    """Schema migratsiyasidan oldin joriy DB'ning rollback nusxasini yaratadi."""
    if not os.path.exists(_DB_PATH) or os.path.getsize(_DB_PATH) == 0:
        return None

    # Oldingi rollback nusxasini hech qachon ustidan yozmaymiz. Microsecond
    # timestamp bir necha marta ketma-ket ishga tushirilganda ham alohida fayl
    # yaratadi.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = f"{_DB_PATH}.pre_migration_{timestamp}.bak"
    temp_path = f"{backup_path}.tmp"
    while os.path.exists(backup_path) or os.path.exists(temp_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = f"{_DB_PATH}.pre_migration_{timestamp}.bak"
        temp_path = f"{backup_path}.tmp"
    backup_conn = sqlite3.connect(temp_path, timeout=30.0)
    try:
        with backup_conn:
            conn.backup(backup_conn)
        os.replace(temp_path, backup_path)
        logger.info("Schema migratsiyasi uchun backup yaratildi: %s", backup_path)
        return backup_path
    finally:
        backup_conn.close()
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _deduplicate_seasons_and_episodes(conn):
    """Eski duplicate fasl/qismlarni ID'larni imkon qadar saqlagan holda birlashtiradi."""
    c = conn.cursor()

    # Fasl tushunchasidan oldingi bazalarda season_id=NULL bo'lgan qismlarni
    # mavjud yoki yangi 1-faslga biriktiramiz.
    c.execute("SELECT code, total_episodes, poster_file_id FROM animes")
    for code, total_ep, poster_id in c.fetchall():
        c.execute(
            "SELECT id FROM seasons WHERE anime_code=? AND season_num=1 "
            "ORDER BY id LIMIT 1",
            (code,),
        )
        season_row = c.fetchone()
        if season_row:
            season1_id = season_row[0]
        else:
            c.execute(
                "INSERT INTO seasons "
                "(anime_code, season_num, poster_file_id, total_episodes, added_date) "
                "VALUES (?, 1, ?, ?, ?)",
                (code, poster_id, total_ep, datetime.now().strftime("%Y-%m-%d")),
            )
            season1_id = c.lastrowid
        c.execute(
            "UPDATE episodes SET season_id=? "
            "WHERE anime_code=? AND season_id IS NULL",
            (season1_id, code),
        )

    # Bir anime ichidagi bir xil season_num yozuvlarini eng eski ID atrofida
    # birlashtiramiz. Ikkinchi faslni o'chirishdan oldin uning qismlari ko'chiriladi.
    c.execute("""
        SELECT anime_code, season_num, MIN(id)
        FROM seasons
        GROUP BY anime_code, season_num
        HAVING COUNT(*) > 1
    """)
    duplicate_seasons = c.fetchall()
    for anime_code, season_num, keep_id in duplicate_seasons:
        c.execute(
            "SELECT id, poster_file_id, total_episodes, poster_type, "
            "total_episodes_label FROM seasons "
            "WHERE anime_code=? AND season_num=? ORDER BY id",
            (anime_code, season_num),
        )
        season_rows = c.fetchall()
        keep_row = season_rows[0]
        keep_poster = keep_row[1]
        keep_total = keep_row[2]
        keep_poster_type = keep_row[3]
        keep_label = keep_row[4]

        for duplicate_id, poster_id, total_ep, poster_type, ep_label in season_rows[1:]:
            if not keep_poster and poster_id:
                keep_poster = poster_id
            if (keep_total is None or keep_total == 0) and total_ep:
                keep_total = total_ep
            if not keep_poster_type and poster_type:
                keep_poster_type = poster_type
            if not keep_label and ep_label:
                keep_label = ep_label

            c.execute(
                "SELECT id, episode_num, video_file_id, added_at "
                "FROM episodes WHERE season_id=? ORDER BY id",
                (duplicate_id,),
            )
            for episode_id, episode_num, video_file_id, added_at in c.fetchall():
                c.execute(
                    "SELECT id, video_file_id, added_at FROM episodes "
                    "WHERE season_id=? AND episode_num=? ORDER BY id LIMIT 1",
                    (keep_id, episode_num),
                )
                existing = c.fetchone()
                if existing is None:
                    c.execute(
                        "UPDATE episodes SET season_id=? WHERE id=?",
                        (keep_id, episode_id),
                    )
                else:
                    existing_id, existing_video_id, existing_added_at = existing
                    duplicate_is_newer = (
                        added_at is not None
                        and (
                            existing_added_at is None
                            or added_at > existing_added_at
                        )
                    )
                    if (not existing_video_id and video_file_id) or duplicate_is_newer:
                        c.execute(
                            "UPDATE episodes SET video_file_id=?, added_at=? WHERE id=?",
                            (video_file_id, added_at, existing_id),
                        )
                    c.execute("DELETE FROM episodes WHERE id=?", (episode_id,))

            c.execute("DELETE FROM seasons WHERE id=?", (duplicate_id,))

        c.execute(
            "UPDATE seasons SET poster_file_id=?, total_episodes=?, "
            "poster_type=?, total_episodes_label=? WHERE id=?",
            (keep_poster, keep_total, keep_poster_type, keep_label, keep_id),
        )

    # Bir xil season_id + episode_num bo'yicha qolgan duplicate qismlarni
    # eng eski ID'ni saqlagan holda birlashtiramiz.
    c.execute("""
        SELECT season_id, episode_num, MIN(id)
        FROM episodes
        WHERE season_id IS NOT NULL
        GROUP BY season_id, episode_num
        HAVING COUNT(*) > 1
    """)
    for season_id, episode_num, keep_episode_id in c.fetchall():
        c.execute(
            "SELECT id, video_file_id, added_at FROM episodes "
            "WHERE season_id=? AND episode_num=? ORDER BY id",
            (season_id, episode_num),
        )
        rows = c.fetchall()
        keep_id, keep_video_id, keep_added_at = rows[0]
        for episode_id, video_file_id, added_at in rows[1:]:
            newer = (
                added_at is not None
                and (keep_added_at is None or added_at > keep_added_at)
            )
            if (not keep_video_id and video_file_id) or newer:
                keep_video_id, keep_added_at = video_file_id, added_at
            c.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
        c.execute(
            "UPDATE episodes SET video_file_id=?, added_at=? WHERE id=?",
            (keep_video_id, keep_added_at, keep_episode_id),
        )

@_db_locked
def init_db():
    existing_db = os.path.exists(_DB_PATH) and os.path.getsize(_DB_PATH) > 0
    conn = get_db()
    if existing_db:
        _create_pre_migration_backup(conn)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""
        CREATE TABLE IF NOT EXISTS animes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code INTEGER UNIQUE,
            name TEXT,
            year INTEGER,
            genre TEXT,
            total_episodes INTEGER,
            description TEXT,
            poster_file_id TEXT,
            added_date TEXT
        )
    """)
    try:
        c.execute("ALTER TABLE animes ADD COLUMN channel_post_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN episode_thumb_file_id TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    c.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_code INTEGER,
            episode_num INTEGER,
            video_file_id TEXT,
            FOREIGN KEY(anime_code) REFERENCES animes(code)
        )
    """)
    try:
        c.execute("ALTER TABLE episodes ADD COLUMN added_at REAL")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            joined_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            link TEXT
        )
    """)
    try:
        c.execute("ALTER TABLE required_channels ADD COLUMN title TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE required_channels ADD COLUMN expires_at TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    # Yangi bo'sh bazada asosiy kanal majburiy obuna sifatida avtomatik qo'shiladi.
    # Admin panelidan qo'shilgan keyingi kanallar ushbu kanal bilan birga tekshiriladi.
    c.execute(
        "INSERT OR IGNORE INTO required_channels (username, link, title, expires_at) VALUES (?, ?, ?, NULL)",
        (CHANNEL_USERNAME, CHANNEL_LINK, DEFAULT_REQUIRED_CHANNEL_TITLE)
    )
    c.execute("""
        CREATE TABLE IF NOT EXISTS join_requests (
            chat_id TEXT,
            user_id INTEGER,
            requested_at TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_date TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anime_code INTEGER,
            season_num INTEGER,
            poster_file_id TEXT,
            total_episodes INTEGER,
            added_date TEXT
        )
    """)
    try:
        c.execute("ALTER TABLE seasons ADD COLUMN poster_type TEXT DEFAULT 'photo'")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE seasons ADD COLUMN total_episodes_label TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN poster_type TEXT DEFAULT 'photo'")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN total_episodes_label TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN added_at REAL")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN status TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN original_title TEXT")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN rating REAL")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN is_featured INTEGER DEFAULT 0")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    try:
        c.execute("ALTER TABLE animes ADD COLUMN is_popular INTEGER DEFAULT 0")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise
    # Eski (vaqt belgisi yo'q) animelarga hozirgi vaqtni belgilaymiz — shunda ular darhol
    # 48 soatlik ro'yxatlarga (O'chirish/Tahrirlash/Kanalga Yuborish) kirib keladi.
    # Bu faqat vaqt belgisi ALI yo'q qatorlarga tegadi, shuning uchun xavfsiz bir martalik amal.
    c.execute("UPDATE animes SET added_at=? WHERE added_at IS NULL", (datetime.now().timestamp(),))
    try:
        c.execute("ALTER TABLE episodes ADD COLUMN season_id INTEGER")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise

    # Qism video cover'i endi alohida animes.episode_thumb_file_id ustunida saqlanadi.
    # Avvalgi versiya cover'ni fasl posteriga yozib qo'ygan bo'lishi mumkin. Quyidagi
    # tiklash faqat bir marta bajariladi; keyingi yangi fasl posterlariga tegilmaydi.
    c.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")

    # Statistika uchun — foydalanuvchilarning anime ko'rish va qism so'rash
    # harakatlarini yozib boradi (adminlarniki bu jadvalga yozilmaydi).
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            anime_code INTEGER,
            user_id INTEGER,
            created_at REAL NOT NULL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_type_time ON activity_log(event_type, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_anime ON activity_log(anime_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_type_time_user ON activity_log(event_type, created_at, user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_activity_user_type ON activity_log(user_id, event_type)")

    c.execute("SELECT value FROM app_meta WHERE key='episode_cover_separation_v1'")
    if not c.fetchone():
        c.execute("""
            UPDATE seasons
            SET poster_file_id = (
                    SELECT a.poster_file_id FROM animes a WHERE a.code = seasons.anime_code
                ),
                poster_type = COALESCE((
                    SELECT a.poster_type FROM animes a WHERE a.code = seasons.anime_code
                ), 'photo')
            WHERE EXISTS (SELECT 1 FROM animes a WHERE a.code = seasons.anime_code)
        """)
        c.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("episode_cover_separation_v1", datetime.now().isoformat())
        )

    # Qism cover'i endi har bir faslda alohida saqlanadi (seasons.episode_thumb_file_id).
    # Eski anime-darajasidagi cover bir marta mavjud fasllarga ko'chiriladi.
    _ensure_season_cover_column(conn)
    c.execute("SELECT value FROM app_meta WHERE key='season_episode_cover_v1'")
    if not c.fetchone():
        c.execute("""
            UPDATE seasons
            SET episode_thumb_file_id = (
                SELECT a.episode_thumb_file_id FROM animes a WHERE a.code = seasons.anime_code
            )
            WHERE episode_thumb_file_id IS NULL OR episode_thumb_file_id = ''
        """)
        c.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("season_episode_cover_v1", datetime.now().isoformat())
        )

    # Har bir animening qidirishlar soni animes.view_count hisoblagichida saqlanadi.
    # Eski ko'rishlar activity_log'dan bir marta hisoblab qo'yiladi.
    _ensure_view_count_column(conn)
    c.execute("SELECT value FROM app_meta WHERE key='anime_view_count_v1'")
    if not c.fetchone():
        c.execute("""
            UPDATE animes
            SET view_count = (
                SELECT COUNT(*) FROM activity_log
                WHERE activity_log.event_type = 'anime_view' AND activity_log.anime_code = animes.code
            )
        """)
        c.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("anime_view_count_v1", datetime.now().isoformat())
        )

    # Avval eski bazadagi legacy yozuvlarni va duplicate fasl/qismlarni bitta
    # transaction ichida birlashtiramiz. Shundan keyingina UNIQUE indexlar
    # yaratiladi; xato bo'lsa @_db_locked rollback qiladi.
    _deduplicate_seasons_and_episodes(conn)

    # Tezlik va yaxlitlik uchun indekslar. UNIQUE indexlar mavjud ID'larni
    # almashtirmaydi, faqat kelgusidagi duplicate yozuvlarni to'sadi.
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id)")
    c.execute("DROP INDEX IF EXISTS idx_episodes_season_num")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_episode ON episodes(season_id, episode_num)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_seasons_anime ON seasons(anime_code)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_season ON seasons(anime_code, season_num)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_animes_code ON animes(code)")
    foreign_key_errors = c.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(
            f"Foreign key xatolari topildi, migratsiya bekor qilindi: {foreign_key_errors[:10]}"
        )
    conn.commit()

@_db_locked
def get_next_code():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT MAX(code) FROM animes")
    result = c.fetchone()[0]
    return (result or 0) + 1

@_db_locked
def add_anime(code, name, year, genre, total_episodes, description, poster_file_id, poster_type="photo", total_episodes_label=None,
              original_title=None, rating=None):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now()
    c.execute("""
        INSERT INTO animes (code, name, year, genre, total_episodes, description, poster_file_id, added_date, poster_type, total_episodes_label, added_at, original_title, rating)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (code, name, year, genre, total_episodes, description, poster_file_id, now.strftime("%Y-%m-%d"), poster_type, total_episodes_label, now.timestamp(), original_title, rating))
    conn.commit()

ALLOWED_ANIME_FIELDS = {"name", "year", "genre", "total_episodes", "description", "original_title", "rating", "is_featured", "is_popular"}

@_db_locked
def update_anime_field(code, field, value):
    if field not in ALLOWED_ANIME_FIELDS:
        raise ValueError(f"Ruxsat etilmagan ustun: {field}")
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE animes SET {field}=? WHERE code=?", (value, code))
    conn.commit()

@_db_locked
def set_anime_status(code, status_key):
    if status_key not in ANIME_STATUSES:
        raise ValueError(f"Noma'lum holat: {status_key}")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE animes SET status=? WHERE code=?", (status_key, code))
    conn.commit()

@_db_locked
def get_anime_status(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status FROM animes WHERE code=?", (code,))
    row = c.fetchone()
    return row[0] if row else None

@_db_locked
def get_animes_by_status(status_key):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name FROM animes WHERE status=? ORDER BY id", (status_key,))
    return c.fetchall()

@_db_locked
def add_episode(season_id, episode_num, video_file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO episodes (season_id, episode_num, video_file_id, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(season_id, episode_num) DO UPDATE SET
            video_file_id=excluded.video_file_id,
            added_at=excluded.added_at
    """, (season_id, episode_num, video_file_id, datetime.now().timestamp()))
    conn.commit()

@_db_locked
def get_recent_episodes(hours=36):
    """So'nggi `hours` soat ichida qo'shilgan qismlarni anime/fasl nomi bilan qaytaradi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT s.anime_code, e.episode_num, e.added_at, a.name, s.season_num
        FROM episodes e
        JOIN seasons s ON e.season_id = s.id
        JOIN animes a ON s.anime_code = a.code
        WHERE e.added_at IS NOT NULL
        ORDER BY e.added_at DESC
    """)
    rows = c.fetchall()
    cutoff = datetime.now().timestamp() - hours * 3600
    return [r for r in rows if r[2] and r[2] >= cutoff]

@_db_locked
def get_recent_episode_counts(hours=36):
    """So'nggi `hours` soat ichida har bir anime/fasl uchun qancha qism qo'shilganini qaytaradi.
    Natija: [(anime_code, anime_name, season_num, qo'shilgan_soni, jami_e'lon_qilingan_qismlar, label), ...]"""
    recent = get_recent_episodes(hours)
    counts = {}
    for anime_code, ep_num, added_at, name, season_num in recent:
        key = (anime_code, season_num)
        if key not in counts:
            counts[key] = {"name": name, "count": 0}
        counts[key]["count"] += 1
    result = []
    for (code, season_num), info in counts.items():
        season = get_season(code, season_num)
        total_ep = season[3] if season else 0
        ep_label = season[5] if season and len(season) > 5 else None
        result.append((code, info["name"], season_num, info["count"], total_ep, ep_label))
    return result

@_db_locked
def get_anime_by_code(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM animes WHERE code=?", (code,))
    result = c.fetchone()
    return result

@_db_locked
def get_anime_list_summary():
    """Barcha animelar, fasllar va yuklangan qismlar sonini atigi 3 ta SQL so'rov bilan
    qaytaradi (har bir anime/fasl uchun alohida so'rov ochish o'rniga)."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name, channel_post_count FROM animes ORDER BY id")
    animes = c.fetchall()

    c.execute("SELECT id, anime_code, season_num, total_episodes, total_episodes_label FROM seasons ORDER BY anime_code, season_num")
    seasons_by_anime = {}
    for sid, anime_code, snum, s_total, s_label in c.fetchall():
        seasons_by_anime.setdefault(anime_code, []).append((sid, snum, s_total, s_label))

    c.execute("SELECT season_id, COUNT(*) FROM episodes GROUP BY season_id")
    ep_counts = {sid: cnt for sid, cnt in c.fetchall()}

    return animes, seasons_by_anime, ep_counts

@_db_locked
def get_all_animes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name, year, genre, total_episodes FROM animes ORDER BY id")
    result = c.fetchall()
    return result

@_db_locked
def get_recent_animes(hours=48):
    """So'nggi `hours` soat ichida qo'shilgan animelarni qaytaradi (added_at bo'yicha,
    eng yangisi birinchi). Eski (added_at=NULL yoki muddati o'tgan) animeler kirmaydi —
    ular bot ichida kod orqali ishlashda davom etadi, faqat bu ro'yxatlarda ko'rinmaydi."""
    conn = get_db()
    c = conn.cursor()
    cutoff = datetime.now().timestamp() - hours * 3600
    c.execute(
        "SELECT code, name, year, genre, total_episodes FROM animes "
        "WHERE added_at IS NOT NULL AND added_at >= ? ORDER BY added_at ASC",
        (cutoff,)
    )
    return c.fetchall()

def _name_similarity(query, title):
    """So'rov bilan nom (yoki nomdagi alohida so'zlar) orasidagi o'xshashlik (0..1)."""
    title = (title or "").lower().strip()
    if not title:
        return 0.0
    best = difflib.SequenceMatcher(None, query, title).ratio()
    for word in re.split(r"[\s\-_:;,.!?()]+", title):
        if len(word) >= 4:
            best = max(best, difflib.SequenceMatcher(None, query, word).ratio())
    return best

@_db_locked
def suggest_animes_by_name(name, limit=3, cutoff=0.65):
    """Imlo xatosi bilan yozilgan nomga eng o'xshash animelarni qaytaradi: [(code, name), ...]."""
    query = (name or "").lower().strip()
    if len(query) < 4:
        return []
    conn = get_db()
    rows = conn.execute("SELECT code, name FROM animes").fetchall()
    scored = []
    for code, title in rows:
        score = _name_similarity(query, title)
        if score >= cutoff:
            scored.append((score, code, title))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(code, title) for _, code, title in scored[:limit]]

@_db_locked
def find_animes_by_name(name):
    """Nomi bo'yicha (harf katta-kichikligiga qaramasdan) o'xshash animelarni topadi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name FROM animes WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
    result = c.fetchall()
    return result

@_db_locked
def increment_channel_post_count(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE animes SET channel_post_count = COALESCE(channel_post_count, 0) + 1 WHERE code=?", (code,))
    conn.commit()

@_db_locked
def get_channel_post_count(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT channel_post_count FROM animes WHERE code=?", (code,))
    row = c.fetchone()
    return row[0] if row and row[0] else 0

# -- FASLLAR (SEASONS) --
@_db_locked
def add_season(anime_code, season_num, poster_file_id, total_episodes, poster_type="photo", total_episodes_label=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO seasons "
        "(anime_code, season_num, poster_file_id, total_episodes, added_date, poster_type, total_episodes_label) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(anime_code, season_num) DO UPDATE SET "
        "poster_file_id=COALESCE(NULLIF(excluded.poster_file_id, ''), seasons.poster_file_id), "
        "total_episodes=COALESCE(excluded.total_episodes, seasons.total_episodes), "
        "poster_type=COALESCE(NULLIF(excluded.poster_type, ''), seasons.poster_type), "
        "total_episodes_label=COALESCE(NULLIF(excluded.total_episodes_label, ''), seasons.total_episodes_label)",
        (anime_code, season_num, poster_file_id, total_episodes, datetime.now().strftime("%Y-%m-%d"), poster_type, total_episodes_label)
    )
    conn.commit()
    c.execute(
        "SELECT id FROM seasons WHERE anime_code=? AND season_num=?",
        (anime_code, season_num),
    )
    return c.fetchone()[0]

@_db_locked
def update_season_total_episodes(season_id, total_episodes, total_episodes_label=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE seasons SET total_episodes=?, total_episodes_label=? WHERE id=?", (total_episodes, total_episodes_label, season_id))
    conn.commit()

@_db_locked
def update_season_poster(season_id, poster_file_id, poster_type="photo"):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE seasons SET poster_file_id=?, poster_type=? WHERE id=?", (poster_file_id, poster_type, season_id))
    conn.commit()

@_db_locked
def update_anime_poster(code, poster_file_id):
    """Fasli yo'q (eski) anime uchun asosiy posterni almashtiradi."""
    conn = get_db()
    conn.execute("UPDATE animes SET poster_file_id=? WHERE code=?", (poster_file_id, code))
    conn.commit()

@_db_locked
def set_anime_episode_cover(anime_code, poster_file_id):
    """Qismlar videosi uchun coverni alohida saqlaydi.
    Anime va fasllarning katta posterlariga tegmaydi."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE animes SET episode_thumb_file_id=? WHERE code=?",
        (poster_file_id, anime_code)
    )
    conn.commit()

@_db_locked
def get_anime_episode_cover(anime_code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT episode_thumb_file_id FROM animes WHERE code=?", (anime_code,))
    row = c.fetchone()
    return (row[0] if row and row[0] else None) or get_global_episode_cover()

def _ensure_season_cover_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(seasons)").fetchall()]
    if "episode_thumb_file_id" not in cols:
        conn.execute("ALTER TABLE seasons ADD COLUMN episode_thumb_file_id TEXT")

@_db_locked
def set_season_episode_cover(season_id, file_id):
    """Qism videolari coverini aynan shu fasl uchun saqlaydi (Telegram file_id)."""
    conn = get_db()
    _ensure_season_cover_column(conn)
    conn.execute("UPDATE seasons SET episode_thumb_file_id=? WHERE id=?", (file_id, season_id))
    conn.commit()

@_db_locked
def get_season_episode_cover(season_id):
    conn = get_db()
    _ensure_season_cover_column(conn)
    row = conn.execute("SELECT episode_thumb_file_id FROM seasons WHERE id=?", (season_id,)).fetchone()
    return (row[0] if row and row[0] else None) or get_global_episode_cover()

@_db_locked
def get_global_episode_cover():
    """Barcha qism videolari uchun umumiy cover (bo'lmasa None)."""
    conn = get_db()
    row = conn.execute("SELECT value FROM app_meta WHERE key='global_episode_cover'").fetchone()
    return (row[0] or None) if row else None

@_db_locked
def apply_global_episode_cover(file_id):
    """Umumiy coverni saqlaydi va mavjud barcha anime/fasllarga bir tranzaksiyada qo'yadi."""
    conn = get_db()
    _ensure_season_cover_column(conn)
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('global_episode_cover', ?)", (file_id,))
    animes_count = conn.execute("UPDATE animes SET episode_thumb_file_id=?", (file_id,)).rowcount
    seasons_count = conn.execute("UPDATE seasons SET episode_thumb_file_id=?", (file_id,)).rowcount
    conn.commit()
    return animes_count, seasons_count

@_db_locked
def clear_global_episode_cover():
    conn = get_db()
    conn.execute("DELETE FROM app_meta WHERE key='global_episode_cover'")
    conn.commit()

@_db_locked
def get_next_free_episode_num(season_id):
    """Fasldagi eng kichik bo'sh qism raqamini qaytaradi (o'chirilgan raqamlar ham to'ldiriladi)."""
    conn = get_db()
    rows = conn.execute("SELECT episode_num FROM episodes WHERE season_id=?", (season_id,)).fetchall()
    used = {r[0] for r in rows}
    num = 1
    while num in used:
        num += 1
    return num

@_db_locked
def delete_episodes(season_id, episode_nums):
    """Fasldagi tanlangan qismlarni o'chiradi. Qolgan qismlar raqami o'zgarmaydi."""
    conn = get_db()
    count = 0
    for num in episode_nums:
        cur = conn.execute("DELETE FROM episodes WHERE season_id=? AND episode_num=?", (season_id, num))
        count += cur.rowcount
    conn.commit()
    return count

@_db_locked
def delete_season_episodes(season_id):
    """Fasldagi barcha qismlarni o'chiradi (faslning o'zi va coveri qoladi)."""
    conn = get_db()
    cur = conn.execute("DELETE FROM episodes WHERE season_id=?", (season_id,))
    conn.commit()
    return cur.rowcount

@_db_locked
def delete_anime_episodes(anime_code):
    """Anime bo'yicha barcha fasllardagi barcha qismlarni o'chiradi (fasllar qoladi)."""
    conn = get_db()
    cur = conn.execute(
        "DELETE FROM episodes WHERE season_id IN (SELECT id FROM seasons WHERE anime_code=?)",
        (anime_code,)
    )
    conn.commit()
    return cur.rowcount

@_db_locked
def get_anime_main_poster(anime_code):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT poster_file_id, COALESCE(poster_type, 'photo') FROM animes WHERE code=?",
        (anime_code,)
    )
    return c.fetchone()

@_db_locked
def get_seasons(anime_code):
    """Berilgan anime uchun barcha fasllarni qaytaradi:
    [(id, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label), ...]"""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label FROM seasons WHERE anime_code=? ORDER BY season_num",
        (anime_code,)
    )
    result = c.fetchall()
    return result

@_db_locked
def get_season(anime_code, season_num):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label FROM seasons WHERE anime_code=? AND season_num=?",
        (anime_code, season_num)
    )
    result = c.fetchone()
    return result

@_db_locked
def get_season_by_id(season_id):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, anime_code, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label FROM seasons WHERE id=?",
        (season_id,)
    )
    result = c.fetchone()
    return result

@_db_locked
def get_episode(season_id, episode_num):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT video_file_id FROM episodes WHERE season_id=? AND episode_num=?",
              (season_id, episode_num))
    result = c.fetchone()
    return result

@_db_locked
def get_episodes_list(season_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT episode_num FROM episodes WHERE season_id=? ORDER BY episode_num",
              (season_id,))
    result = c.fetchall()
    return [r[0] for r in result]

@_db_locked
def delete_anime(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM seasons WHERE anime_code=?", (code,))
    season_ids = [r[0] for r in c.fetchall()]
    for sid in season_ids:
        c.execute("DELETE FROM episodes WHERE season_id=?", (sid,))
    c.execute("DELETE FROM seasons WHERE anime_code=?", (code,))
    # episodes.anime_code eski schema'da animes(code) ga foreign key bo'lgani
    # uchun anime qatori eng oxirida o'chiriladi.
    c.execute("DELETE FROM episodes WHERE anime_code=?", (code,))
    c.execute("DELETE FROM animes WHERE code=?", (code,))
    conn.commit()

@_db_locked
def delete_episode(season_id, episode_num):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM episodes WHERE season_id=? AND episode_num=?", (season_id, episode_num))
    conn.commit()

@_db_locked
def update_episode_number(season_id, old_num, new_num):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE episodes SET episode_num=? WHERE season_id=? AND episode_num=?",
        (new_num, season_id, old_num)
    )
    conn.commit()

@_db_locked
def get_monthly_stats():
    conn = get_db()
    c = conn.cursor()
    month = datetime.now().strftime("%Y-%m")
    c.execute("SELECT COUNT(*) FROM animes WHERE added_date LIKE ?", (f"{month}%",))
    animes_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users")
    users_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM animes")
    total_animes = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM episodes")
    total_episodes = c.fetchone()[0]
    return animes_count, users_count, total_animes, total_episodes

@_db_locked
def _ensure_view_count_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(animes)").fetchall()]
    if "view_count" not in cols:
        conn.execute("ALTER TABLE animes ADD COLUMN view_count INTEGER DEFAULT 0")

@_db_locked
def get_anime_view_count(anime_code):
    conn = get_db()
    _ensure_view_count_column(conn)
    row = conn.execute("SELECT COALESCE(view_count, 0) FROM animes WHERE code=?", (anime_code,)).fetchone()
    return row[0] if row else 0

@_db_locked
def log_activity(event_type, anime_code, user_id):
    """Anime ko'rish yoki qism so'rashni yozib qo'yadi. Adminlar hisoblanmaydi —
    bu funksiyani chaqirishdan oldin chaqiruvchi tomonda is_admin() tekshirilishi kerak."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO activity_log (event_type, anime_code, user_id, created_at) VALUES (?, ?, ?, ?)",
        (event_type, anime_code, user_id, datetime.now().timestamp())
    )
    if event_type == "anime_view" and anime_code is not None:
        # Qidirishlar hisoblagichi: shu tranzaksiyada, qo'shimcha disk yozuvisiz.
        _ensure_view_count_column(conn)
        conn.execute("UPDATE animes SET view_count = COALESCE(view_count, 0) + 1 WHERE code=?", (anime_code,))
    conn.commit()

@_db_locked
def get_request_stats():
    """(jami_qism_sorovlari, bu_oy_qism_sorovlari, jami_anime_sorovlari) qaytaradi."""
    conn = get_db()
    c = conn.cursor()
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

    c.execute("SELECT COUNT(*) FROM activity_log WHERE event_type='episode_request'")
    total_episode_requests = c.fetchone()[0]

    c.execute(
        "SELECT COUNT(*) FROM activity_log WHERE event_type='episode_request' AND created_at >= ?",
        (month_start,)
    )
    month_episode_requests = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM activity_log WHERE event_type='anime_view'")
    total_anime_requests = c.fetchone()[0]

    return total_episode_requests, month_episode_requests, total_anime_requests

_growth_cache = {"time": 0.0, "data": None}

@_db_locked
def get_growth_stats():
    """Bu oy va o'tgan oy bo'yicha: yangi foydalanuvchilar, faol foydalanuvchilar, kuzatuvlar.
    Natija 5 daqiqa keshlanadi (statistika tez-tez ochilsa bazani yuklamaslik uchun)."""
    now_ts = time.monotonic()
    if _growth_cache["data"] is not None and now_ts - _growth_cache["time"] < 300:
        return _growth_cache["data"]
    conn = get_db()
    _ensure_watch_table(conn)
    now = datetime.now()
    this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_start = (this_start - timedelta(days=1)).replace(day=1)

    def count_users(start, end):
        row = conn.execute(
            "SELECT COUNT(*) FROM users WHERE joined_date >= ? AND joined_date < ?",
            (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        ).fetchone()
        return row[0]

    def count_active(start, end):
        row = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM activity_log "
            "WHERE event_type IN ('anime_view', 'episode_request') AND created_at >= ? AND created_at < ?",
            (start.timestamp(), end.timestamp())
        ).fetchone()
        return row[0]

    def count_watches(start, end):
        row = conn.execute(
            "SELECT COUNT(*) FROM anime_watch WHERE created_at >= ? AND created_at < ?",
            (start.isoformat(), end.isoformat())
        ).fetchone()
        return row[0]

    far_future = now + timedelta(days=1)
    total_watchers, total_watches = conn.execute(
        "SELECT COUNT(DISTINCT user_id), COUNT(*) FROM anime_watch"
    ).fetchone()
    top_watched = conn.execute(
        "SELECT a.name, COUNT(*) AS c FROM anime_watch w JOIN animes a ON a.code = w.anime_code "
        "GROUP BY w.anime_code ORDER BY c DESC, a.name LIMIT 5"
    ).fetchall()
    data = {
        "new_users": (count_users(this_start, far_future), count_users(last_start, this_start)),
        "active_users": (count_active(this_start, far_future), count_active(last_start, this_start)),
        "new_watches": (count_watches(this_start, far_future), count_watches(last_start, this_start)),
        "total_watchers": total_watchers,
        "total_watches": total_watches,
        "top_watched": top_watched,
    }
    _growth_cache["time"] = now_ts
    _growth_cache["data"] = data
    return data

def _percent_change_text(current, previous):
    """Oldingi oyga nisbatan o'zgarish: '📈 +26%', '📉 -17%' yoki '➖ 0%'."""
    if previous == 0:
        return "🆕 yangi" if current > 0 else "➖ 0%"
    pct = round((current - previous) / previous * 100)
    if pct > 0:
        return f"📈 +{pct}%"
    if pct < 0:
        return f"📉 {pct}%"
    return "➖ 0%"

@_db_locked
def get_top_animes(limit=10):
    """Eng ko'p SO'RALGAN (faqat anime_view — anime ko'rish/qidirish) animelar
    ro'yxatini qaytaradi: [(name, code, count), ...]. Qism tanlash bu yerga kirmaydi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT a.name, a.code, COUNT(*) as cnt
        FROM activity_log al
        JOIN animes a ON a.code = al.anime_code
        WHERE al.event_type = 'anime_view'
        GROUP BY al.anime_code
        ORDER BY cnt DESC
        LIMIT ?
    """, (limit,))
    return c.fetchall()

@_db_locked
def get_animes_by_genre(genre, limit=30):
    """Berilgan janr nomiga mos animelarni qaytaradi: [(code, name), ...]."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT code, name FROM animes WHERE genre LIKE ? ORDER BY id DESC LIMIT ?",
        (f"%{genre}%", limit)
    )
    return c.fetchall()

@_db_locked
def get_top_rated_animes(limit=10):
    """Reytingi belgilangan animelarni yuqoridan pastga qaytaradi: [(code, name, rating), ...]."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT code, name, rating FROM animes WHERE rating IS NOT NULL ORDER BY rating DESC LIMIT ?",
        (limit,)
    )
    return c.fetchall()

@_db_locked
def get_latest_animes(limit=10):
    """Eng oxirgi qo'shilgan animelarni qaytaradi: [(code, name), ...]."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT code, name FROM animes WHERE added_at IS NOT NULL ORDER BY added_at DESC LIMIT ?",
        (limit,)
    )
    return c.fetchall()

@_db_locked
def get_bot_setting(key, default=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM app_meta WHERE key=?", (key,))
    row = c.fetchone()
    return row[0] if row else default

@_db_locked
def set_bot_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    conn.commit()

@_db_locked
def delete_bot_setting(key):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM app_meta WHERE key=?", (key,))
    conn.commit()

def _instagram_link():
    """Instagram havolasi faqat tugma sifatida ko'rsatiladi.

    Instagram obunasini Telegram Bot API orqali tekshirib bo'lmaydi, shuning
    uchun bu sozlama foydalanuvchini bloklamaydi.
    """
    return (get_bot_setting("instagram_link", "") or "").strip()

def _auto_backup_channel():
    return (get_bot_setting("auto_backup_channel", "") or "").strip()

def _auto_backup_channel_title():
    return (get_bot_setting("auto_backup_channel_title", "") or "").strip()

def _auto_backup_times():
    raw = (get_bot_setting("auto_backup_times", "") or "").strip()
    return [item for item in raw.split(",") if re.fullmatch(r"\d{2}:\d{2}", item)]

def _auto_backup_enabled():
    return get_bot_setting("auto_backup_enabled", "0") == "1"

def _subscription_keyboard(not_joined):
    """Telegram obunasi tugmalari va tekshirilmaydigan Instagram linki."""
    buttons = [
        [InlineKeyboardButton(f"📢 {title} ga Obuna Bo'lish", url=link, style="success")]
        for title, link in not_joined
    ]
    instagram = _instagram_link()
    if instagram:
        buttons.append([
            InlineKeyboardButton("📸 Instagramga obuna bo'lish", url=instagram, style="success")
        ])
    if not_joined:
        buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub", style="primary")])
    return InlineKeyboardMarkup(buttons)

@_db_locked
def add_required_channel(identifier, link, title=None, expires_at=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO required_channels (username, link, title, expires_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(username) DO UPDATE SET link=excluded.link, title=excluded.title, expires_at=excluded.expires_at",
        (identifier, link, title, expires_at)
    )
    conn.commit()

@_db_locked
def remove_required_channel(identifier):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE username=?", (identifier,))
    conn.commit()

@_db_locked
def cleanup_expired_channels():
    """Muddati o'tgan (1 hafta/15 kun/30 kun) kanallarni majburiy obuna ro'yxatidan avtomatik olib tashlaydi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE expires_at IS NOT NULL AND expires_at <= ?", (datetime.now().isoformat(),))
    conn.commit()

@_db_locked
def get_required_channels():
    cleanup_expired_channels()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, link, title, expires_at FROM required_channels")
    result = c.fetchall()
    return result

def _ensure_users_active_column(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "is_active" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")

@_db_locked
def register_user(user_id, username):
    conn = get_db()
    _ensure_users_active_column(conn)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (id, username, joined_date)
        VALUES (?, ?, ?)
    """, (user_id, username or "", datetime.now().strftime("%Y-%m-%d")))
    # Foydalanuvchi botga qaytib /start bossa, yana faol hisoblanadi.
    c.execute("UPDATE users SET is_active=1 WHERE id=? AND is_active=0", (user_id,))
    conn.commit()

def _ensure_watch_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS anime_watch (
            user_id INTEGER NOT NULL,
            anime_code INTEGER NOT NULL,
            created_at TEXT,
            PRIMARY KEY (user_id, anime_code)
        )
    """)

@_db_locked
def is_watching(user_id, anime_code):
    conn = get_db()
    _ensure_watch_table(conn)
    row = conn.execute(
        "SELECT 1 FROM anime_watch WHERE user_id=? AND anime_code=?", (user_id, anime_code)
    ).fetchone()
    return row is not None

@_db_locked
def add_watch(user_id, anime_code):
    conn = get_db()
    _ensure_watch_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO anime_watch (user_id, anime_code, created_at) VALUES (?, ?, ?)",
        (user_id, anime_code, datetime.now().isoformat())
    )
    conn.commit()

@_db_locked
def remove_watch(user_id, anime_code):
    conn = get_db()
    _ensure_watch_table(conn)
    conn.execute("DELETE FROM anime_watch WHERE user_id=? AND anime_code=?", (user_id, anime_code))
    conn.commit()

@_db_locked
def get_watchers(anime_code):
    """Animeni kuzatayotgan faol (botni bloklamagan) foydalanuvchilar."""
    conn = get_db()
    _ensure_watch_table(conn)
    _ensure_users_active_column(conn)
    rows = conn.execute(
        "SELECT w.user_id FROM anime_watch w LEFT JOIN users u ON u.id = w.user_id "
        "WHERE w.anime_code=? AND (u.is_active IS NULL OR u.is_active != 0)",
        (anime_code,)
    ).fetchall()
    return [r[0] for r in rows]

@_db_locked
def get_broadcast_users():
    """Xabar yuboriladigan faol foydalanuvchilar (botni bloklamaganlar)."""
    conn = get_db()
    _ensure_users_active_column(conn)
    rows = conn.execute("SELECT id FROM users WHERE is_active IS NULL OR is_active != 0").fetchall()
    return [r[0] for r in rows]

@_db_locked
def set_user_active(user_id, active):
    conn = get_db()
    _ensure_users_active_column(conn)
    conn.execute("UPDATE users SET is_active=? WHERE id=?", (1 if active else 0, user_id))
    conn.commit()

@_db_locked
def get_all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    rows = c.fetchall()
    return [r[0] for r in rows]

@_db_locked
def add_admin(user_id, added_by):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)",
        (user_id, added_by, datetime.now().strftime("%Y-%m-%d"))
    )
    conn.commit()

@_db_locked
def remove_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()

@_db_locked
def get_all_admins():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, added_date FROM admins")
    rows = c.fetchall()
    return rows

@_db_locked
def is_admin(user_id):
    """Asosiy admin yoki qo'shilgan sub-admin bo'lsa True qaytaradi."""
    if user_id == ADMIN_ID:
        return True
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    result = c.fetchone()
    return result is not None

def is_primary_admin(user_id):
    """Faqat bot egasi (asosiy admin) uchun mo'ljallangan amallar."""
    return user_id == ADMIN_ID

# ==================== HELPERS ====================
@_db_locked
def has_pending_join_request(chat_id_str, user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM join_requests WHERE chat_id=? AND user_id=?", (chat_id_str, user_id))
    return c.fetchone() is not None

async def record_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yopiq kanalga yuborilgan qo'shilish so'rovini FAQAT yozib qo'yadi (tasdiqlamaydi) —
    admin so'rovlarni Telegram'ning o'zidan qo'lda tasdiqlaydi. Bot esa 'so'rov yuborilganini'
    obuna talabini qondirish uchun yetarli deb hisoblaydi."""
    req = update.chat_join_request
    with _DB_LOCK:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO join_requests (chat_id, user_id, requested_at) VALUES (?, ?, ?)",
            (str(req.chat.id), req.from_user.id, datetime.now().isoformat())
        )
        conn.commit()

async def check_subscription(user_id, context):
    channels = get_required_channels()
    if not channels:
        channels = [(CHANNEL_USERNAME, CHANNEL_LINK, None, None)]
    not_joined = []
    for identifier, link, title, expires_at in channels:
        # Yopiq kanallar uchun identifier manfiy raqamli chat_id ("-100...") ko'rinishida saqlanadi
        chat_ref = int(identifier) if identifier.lstrip("-").isdigit() else identifier
        label = title or identifier
        try:
            member = await context.bot.get_chat_member(chat_ref, user_id)
            logger.info(f"[OBUNA-TEKSHIRUV] user_id={user_id} kanal={identifier} status={member.status!r}")
            if member.status not in ["member", "administrator", "creator"]:
                # A'zo emas — lekin qo'shilish so'rovi yuborgan bo'lsa, shuni yetarli deb hisoblaymiz
                # (admin so'rovni Telegram'ning o'zidan o'z vaqtida qo'lda tasdiqlaydi)
                if not has_pending_join_request(str(chat_ref), user_id):
                    not_joined.append((label, link))
        except Exception as e:
            logger.info(f"[OBUNA-TEKSHIRUV] user_id={user_id} kanal={identifier} XATO: {e!r}")
            if not has_pending_join_request(str(chat_ref), user_id):
                not_joined.append((label, link))
    return not_joined

def parse_channel_link(text):
    """Foydalanuvchi yuborgan matnni kanal havolasi sifatida tahlil qiladi.
    Qaytaradi: ("public", username) ochiq kanal uchun, yoki ("private", havola) yopiq kanal uchun.
    Noto'g'ri formatda bo'lsa None qaytaradi."""
    text = text.strip()
    if text.startswith("@"):
        uname = text[1:]
        if re.fullmatch(r"[A-Za-z0-9_]{4,}", uname):
            return ("public", uname)
        return None
    m = re.match(r"(?:https?://)?t\.me/(.+)", text, re.I)
    if not m:
        return None
    path = m.group(1).strip()
    if path.startswith("+") or path.startswith("joinchat/"):
        full_link = text if text.lower().startswith("http") else f"https://t.me/{path}"
        return ("private", full_link)
    uname = path.split("?")[0].strip("/")
    if re.fullmatch(r"[A-Za-z0-9_]{4,}", uname):
        return ("public", uname)
    return None

def _esc_md(text):
    """Foydalanuvchi kiritgan matnda Markdown maxsus belgilari bo'lsa,
    Telegram xabarni yubormay qolib ketishining oldini olish uchun ekranlaydi."""
    if text is None:
        return ""
    text = str(text)
    for ch in ("\\", "_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text

def _parse_episode_count(text):
    """Qism soni maydoniga so'z bilan yozilgan matnni ham qabul qiladi
    (masalan '24 qism 2-fasl'). Ichki hisob-kitob uchun birinchi topilgan
    raqamni ajratib oladi, ko'rsatish uchun esa yozilgan matnning o'zini saqlaydi."""
    text = text.strip()
    match = re.search(r"\d+", text)
    number = int(match.group()) if match else 0
    return number, text

def _episode_label(total_episodes, label):
    """Ko'rsatish uchun: agar admin so'z bilan yozgan bo'lsa o'shani, aks holda sonni qaytaradi."""
    if label:
        return label
    return str(total_episodes)

def _season_label(season_num, total_episodes):
    """Agar faslda jami 1 ta qism bo'lsa (film), 'N-fasl' o'rniga 'Film' deb ko'rsatadi."""
    if total_episodes == 1:
        return "🎬 Film"
    return f"{season_num}-fasl"

def main_menu_keyboard():
    # style='primary' — ko'k rang (Bot API 9.4+; eski Telegram ilovalarida rangsiz ko'rinadi)
    keyboard = [
        [KeyboardButton("🔍 Anime Izlash", style="primary")],
        [KeyboardButton("📖 Qo'llanma", style="primary"), KeyboardButton("📢 Reklama", style="primary")],
        [KeyboardButton("📺 Animelar Kanali", style="primary")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_menu_keyboard(user_id=None):
    keyboard = [
        [KeyboardButton("➕ Anime Qo'shish"), KeyboardButton("📺 Qism Qo'shish")],
        [KeyboardButton("📋 Animeler Ro'yxati"), KeyboardButton("📊 Statistika")],
        [KeyboardButton("🗑 Anime O'chirish"), KeyboardButton("✏️ Anime Tahrirlash")],
        [KeyboardButton("📤 Kanalga Yuborish"), KeyboardButton("🆕 Yangi Qismlar")],
        [KeyboardButton("🛠 Qism Boshqarish")],
        [KeyboardButton("🏷 Anime Holati")],
        [KeyboardButton("📊 So'rovnomalar"), KeyboardButton("⚙️ Bot Sozlamalari")],
    ]
    keyboard.append([KeyboardButton("🔙 Asosiy Menu")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def episodes_keyboard(season_id, page=0, user_id=None):
    episodes = get_episodes_list(season_id)
    per_page = 24
    start = page * per_page
    end = start + per_page
    page_episodes = episodes[start:end]
    total_pages = (len(episodes) - 1) // per_page + 1 if episodes else 1

    buttons = []
    row = []
    for i, ep in enumerate(page_episodes):
        row.append(InlineKeyboardButton(str(ep), callback_data=f"ep_{season_id}_{ep}"))
        if len(row) == 6:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⏮", callback_data=f"page_{season_id}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if end < len(episodes):
        nav.append(InlineKeyboardButton("⏭", callback_data=f"page_{season_id}_{page+1}"))
    if nav:
        buttons.append(nav)

    if episodes and is_admin(user_id):
        buttons.append([
            InlineKeyboardButton(
                f"📥 Barcha qismlarni yuklash (1-{len(episodes)})",
                callback_data=f"all_eps_{season_id}",
            )
        ])

    if user_id is not None:
        season_row = get_season_by_id(season_id)
        if season_row:
            watch_code = season_row[1]
            buttons.append([
                InlineKeyboardButton(
                    _watch_button_label(is_watching(user_id, watch_code)),
                    callback_data=f"watch_{watch_code}",
                )
            ])

    return InlineKeyboardMarkup(buttons)

def _watch_button_label(watching):
    return "🔕 Kuzatuvni bekor qilish" if watching else "🔔 Yangi qism chiqsa xabar bering"

def genre_select_keyboard(selected):
    """selected — tanlangan janr indexlari to'plami"""
    buttons = []
    row = []
    for i, g in enumerate(GENRE_LIST):
        label = f"✅ {g}" if i in selected else g
        row.append(InlineKeyboardButton(label, callback_data=f"gsel_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(f"➡️ Tasdiqlash ({len(selected)} ta tanlandi)", callback_data="gconfirm")])
    buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")])
    return InlineKeyboardMarkup(buttons)

def anime_search_menu_keyboard():
    """'🔍 Anime Izlash' bosilganda chiqadigan qidiruv usullari menyusi.
    style='primary' — ko'k, style='danger' — qizil (Bot API 9.4+, PTB 22.7+ talab qiladi;
    eskiroq Telegram ilovalarida ranglar ko'rinmaydi, lekin tugmalar baribir ishlayveradi)."""
    buttons = [
        [InlineKeyboardButton("🔢 Kod orqali izlash", callback_data="srchmenu_code", style="primary")],
        [InlineKeyboardButton("🔤 Nom orqali izlash", callback_data="srchmenu_name", style="primary")],
        [
            InlineKeyboardButton("🎭 Janr orqali izlash", callback_data="srchmenu_genre", style="primary"),
            InlineKeyboardButton("🆕 So'ngi yuklanganlar", callback_data="srchmenu_recent", style="primary"),
        ],
        [
            InlineKeyboardButton("⭐ Reytingi baland", callback_data="srchmenu_rating", style="primary"),
            InlineKeyboardButton("👁 Ko'p ko'rilgan", callback_data="srchmenu_views", style="primary"),
        ],
        [
            InlineKeyboardButton("📚 Barcha animelar", callback_data="srchmenu_all", style="primary"),
            InlineKeyboardButton("📋 Animelar ro'yxati", url=CHANNEL_LINK, style="primary"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="srchmenu_close", style="danger")],
    ]
    return InlineKeyboardMarkup(buttons)

def search_genre_keyboard():
    """Qidiruv uchun janrlarni bitta bosishda tanlash klaviaturasi."""
    buttons = []
    row = []
    for i, g in enumerate(GENRE_LIST):
        row.append(InlineKeyboardButton(g, callback_data=f"srchgnr_{i}", style="primary"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="srchmenu_root", style="danger")])
    return InlineKeyboardMarkup(buttons)

def _srch_results_keyboard(items, back_callback="srchmenu_root"):
    """items — [(code, label), ...] ro'yxatidan bosiladigan natija tugmalarini yaratadi."""
    buttons = [[InlineKeyboardButton(label, callback_data=f"srch_{code}", style="primary")] for code, label in items]
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data=back_callback, style="danger")])
    return InlineKeyboardMarkup(buttons)

async def _send_poster_or_text(
    bot,
    chat_id,
    caption,
    poster_id,
    poster_type="photo",
    reply_markup=None,
    log_context="",
):
    """Yaroqsiz Telegram file_id botni to'xtatib qo'ymasligi uchun fallback."""
    if not poster_id:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return

    media_kwarg = "video" if poster_type == "video" else "photo"
    send_fn = bot.send_video if poster_type == "video" else bot.send_photo
    try:
        await send_fn(
            chat_id=chat_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            **{media_kwarg: poster_id},
        )
    except Exception as e:
        logger.warning("Media yuborilmadi%s: %s", f" ({log_context})" if log_context else "", e)
        fallback_text = (
            f"{caption}\n\n"
            "⚠️ Poster fayli topilmadi, lekin anime ma'lumotlari saqlandi."
        )
        await bot.send_message(
            chat_id=chat_id,
            text=fallback_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )

async def _send_season_info(bot, chat_id, name, genre, desc, season_id, poster_id, total_ep, season_num=None, show_season_label=False, poster_type="photo", ep_label=None, status_key=None, anime_code=None):
    episodes = get_episodes_list(season_id) if season_id else []
    title = f"🎬 *{_esc_md(name)}*"
    if show_season_label and season_num:
        title += f" — {_season_label(season_num, total_ep)}"
    ep_count_display = _episode_label(total_ep, ep_label)
    status_line = f"🏷 Holati: {ANIME_STATUSES[status_key]}\n" if status_key in ANIME_STATUSES else ""
    code_line = f"🆔 Anime kodi: {anime_code}\n" if anime_code is not None else ""
    views_line = f"🔍 Qidirishlar soni: {get_anime_view_count(anime_code)}\n" if anime_code is not None else ""
    caption = (
        f"{title}\n\n"
        f"{status_line}"
        f"{code_line}"
        f"🎭 Janr: {genre}\n"
        f"📺 Jami qismlar: {ep_count_display} ta\n"
        f"✅ Yuklangan: {len(episodes)} ta\n"
        f"{views_line}\n"
        f"👇 Qismni tanlang:"
    )
    if desc:
        caption = caption.replace("👇 Qismni tanlang:", f"📝 {_esc_md(desc)}\n\n👇 Qismni tanlang:")

    if not poster_id:
        await bot.send_message(
            chat_id=chat_id, text=caption, parse_mode="Markdown",
            reply_markup=episodes_keyboard(season_id, user_id=chat_id) if episodes else None
        )
        return

    reply_markup = episodes_keyboard(season_id, user_id=chat_id) if episodes else None
    final_caption = caption if episodes else caption + "\n\n⚠️ Hali qism yuklanmagan!"
    await _send_poster_or_text(
        bot,
        chat_id,
        final_caption,
        poster_id,
        poster_type=poster_type,
        reply_markup=reply_markup,
        log_context=f"anime={name}, season={season_num or '-'}",
    )

async def _send_anime_info_core(bot, chat_id, code):
    """Anime kodini kanal deep-link orqali yoki qo'lda yozilganda ko'rsatish uchun umumiy funksiya."""
    anime = get_anime_by_code(code)
    if not anime:
        await bot.send_message(chat_id=chat_id, text="❌ Bunday kodli anime topilmadi!")
        return
    if not is_admin(chat_id):  # shaxsiy chatda chat_id == foydalanuvchi id
        log_activity("anime_view", code, chat_id)
    _, code, name, year, genre, total_ep, desc, poster_id, added_date, *_rest = anime
    status_key = get_anime_status(code)
    seasons = get_seasons(code)

    if not seasons:
        # eski/fasl yaratilmagan holat uchun zaxira yo'l
        await _send_season_info(
            bot, chat_id, name, genre, desc, None, poster_id, total_ep,
            status_key=status_key, anime_code=code
        )
        return

    if len(seasons) == 1:
        sid, snum, s_poster, s_total, s_ptype, s_label = seasons[0]
        await _send_season_info(
            bot, chat_id, name, genre, desc, sid, s_poster, s_total,
            season_num=snum, show_season_label=False, poster_type=s_ptype, ep_label=s_label,
            status_key=status_key, anime_code=code
        )
        return

    # bir nechta fasl bor — tanlash ro'yxatini ko'rsatish
    buttons = []
    for sid, snum, s_poster, s_total, s_ptype, s_label in seasons:
        added = len(get_episodes_list(sid))
        label = _episode_label(s_total, s_label)
        buttons.append([InlineKeyboardButton(f"{_season_label(snum, total_ep)} ({added}/{label})", callback_data=f"showseason_{sid}")])
    await bot.send_message(
        chat_id=chat_id,
        text=f"🎬 *{_esc_md(name)}*\n🆔 Anime kodi: `{code}`\n\nQaysi faslni tomosha qilmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def send_season_direct(bot, chat_id, code, season_num):
    """Kanal postidagi aniq fasl havolasi: fasl tanlashni so'ramasdan shu faslni ochadi."""
    anime = get_anime_by_code(code)
    seasons = get_seasons(code)
    season = next((s for s in seasons if s[1] == season_num), None)
    if not anime or not season:
        await send_anime_info(bot, chat_id, code)
        return
    if not is_admin(chat_id):
        log_activity("anime_view", code, chat_id)
    sid, snum, s_poster, s_total, s_ptype, s_label = season
    await _send_season_info(
        bot, chat_id, anime[2], anime[4], anime[6], sid, s_poster, s_total,
        season_num=snum, show_season_label=len(seasons) > 1, poster_type=s_ptype, ep_label=s_label,
        status_key=get_anime_status(code), anime_code=code
    )

async def show_season_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    season_id = int(query.data[11:])
    season = get_season_by_id(season_id)
    if not season:
        await query.answer("❌ Bu fasl endi topilmadi.", show_alert=True)
        return
    _, anime_code, season_num, poster_id, total_ep, poster_type, ep_label = season
    anime = get_anime_by_code(anime_code)
    if not anime:
        return
    name, genre, desc = anime[2], anime[4], anime[6]
    status_key = get_anime_status(anime_code)
    await _send_season_info(
        context.bot, query.from_user.id, name, genre, desc,
        season_id, poster_id, total_ep, season_num=season_num, show_season_label=True,
        poster_type=poster_type, ep_label=ep_label, status_key=status_key,
        anime_code=anime_code
    )

async def post_anime_to_channel(context, code, name, genre, total_episodes, poster_id, poster_type="photo", ep_label=None, season_num=None):
    """Admin '📤 Kanalga Yuborish' tugmasi orqali bossagina kanalga poster + ma'lumot joylash."""
    # Havolada fasl raqami bo'lsa, foydalanuvchi fasl tanlamasdan to'g'ridan-to'g'ri shu faslga kiradi.
    start_param = f"{code}_{season_num}" if season_num is not None else f"{code}"
    watch_url = f"https://t.me/{BOT_USERNAME}?start={start_param}"
    ep_count_display = _episode_label(total_episodes, ep_label)
    caption = (
        f"🎬 {_esc_md(name)}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n\n"
        f"🎞 Qismi: {ep_count_display}\n"
        f"🎭 Janri: {genre}\n"
        f"🆔 Anime kodi: {code}\n"
        f"📢 Kanal: {CHANNEL_USERNAME}\n"
        f"➖➖➖➖➖➖➖➖➖➖\n\n"
        f"🔗 Yuklab olish: {watch_url}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Tomosha qilish", url=watch_url)]])
    try:
        if poster_type == "video":
            await context.bot.send_video(
                chat_id=CHANNEL_USERNAME, video=poster_id,
                caption=caption, reply_markup=kb
            )
        else:
            await context.bot.send_photo(
                chat_id=CHANNEL_USERNAME, photo=poster_id,
                caption=caption, reply_markup=kb
            )
        return True
    except Exception as e:
        logger.warning(f"Kanalga post yuborishda xato: {e}")
        return False

# ==================== HANDLERS ====================

async def require_subscription(update, context, pending_code=None):
    """Obunani faqat foydalanuvchi botdan haqiqatan foydalanmoqchi bo'lganda (kod yuborganda
    yoki anime linki orqali kirganda) tekshiradi. Admin uchun har doim True qaytaradi.
    Obuna bo'lmagan bo'lsa — tugmalarni ko'rsatib, False qaytaradi (chaqiruvchi to'xtashi kerak)."""
    user = update.effective_user
    if is_admin(user.id):
        return True
    not_joined = await check_subscription(user.id, context)
    if not not_joined:
        return True
    if pending_code is not None:
        context.user_data["pending_anime_code"] = pending_code
    await update.message.reply_text(
        "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
        reply_markup=_subscription_keyboard(not_joined)
    )
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    deep_code = None
    deep_season = None
    if context.args:
        arg = context.args[0]
        if arg.isdigit():
            deep_code = int(arg)
        else:
            code_part, _, season_part = arg.partition("_")
            if code_part.isdigit() and season_part.isdigit():
                deep_code = int(code_part)
                deep_season = int(season_part)

    # Obuna faqat anime kodi orqali (havola bilan) kirganda tekshiriladi —
    # oddiy /start da botning asosiy menyusi darhol ko'rsatiladi.
    if deep_code is not None:
        if deep_season is not None:
            context.user_data["pending_anime_season_for"] = (deep_code, deep_season)
        if not await require_subscription(update, context, pending_code=deep_code):
            return

    await send_start(update, context, deep_code, deep_season)

async def send_start(update, context, deep_code=None, deep_season=None):
    if deep_code is not None:
        if deep_season is not None:
            await send_season_direct(context.bot, update.effective_chat.id, deep_code, deep_season)
        else:
            await send_anime_info(context.bot, update.effective_chat.id, deep_code)
        return

    text = _bot_text_value("start")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(_start_button_value("search"), callback_data="anime_search", style="primary")],
        [InlineKeyboardButton(_start_button_value("cabinet"), callback_data="kabinet", style="success"), InlineKeyboardButton(_start_button_value("guide"), callback_data="guide", style="primary")],
        [InlineKeyboardButton(_start_button_value("channel"), url=CHANNEL_LINK, style="success"), InlineKeyboardButton(_start_button_value("ad"), callback_data="reklama", style="danger")],
    ])
    if _start_gif_enabled():
        await update.message.reply_animation(
            animation=_start_gif_file_id(),
            caption=text,
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(text, reply_markup=keyboard)

async def search_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = int(query.data.split("_")[1])
    user = query.from_user
    if not is_admin(user.id):
        not_joined = await check_subscription(user.id, context)
        if not_joined:
            context.user_data["pending_anime_code"] = code
            await query.message.reply_text(
                "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=_subscription_keyboard(not_joined)
            )
            return
    await send_anime_info(context.bot, query.from_user.id, code)

async def search_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'🔍 Anime Izlash' menyusidagi tugmalarni boshqaradi."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "srchmenu_root":
        await query.message.edit_text(
            "🔍 Qidiruv usulini tanlang (yoki shunchaki anime kodi/nomini yozib yuboring):",
            reply_markup=anime_search_menu_keyboard()
        )
        return

    if data == "srchmenu_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        kb = admin_menu_keyboard(query.from_user.id) if is_admin(query.from_user.id) else main_menu_keyboard()
        await context.bot.send_message(chat_id=query.from_user.id, text="🏠 Asosiy menu:", reply_markup=kb)
        return

    if data == "srchmenu_code":
        await query.message.edit_text("🔢 Anime kodini yuboring (masalan: 1, 2, 3...):")
        return

    if data == "srchmenu_name":
        await query.message.edit_text("🔤 Anime nomini yuboring (masalan: \"Naruto\"):")
        return

    if data == "srchmenu_genre":
        await query.message.edit_text("🎭 Janrni tanlang:", reply_markup=search_genre_keyboard())
        return

    if data == "srchmenu_recent":
        items = get_latest_animes(10)
        if not items:
            await query.message.edit_text("❌ Hali anime qo'shilmagan.", reply_markup=_srch_results_keyboard([]))
            return
        results = [(code, f"🆕 {name}") for code, name in items]
        await query.message.edit_text("🆕 So'ngi yuklangan animelar:", reply_markup=_srch_results_keyboard(results))
        return

    if data == "srchmenu_rating":
        items = get_top_rated_animes(10)
        if not items:
            await query.message.edit_text("❌ Hali reyting belgilangan anime yo'q.", reply_markup=_srch_results_keyboard([]))
            return
        results = [(code, f"⭐ {name} — {rating}") for code, name, rating in items]
        await query.message.edit_text("⭐ Reytingi eng baland animelar:", reply_markup=_srch_results_keyboard(results))
        return

    if data == "srchmenu_views":
        items = get_top_animes(10)
        if not items:
            await query.message.edit_text("❌ Hali statistika uchun yetarli ma'lumot yo'q.", reply_markup=_srch_results_keyboard([]))
            return
        results = [(code, f"👁 {name} — {count} marta ko'rilgan") for name, code, count in items]
        await query.message.edit_text("👁 Eng ko'p ko'rilgan animelar:", reply_markup=_srch_results_keyboard(results))
        return

    if data == "srchmenu_all":
        await _show_browse_page(query.message, page=0)
        return

    if data == "srchmenu_list":
        animes = get_all_animes()
        if not animes:
            await query.message.edit_text("❌ Hali anime qo'shilmagan.", reply_markup=_srch_results_keyboard([]))
            return
        lines = [f"`{code}` — {_esc_md(name)}" for code, name, *_ in animes]
        header = "📋 *Barcha animelar ro'yxati:*\n\n"
        chunks = []
        chunk = header
        for line in lines:
            if len(chunk) + len(line) + 1 > 3500:
                chunks.append(chunk)
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            chunks.append(chunk)

        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="srchmenu_root")]])
        if len(chunks) == 1:
            await query.message.edit_text(chunks[0], parse_mode="Markdown", reply_markup=back_kb)
        else:
            await query.message.edit_text(chunks[0], parse_mode="Markdown")
            for c in chunks[1:-1]:
                await query.message.reply_text(c, parse_mode="Markdown")
            await query.message.reply_text(chunks[-1], parse_mode="Markdown", reply_markup=back_kb)
        return

async def search_genre_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi qidiruv menyusida bitta janrni tanlaganda shu janrdagi animelarni ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    if idx < 0 or idx >= len(GENRE_LIST):
        return
    genre = GENRE_LIST[idx]
    items = get_animes_by_genre(genre, limit=30)
    if not items:
        await query.message.edit_text(
            f"❌ \"{genre}\" janrida hali anime yo'q.",
            reply_markup=_srch_results_keyboard([], back_callback="srchmenu_genre")
        )
        return
    results = [(code, name) for code, name in items]
    await query.message.edit_text(
        f"🎭 \"{genre}\" janridagi animelar:",
        reply_markup=_srch_results_keyboard(results, back_callback="srchmenu_genre")
    )

_BROWSE_PAGE_SIZE = 8

async def _show_browse_page(message, page):
    """'📚 Barcha animelar' bo'limi uchun sahifalangan ro'yxatni ko'rsatadi."""
    animes = get_all_animes()  # [(code, name, year, genre, total_episodes), ...]
    if not animes:
        await message.edit_text("❌ Hali anime qo'shilmagan.", reply_markup=_srch_results_keyboard([]))
        return
    total_pages = (len(animes) - 1) // _BROWSE_PAGE_SIZE + 1
    page = max(0, min(page, total_pages - 1))
    start = page * _BROWSE_PAGE_SIZE
    page_items = animes[start:start + _BROWSE_PAGE_SIZE]

    buttons = [[InlineKeyboardButton(f"{name} ({code})", callback_data=f"srch_{code}", style="primary")] for code, name, *_ in page_items]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"allanp_{page - 1}", style="primary"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"allanp_{page + 1}", style="primary"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="srchmenu_root", style="danger")])

    text = f"📚 Barcha animelar ({page + 1}/{total_pages}-sahifa):"
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def browse_all_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[1])
    await _show_browse_page(query.message, page)

def _start_gif_status_label():
    if not _start_gif_file_id():
        return " ⚪"
    return " ✅" if _start_gif_enabled() else " 🚫"

def _start_gif_detail_keyboard():
    buttons = [
        [InlineKeyboardButton("📤 GIF yuborish/almashtirish", callback_data="botset_gif_upload", style="primary")],
    ]
    if _start_gif_file_id():
        toggle_label = "🚫 /start GIFni o'chirish" if _start_gif_enabled() else "✅ /start GIFni yoqish"
        toggle_style = "danger" if _start_gif_enabled() else "success"
        buttons.append([InlineKeyboardButton(toggle_label, callback_data="botset_gif_toggle", style=toggle_style)])
        buttons.append([InlineKeyboardButton("🗑 GIFni butunlay o'chirish", callback_data="botset_gif_remove", style="danger")])
    buttons.append([InlineKeyboardButton("🔙 Start va ko'rinishga qaytish", callback_data="botset_appearance_open", style="primary")])
    return InlineKeyboardMarkup(buttons)

async def _render_start_gif_detail(query):
    file_id = _start_gif_file_id()
    if not file_id:
        status = "⚪ GIF hali yuklanmagan"
    elif _start_gif_enabled():
        status = "✅ Yoqilgan — /start bosilganda ko'rsatiladi"
    else:
        status = "🚫 O'chirilgan — GIF saqlangan, lekin /startda ko'rsatilmaydi"
    await query.message.edit_text(
        "🎞 */start GIF sozlamasi*\n\n"
        f"Holati: {status}\n\n"
        "GIFni yuboring — u saqlanadi va kerak bo'lsa /start xabarida ko'rsatiladi.",
        parse_mode="Markdown",
        reply_markup=_start_gif_detail_keyboard()
    )

def _start_buttons_menu_keyboard():
    buttons = []
    for setting_id, (label, key, default) in _START_BUTTON_SETTINGS.items():
        buttons.append([
            InlineKeyboardButton(
                _start_button_value(setting_id),
                callback_data=f"botset_btn_open_{setting_id}",
                style="primary"
            )
        ])
    buttons.append([
        InlineKeyboardButton("🔙 Start va ko'rinishga qaytish", callback_data="botset_appearance_open", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

async def _render_start_button_detail(query, setting_id):
    label, key, default = _START_BUTTON_SETTINGS[setting_id]
    current = _start_button_value(setting_id)
    buttons = [
        [InlineKeyboardButton("✏️ Tugma nomini o'zgartirish", callback_data=f"botset_btn_edit_{setting_id}", style="primary")],
        [InlineKeyboardButton("♻️ Standart nomga qaytarish", callback_data=f"botset_btn_reset_{setting_id}", style="primary")],
        [InlineKeyboardButton("🔙 Tugmalar ro'yxatiga qaytish", callback_data="botset_buttons_open", style="danger")],
    ]
    await query.message.edit_text(
        f"🎛 {label}\n\nHozirgi nomi:\n\n{current}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

def _auto_backup_status_text():
    channel = _auto_backup_channel()
    title = _auto_backup_channel_title()
    channel_text = f"{title or channel}" if channel else "❌ Ulanmagan"
    times = _auto_backup_times()
    times_text = ", ".join(times) if times else "❌ Kiritilmagan"
    status = "✅ Yoqilgan" if _auto_backup_enabled() else "🚫 O'chirilgan"
    return (
        "🤖 *Avtomatik backup*\n\n"
        f"Holati: {status}\n"
        f"📡 Backup yuboriladigan kanal: {channel_text}\n"
        f"⏰ Vaqtlar ({BACKUP_TIMEZONE_NAME}): {times_text}\n\n"
        "Bot har kuni shu ikki vaqtda yangi `.db` backup yaratib, "
        "ulangan kanalga hujjat qilib yuboradi."
    )

def _auto_backup_keyboard():
    buttons = [
        [InlineKeyboardButton("📡 Backup kanalini ulash", callback_data="botset_auto_backup_channel", style="primary")],
        [InlineKeyboardButton("⏰ 2 ta vaqtni sozlash", callback_data="botset_auto_backup_times", style="primary")],
    ]
    if _auto_backup_channel():
        buttons.append([
            InlineKeyboardButton("🗑 Kanalni uzish", callback_data="botset_auto_backup_remove_channel", style="danger")
        ])
    if _auto_backup_enabled():
        buttons.append([
            InlineKeyboardButton("🚫 Avtomatik backupni o'chirish", callback_data="botset_auto_backup_toggle", style="danger")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("✅ Avtomatik backupni yoqish", callback_data="botset_auto_backup_toggle", style="success")
        ])
    if _auto_backup_channel():
        buttons.append([
            InlineKeyboardButton("📤 Hozir test backup yuborish", callback_data="botset_auto_backup_test", style="primary")
        ])
    buttons.append([
        InlineKeyboardButton("🔙 Admin vositalariga qaytish", callback_data="botset_admin_open", style="danger")
    ])
    return InlineKeyboardMarkup(buttons)

async def _render_auto_backup_detail(query):
    await query.message.edit_text(
        _auto_backup_status_text(),
        parse_mode="Markdown",
        reply_markup=_auto_backup_keyboard()
    )

async def send_auto_backup_now(bot, channel_id=None):
    """Yangi baza backupini Telegram kanaliga yuboradi."""
    target = channel_id or _auto_backup_channel()
    if not target:
        raise RuntimeError("Backup kanali ulanmagan")
    db_path = os.path.abspath("anime.db")
    timestamp = datetime.now(BACKUP_TIMEZONE).strftime("%Y_%m_%d_%H%M%S")
    filename = f"anime_backup_{timestamp}.db"
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    try:
        _media_count, media_ref_count = await _create_media_database(bot, db_path, tmp_path)
        with open(tmp_path, "rb") as backup_file:
            await bot.send_document(
                chat_id=target,
                document=backup_file,
                filename=filename,
                caption=(
                    "💾 Avtomatik backup\n"
                    f"🔗 Bog'langan media file_id: {media_ref_count} ta\n"
                    f"🕐 {datetime.now(BACKUP_TIMEZONE).strftime('%Y-%m-%d %H:%M')} "
                    f"({BACKUP_TIMEZONE_NAME})"
                )
            )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

async def got_auto_backup_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_auto_backup_channel"):
        return
    text = update.message.text.strip()
    parsed = parse_channel_link(text)
    if not parsed or parsed[0] != "public":
        await update.message.reply_text(
            "❌ Ochiq Telegram kanal havolasini yuboring:\n"
            "• @kanal_nomi\n"
            "• https://t.me/kanal_nomi\n\n"
            "Bot shu kanalda administrator bo'lishi kerak."
        )
        return
    value = parsed[1]
    try:
        chat = await context.bot.get_chat(f"@{value}")
        if chat.type != "channel":
            raise RuntimeError("Bu havola kanalga tegishli emas")
        if not await _bot_is_channel_admin(context.bot, chat.id):
            raise RuntimeError("Bot bu kanalda administrator emas")
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Kanal ulanmagan: {_esc_md(str(exc))}\n"
            "Botni kanalga administrator qilib, qaytadan yuboring.",
            parse_mode="Markdown"
        )
        return
    set_bot_setting("auto_backup_channel", str(chat.id))
    set_bot_setting("auto_backup_channel_title", chat.title or f"@{value}")
    context.user_data.pop("awaiting_auto_backup_channel", None)
    await update.message.reply_text(
        f"✅ Backup kanali ulandi: *{_esc_md(chat.title or value)}*",
        parse_mode="Markdown",
        reply_markup=_auto_backup_keyboard()
    )

async def got_auto_backup_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_auto_backup_times"):
        return
    raw_times = [item for item in re.split(r"[\s,;]+", update.message.text.strip()) if item]
    if len(raw_times) != 2 or len(set(raw_times)) != 2:
        await update.message.reply_text(
            "❌ Aynan 2 ta turli vaqt kiriting.\n"
            "Masalan: `09:00 21:00` yoki `09:00,21:00`",
            parse_mode="Markdown"
        )
        return
    for value in raw_times:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            await update.message.reply_text(
                f"❌ `{_esc_md(value)}` noto'g'ri vaqt. 24 soatlik formatdan foydalaning: 09:00",
                parse_mode="Markdown"
            )
            return
    values = sorted(raw_times)
    set_bot_setting("auto_backup_times", ",".join(values))
    context.user_data.pop("awaiting_auto_backup_times", None)
    await update.message.reply_text(
        f"✅ Avtomatik backup vaqtlari saqlandi: *{', '.join(values)}* ({BACKUP_TIMEZONE_NAME})",
        parse_mode="Markdown",
        reply_markup=_auto_backup_keyboard()
    )

async def got_instagram_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_instagram_link"):
        return
    link = update.message.text.strip()
    if not re.fullmatch(r"https?://(?:www\.)?instagram\.com/[^\s]+", link, re.IGNORECASE):
        await update.message.reply_text(
            "❌ Instagram havolasi noto'g'ri.\n"
            "Masalan: https://instagram.com/username"
        )
        return
    set_bot_setting("instagram_link", link)
    context.user_data.pop("awaiting_instagram_link", None)
    await update.message.reply_text(
        "✅ Instagram havolasi saqlandi.\n"
        "Obuna holati tekshirilmaydi — havola faqat tugma sifatida ko'rsatiladi.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Majburiy obuna sozlamalariga qaytish", callback_data="botset_channels")]
        ])
    )

def _bot_appearance_menu_keyboard():
    buttons = []
    for setting_id, (label, key, default, can_disable) in _BOT_TEXT_SETTINGS.items():
        status = ""
        if can_disable:
            status = " ✅" if _bot_text_enabled(setting_id) else " 🚫"
        buttons.append([InlineKeyboardButton(f"{label}{status}", callback_data=f"botset_open_{setting_id}", style="primary")])
    buttons.append([InlineKeyboardButton(f"🎞 /start GIF{_start_gif_status_label()}", callback_data="botset_gif_open", style="primary")])
    buttons.append([InlineKeyboardButton("🎛 /start tugmalari", callback_data="botset_buttons_open", style="primary")])
    buttons.append([InlineKeyboardButton("🔙 Bot sozlamalariga qaytish", callback_data="botset_root", style="danger")])
    return InlineKeyboardMarkup(buttons)

def _bot_admin_tools_menu_keyboard(user_id=None):
    if not is_primary_admin(user_id):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Bot sozlamalariga qaytish", callback_data="botset_root", style="danger")]
        ])
    buttons = [
        [InlineKeyboardButton("💾 Backup olish", callback_data="botset_backup", style="primary")],
        [InlineKeyboardButton("♻️ Backup tiklash", callback_data="botset_restore", style="primary")],
        [InlineKeyboardButton("🤖 Avtomatik backup", callback_data="botset_auto_backup", style="primary")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("👨‍💼 Adminlar", callback_data="botset_admins", style="primary")])
    buttons.extend([
        [InlineKeyboardButton("📨 Xabar yuborish", callback_data="botset_broadcast", style="primary")],
        [InlineKeyboardButton("📢 Majburiy obuna", callback_data="botset_channels", style="primary")],
        [InlineKeyboardButton("🔙 Bot sozlamalariga qaytish", callback_data="botset_root", style="danger")],
    ])
    return InlineKeyboardMarkup(buttons)

def _bot_settings_menu_keyboard(user_id=None):
    buttons = [
        [InlineKeyboardButton("🎨 Start va ko'rinish", callback_data="botset_appearance_open", style="primary")],
    ]
    if is_primary_admin(user_id):
        buttons.append([InlineKeyboardButton("🗂 Admin vositalari", callback_data="botset_admin_open", style="primary")])
    buttons.append([InlineKeyboardButton("❌ Yopish", callback_data="botset_close", style="danger")])
    return InlineKeyboardMarkup(buttons)

async def bot_settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "⚙️ *Bot Sozlamalari*\n\nKerakli bo'limni tanlang:",
        parse_mode="Markdown",
        reply_markup=_bot_settings_menu_keyboard(update.effective_user.id)
    )

async def _render_setting_detail(query, setting_id):
    label, key, default, can_disable = _BOT_TEXT_SETTINGS[setting_id]
    current = _bot_text_value(setting_id)
    enabled = _bot_text_enabled(setting_id)
    status_line = ("✅ Yoqilgan" if enabled else "🚫 O'chirilgan (foydalanuvchiga \"bu bo'lim hozircha yo'q\" ko'rinadi)") if can_disable else "♾ Doim yoqilgan"
    buttons = [[InlineKeyboardButton("✏️ Matnni o'zgartirish", callback_data=f"botset_edit_{setting_id}", style="primary")]]
    if can_disable:
        toggle_label = "🚫 O'chirib qo'yish" if enabled else "✅ Yoqish"
        toggle_style = "danger" if enabled else "success"
        buttons.append([InlineKeyboardButton(toggle_label, callback_data=f"botset_toggle_{setting_id}", style=toggle_style)])
    buttons.append([InlineKeyboardButton("♻️ Standart matnga qaytarish", callback_data=f"botset_reset_{setting_id}", style="primary")])
    buttons.append([InlineKeyboardButton("🔙 Start va ko'rinishga qaytish", callback_data="botset_appearance_open", style="danger")])
    await query.message.edit_text(
        f"*{label}*\nHolati: {status_line}\n\nHozirgi matn:\n\n{_esc_md(current)}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def bot_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    data = query.data

    if data == "botset_close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data == "botset_appearance_open":
        await query.message.edit_text(
            "🎨 *Start va ko'rinish*\n\n"
            "Matn, GIF va /start tugmalarini shu yerdan boshqaring:",
            parse_mode="Markdown",
            reply_markup=_bot_appearance_menu_keyboard()
        )
        return

    if data == "botset_admin_open":
        if not is_primary_admin(query.from_user.id):
            await query.message.edit_text(
                "⛔ Bu bo'lim faqat bosh admin uchun.",
                reply_markup=_bot_settings_menu_keyboard(query.from_user.id)
            )
            return
        await query.message.edit_text(
            "🗂 *Admin vositalari*\n\n"
            "Backup, adminlar, xabar yuborish va majburiy obunani boshqaring:",
            parse_mode="Markdown",
            reply_markup=_bot_admin_tools_menu_keyboard(query.from_user.id)
        )
        return

    if data == "botset_gif_open":
        await _render_start_gif_detail(query)
        return

    if data == "botset_gif_upload":
        context.user_data["awaiting_start_gif"] = True
        await query.message.edit_text(
            "🎞 /start uchun GIFni shu chatga yuboring.\n\n"
            "Yangi GIF yuborsangiz, avvalgisi almashtiriladi.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Bekor qilish", callback_data="botset_gif_open", style="danger")]
            ])
        )
        return

    if data == "botset_gif_toggle":
        if _start_gif_file_id():
            set_bot_setting("start_gif_enabled", "0" if _start_gif_enabled() else "1")
        await _render_start_gif_detail(query)
        return

    if data == "botset_gif_remove":
        delete_bot_setting("start_gif_file_id")
        delete_bot_setting("start_gif_enabled")
        await _render_start_gif_detail(query)
        return

    if data == "botset_buttons_open":
        await query.message.edit_text(
            "🎛 */start tugmalari*\n\n"
            "Nomini o'zgartirmoqchi bo'lgan tugmani tanlang:",
            parse_mode="Markdown",
            reply_markup=_start_buttons_menu_keyboard()
        )
        return

    if data.startswith("botset_btn_open_"):
        setting_id = data[len("botset_btn_open_"):]
        if setting_id in _START_BUTTON_SETTINGS:
            await _render_start_button_detail(query, setting_id)
        return

    if data.startswith("botset_btn_edit_"):
        setting_id = data[len("botset_btn_edit_"):]
        if setting_id not in _START_BUTTON_SETTINGS:
            return
        context.user_data.pop("awaiting_bot_setting_text", None)
        context.user_data["awaiting_start_button_name"] = setting_id
        await query.message.edit_text(
            "✏️ Yangi tugma nomini yuboring.\n\n"
            "Nom 64 belgigacha bo'lsin."
        )
        return

    if data.startswith("botset_btn_reset_"):
        setting_id = data[len("botset_btn_reset_"):]
        if setting_id not in _START_BUTTON_SETTINGS:
            return
        _, key, _ = _START_BUTTON_SETTINGS[setting_id]
        delete_bot_setting(key)
        await _render_start_button_detail(query, setting_id)
        return

    if data == "botset_backup":
        await backup_db_command(update, context)
        return

    if data == "botset_restore":
        await restore_db_start(update, context)
        return

    if data == "botset_auto_backup":
        await _render_auto_backup_detail(query)
        return

    if data == "botset_auto_backup_channel":
        context.user_data["awaiting_auto_backup_channel"] = True
        await query.message.edit_text(
            "📡 Backup yuboriladigan kanalni yuboring:\n\n"
            "• @kanal_nomi\n"
            "• https://t.me/kanal_nomi\n\n"
            "Bot shu kanalda administrator bo'lishi shart."
        )
        return

    if data == "botset_auto_backup_times":
        context.user_data["awaiting_auto_backup_times"] = True
        await query.message.edit_text(
            f"⏰ Kuniga 2 marta backup yuboriladigan vaqtlarni yuboring.\n"
            f"Vaqt zonasi: *{BACKUP_TIMEZONE_NAME}*\n\n"
            "Masalan: `09:00 21:00`",
            parse_mode="Markdown"
        )
        return

    if data == "botset_auto_backup_remove_channel":
        delete_bot_setting("auto_backup_channel")
        delete_bot_setting("auto_backup_channel_title")
        delete_bot_setting("auto_backup_enabled")
        await _render_auto_backup_detail(query)
        return

    if data == "botset_auto_backup_toggle":
        if not _auto_backup_enabled():
            if not _auto_backup_channel() or len(_auto_backup_times()) != 2:
                await query.answer(
                    "Avval kanalni ulang va 2 ta vaqtni kiriting.",
                    show_alert=True
                )
                await _render_auto_backup_detail(query)
                return
            set_bot_setting("auto_backup_enabled", "1")
        else:
            set_bot_setting("auto_backup_enabled", "0")
        await _render_auto_backup_detail(query)
        return

    if data == "botset_auto_backup_test":
        if not _auto_backup_channel():
            await query.answer("Avval backup kanalini ulang.", show_alert=True)
            return
        await query.answer("⏳ Backup tayyorlanmoqda...")
        try:
            await send_auto_backup_now(context.bot)
            await query.message.reply_text("✅ Test backup ulangan kanalga yuborildi.")
        except Exception as exc:
            logger.exception("Test avtomatik backup yuborilmadi")
            await query.message.reply_text(f"❌ Test backup yuborilmadi: {_esc_md(str(exc))}", parse_mode="Markdown")
        return

    if data == "botset_admins":
        await admins_panel(update, context)
        return

    if data == "botset_channels":
        await manage_channels(update, context)
        return

    if data == "botset_root":
        await query.message.edit_text(
            "⚙️ *Bot Sozlamalari*\n\nKerakli bo'limni tanlang:",
            parse_mode="Markdown",
            reply_markup=_bot_settings_menu_keyboard(query.from_user.id)
        )
        return

    if data.startswith("botset_open_"):
        setting_id = data[len("botset_open_"):]
        if setting_id in _BOT_TEXT_SETTINGS:
            await _render_setting_detail(query, setting_id)
        return

    if data.startswith("botset_edit_"):
        setting_id = data[len("botset_edit_"):]
        if setting_id not in _BOT_TEXT_SETTINGS:
            return
        context.user_data["awaiting_bot_setting_text"] = setting_id
        await query.message.edit_text("✏️ Yangi matnni yozib yuboring (Markdown formatlash ishlatilishi mumkin):")
        return

    if data.startswith("botset_toggle_"):
        setting_id = data[len("botset_toggle_"):]
        if setting_id not in _BOT_TEXT_SETTINGS:
            return
        _, key, _, can_disable = _BOT_TEXT_SETTINGS[setting_id]
        if not can_disable:
            return
        enabled = _bot_text_enabled(setting_id)
        set_bot_setting(f"{key}_enabled", "0" if enabled else "1")
        await _render_setting_detail(query, setting_id)
        return

    if data.startswith("botset_reset_"):
        setting_id = data[len("botset_reset_"):]
        if setting_id not in _BOT_TEXT_SETTINGS:
            return
        _, key, _, _ = _BOT_TEXT_SETTINGS[setting_id]
        delete_bot_setting(key)
        await _render_setting_detail(query, setting_id)
        return

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    not_joined = await check_subscription(query.from_user.id, context)
    if not not_joined:
        await query.answer()
        await query.message.delete()
        pending_code = context.user_data.pop("pending_anime_code", None)
        pending_season_for = context.user_data.pop("pending_anime_season_for", None)
        if pending_code is not None:
            if pending_season_for and pending_season_for[0] == pending_code:
                await send_season_direct(context.bot, query.from_user.id, pending_code, pending_season_for[1])
            else:
                await send_anime_info(context.bot, query.from_user.id, pending_code)
        else:
            await send_start_from_callback(query, context)
    else:
        await query.answer(
            "❌ Hali barcha kanallarga obuna bo'lmadingiz!",
            show_alert=True
        )

async def send_start_from_callback(query, context):
    user = query.from_user
    user_is_admin = is_admin(user.id)
    text = _bot_text_value("start")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(_start_button_value("search"), callback_data="anime_search", style="primary")],
        [InlineKeyboardButton(_start_button_value("cabinet"), callback_data="kabinet", style="success"), InlineKeyboardButton(_start_button_value("guide"), callback_data="guide", style="primary")],
        [InlineKeyboardButton(_start_button_value("channel"), url=CHANNEL_LINK, style="success"), InlineKeyboardButton(_start_button_value("ad"), callback_data="reklama", style="danger")],
    ])
    if user_is_admin:
        admin_text = f"👑 Admin paneliga xush kelibsiz!\n\n{text}"
        if _start_gif_enabled():
            await context.bot.send_animation(
                chat_id=user.id,
                animation=_start_gif_file_id(),
                caption=admin_text,
                reply_markup=admin_menu_keyboard(user.id)
            )
        else:
            await context.bot.send_message(
                chat_id=user.id,
                text=admin_text,
                reply_markup=admin_menu_keyboard(user.id)
            )
    else:
        if _start_gif_enabled():
            await context.bot.send_animation(
                chat_id=user.id,
                animation=_start_gif_file_id(),
                caption=text,
                reply_markup=keyboard
            )
        else:
            await context.bot.send_message(
                chat_id=user.id,
                text=text,
                reply_markup=keyboard
            )

# ==================== USER HANDLERS ====================

async def anime_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Qidiruv usulini tanlang (yoki shunchaki anime kodi/nomini yozib yuboring):",
        reply_markup=anime_search_menu_keyboard()
    )

def _split_text(text, limit=4000):
    """Uzun matnni Telegram chegarasidan (4096) oshmaydigan bo'laklarga satr chegarasida bo'ladi."""
    chunks = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks

async def _reply_guide(message):
    if not _bot_text_enabled("guide"):
        await message.reply_text("❌ Bu bo'lim hozircha yo'q.")
        return
    for chunk in _split_text(_bot_text_value("guide")):
        await message.reply_text(chunk, link_preview_options=LinkPreviewOptions(is_disabled=True))

async def guide_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply_guide(update.message)

async def reklama_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _bot_text_enabled("reklama"):
        await update.message.reply_text("❌ Bu bo'lim hozircha yo'q.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Admin bilan bog'lanish", url=ADMIN_CONTACT_URL)]
    ])
    await update.message.reply_text(
        _bot_text_value("reklama"),
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def channel_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Kanalga o'tish", url=CHANNEL_LINK)]
    ])
    await update.message.reply_text(
        f"📺 Bizning animelar kanalimiz:\n{CHANNEL_LINK}",
        reply_markup=keyboard
    )

@_db_locked
def get_user_cabinet_data(user_id):
    """Kabinet uchun: (joined_date, ko'rilgan qismlar soni, [(code, name), ...] obunalar)."""
    conn = get_db()
    _ensure_watch_table(conn)
    row = conn.execute("SELECT joined_date FROM users WHERE id=?", (user_id,)).fetchone()
    joined = row[0] if row else None
    eps = conn.execute(
        "SELECT COUNT(*) FROM activity_log WHERE user_id=? AND event_type='episode_request'",
        (user_id,)
    ).fetchone()[0]
    subs = conn.execute(
        "SELECT a.code, a.name FROM anime_watch w JOIN animes a ON a.code = w.anime_code "
        "WHERE w.user_id=? ORDER BY w.created_at DESC",
        (user_id,)
    ).fetchall()
    return joined, eps, [(r[0], r[1]) for r in subs]

def _build_cabinet(user):
    joined, eps, subs = get_user_cabinet_data(user.id)
    days_text = ""
    if joined:
        try:
            days = (datetime.now().date() - datetime.strptime(joined, "%Y-%m-%d").date()).days
            days_text = f" ({max(days, 0)} kun)"
        except ValueError:
            pass
    text = (
        "⚙️ <b>Kabinet</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 <b>Ism:</b> {html.escape(user.full_name or '—')}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📅 <b>Botda:</b> {joined or '—'}{days_text}\n"
        "━━━━━━━━━━━━━━━\n"
        f"🎬 <b>Ko'rgan qismlar:</b> {eps} ta\n"
        f"🔔 <b>Obunalarim:</b> {len(subs)} ta"
    )
    buttons = []
    if subs:
        text += "\n\n👇 Obuna bo'lgan animelaringiz:"
        for code, name in subs[:10]:
            buttons.append([InlineKeyboardButton(f"🔔 {name}", callback_data=f"srch_{code}")])
        if len(subs) > 10:
            text += f"\n(Oxirgi 10 tasi ko'rsatildi, jami {len(subs)} ta)"
    else:
        text += "\n\nHali hech qaysi animega obuna bo'lmagansiz. Anime sahifasidagi «🔔 Yangi qism chiqsa xabar bering» tugmasini bosing."
    return text, (InlineKeyboardMarkup(buttons) if buttons else None)

async def kabinet_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = _build_cabinet(update.effective_user)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

# ==================== INLINE BUTTON CALLBACKS ====================

async def inline_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "anime_search":
        await query.message.reply_text(
            "🔍 Qidiruv usulini tanlang (yoki shunchaki anime kodi/nomini yozib yuboring):",
            reply_markup=anime_search_menu_keyboard()
        )

    elif data == "guide":
        await _reply_guide(query.message)

    elif data == "reklama":
        if not _bot_text_enabled("reklama"):
            await query.message.reply_text("❌ Bu bo'lim hozircha yo'q.")
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Admin bilan bog'lanish", url=ADMIN_CONTACT_URL)]
            ])
            await query.message.reply_text(
                _bot_text_value("reklama"),
                parse_mode="Markdown",
                reply_markup=keyboard
            )

    elif data == "kabinet":
        text, keyboard = _build_cabinet(query.from_user)
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def handle_start_gif_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_start_gif"):
        return
    file_id = update.message.animation.file_id
    set_bot_setting("start_gif_file_id", file_id)
    set_bot_setting("start_gif_enabled", "1")
    context.user_data.pop("awaiting_start_gif", None)
    await update.message.reply_text(
        "✅ GIF saqlandi va /start uchun yoqildi.",
        reply_markup=_start_gif_detail_keyboard()
    )

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Admin yangi so'rovnoma savoli/variantlarini yozayotgan bo'lsa
    if is_admin(update.effective_user.id) and context.user_data.get("svy_step"):
        if await survey_admin_text(update, context, text):
            return

    # /start tugmasining nomini saqlash
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_start_button_name"):
        setting_id = context.user_data["awaiting_start_button_name"]
        if setting_id not in _START_BUTTON_SETTINGS:
            context.user_data.pop("awaiting_start_button_name", None)
            return
        if not text or len(text) > 64:
            await update.message.reply_text("❌ Tugma nomi bo'sh bo'lmasin va 64 belgidan oshmasin.")
            return
        _, key, _ = _START_BUTTON_SETTINGS[setting_id]
        set_bot_setting(key, text)
        context.user_data.pop("awaiting_start_button_name", None)
        await update.message.reply_text(
            f"✅ Tugma nomi saqlandi:\n\n{text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Tugmalar ro'yxatiga qaytish", callback_data="botset_buttons_open", style="primary")]
            ])
        )
        return

    # Bot Sozlamalari — admin yangi matn yuborishini kutayotgan bo'lsa
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_bot_setting_text"):
        setting_id = context.user_data.pop("awaiting_bot_setting_text")
        if setting_id in _BOT_TEXT_SETTINGS:
            _, key, _, _ = _BOT_TEXT_SETTINGS[setting_id]
            set_bot_setting(key, update.message.text)
            await update.message.reply_text(
                "✅ Matn muvaffaqiyatli yangilandi.",
                reply_markup=admin_menu_keyboard(update.effective_user.id)
            )
        return

    # Handle awaiting channel input from admin
    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel"):
        await got_add_channel(update, context)
        return

    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_instagram_link"):
        await got_instagram_link(update, context)
        return

    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_auto_backup_channel"):
        await got_auto_backup_channel(update, context)
        return

    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_auto_backup_times"):
        await got_auto_backup_times(update, context)
        return

    # Handle admin qo'lda kiritayotgan kanal nomi
    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_title"):
        await got_channel_title(update, context)
        return

    # Handle admin qo'lda kiritayotgan majburiy obuna muddati (kun)
    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_custom_days"):
        await got_channel_custom_days(update, context)
        return

    # Handle admin "Kanalga Yuborish" uchun qo'lda kod kiritishi
    if is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_send_code"):
        await got_channel_send_code(update, context)
        return

    # Handle awaiting new-admin ID input from super admin
    if update.effective_user.id == ADMIN_ID and context.user_data.get("awaiting_admin_id"):
        await got_add_admin_id(update, context)
        return

    # Admin menu buttons
    if is_admin(update.effective_user.id):
        if text == "🔙 Asosiy Menu":
            await update.message.reply_text("Asosiy menu:", reply_markup=main_menu_keyboard())
            return
        if text == "📊 Statistika":
            await show_stats(update, context)
            return
        if text == "📋 Animeler Ro'yxati":
            await show_anime_list(update, context)
            return

    if not text.isdigit():
        # 4 harfdan qisqa matn anime nomi sifatida qidirilmaydi (bazani ortiqcha yuklamaslik uchun).
        if len(text.strip()) < 4:
            if not is_admin(update.effective_user.id):
                await update.message.reply_text("⚠️ Anime nomini kamida 4 harf bilan yozing yoki kodini yuboring.")
            return
        matches = find_animes_by_name(text)
        if not matches:
            suggestions = suggest_animes_by_name(text)
            if suggestions:
                buttons = [
                    [InlineKeyboardButton(f"{name} — {code}", callback_data=f"srch_{code}")]
                    for code, name in suggestions
                ]
                await update.message.reply_text(
                    f"🤔 \"{text}\" topilmadi. Balki siz shu animeni qidiryapsiz:",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            elif not is_admin(update.effective_user.id):
                await update.message.reply_text("❌ Anime topilmadi. Kod yoki to'liq nomini yozing.")
            return
        if len(matches) == 1:
            code = matches[0][0]
            if not await require_subscription(update, context, pending_code=code):
                return
            await send_anime_info(context.bot, update.effective_chat.id, code)
            return
        buttons = [
            [InlineKeyboardButton(f"{name} — {code}", callback_data=f"srch_{code}")]
            for code, name in matches[:15]
        ]
        await update.message.reply_text(
            f"🔍 \"{text}\" bo'yicha {len(matches)} ta natija topildi:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    code = int(text)
    if not await require_subscription(update, context, pending_code=code):
        return
    await send_anime_info(context.bot, update.effective_chat.id, code)

async def episode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data == "top10_animes":
        await show_top_animes_callback(update, context)
        return

    if data.startswith("page_"):
        _, season_id, page = data.split("_")
        await query.edit_message_reply_markup(
            reply_markup=episodes_keyboard(int(season_id), int(page), user_id=query.from_user.id)
        )
        return

    if data.startswith("all_eps_"):
        season_id = int(data[len("all_eps_"):])
        user = query.from_user
        if not is_admin(user.id):
            await query.answer("🚫 Bu funksiya faqat adminlar uchun.", show_alert=True)
            return

        episode_numbers = get_episodes_list(season_id)
        if not episode_numbers:
            await query.answer("❌ Bu faslda yuklangan qism yo'q.", show_alert=True)
            return

        season = get_season_by_id(season_id)
        anime_name = ""
        episode_cover = None
        if season:
            anime = get_anime_by_code(season[1])
            if anime:
                anime_name = anime[2]
                episode_cover = get_season_episode_cover(season_id)

        progress = await query.message.reply_text(
            f"📥 {len(episode_numbers)} ta qism yuborilmoqda..."
        )
        sent_count = 0
        failed_count = 0
        for ep_num in episode_numbers:
            episode = get_episode(season_id, ep_num)
            if not episode:
                failed_count += 1
                continue
            try:
                video_kwargs = {
                    "chat_id": user.id,
                    "video": episode[0],
                    "caption": _episode_caption(anime_name, season, ep_num),
                }
                if episode_cover:
                    video_kwargs["cover"] = episode_cover
                await context.bot.send_video(**video_kwargs)
                sent_count += 1
                await asyncio.sleep(0.1)
            except Exception as exc:
                failed_count += 1
                logger.warning(
                    "Barcha qismlar yuborilmadi (anime=%s, season=%s, episode=%s): %s",
                    anime_name,
                    season_id,
                    ep_num,
                    exc,
                )

        try:
            await progress.edit_text(
                f"✅ Yuborildi: {sent_count} ta\n"
                f"❌ Yuborilmadi: {failed_count} ta"
            )
        except Exception:
            logger.exception("Barcha qismlar holatini yangilashda xato")
        return

    if data.startswith("ep_"):
        _, season_id, ep_num = data.split("_")
        user = query.from_user
        if not is_admin(user.id):
            not_joined = await check_subscription(user.id, context)
            if not_joined:
                season_for_code = get_season_by_id(int(season_id))
                if season_for_code:
                    context.user_data["pending_anime_code"] = season_for_code[1]
                await query.message.reply_text(
                    "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                    reply_markup=_subscription_keyboard(not_joined)
                )
                return
        episode = get_episode(int(season_id), int(ep_num))
        if episode:
            season = get_season_by_id(int(season_id))
            anime_name = ""
            if season:
                anime = get_anime_by_code(season[1])
                if anime:
                    anime_name = anime[2]
                if not is_admin(user.id):
                    log_activity("episode_request", season[1], user.id)
            try:
                video_kwargs = {
                    "chat_id": query.from_user.id,
                    "video": episode[0],
                    "caption": _episode_caption(anime_name, season, ep_num),
                }
                # Qism cover'i har bir faslda alohida saqlanadi va faqat videoga biriktiriladi.
                episode_cover = get_season_episode_cover(season_id) if season else None
                if episode_cover:
                    video_kwargs["cover"] = episode_cover
                await context.bot.send_video(**video_kwargs)
                if not is_admin(user.id):
                    await maybe_ask_survey(context.bot, user.id)
            except Exception as e:
                logger.warning(
                    "Qism videosi yuborilmadi (anime=%s, season=%s, episode=%s): %s",
                    anime_name,
                    season_id,
                    ep_num,
                    e,
                )
                await query.message.reply_text(
                    f"❌ {ep_num}-qism videosi topilmadi.\n"
                    "Anime ma'lumotlari saqlangan, admin videoni qayta yuklashi kerak."
                )
        else:
            await query.answer("❌ Bu qism hali yuklanmagan!", show_alert=True)

# ==================== SO'ROVNOMALAR (survey) ====================
REGION_OPTIONS = [
    "Andijon", "Buxoro", "Farg'ona", "Jizzax", "Xorazm", "Namangan", "Navoiy",
    "Qashqadaryo", "Samarqand", "Sirdaryo", "Surxondaryo", "Toshkent viloyati",
    "Qoraqalpog'iston", "Toshkent shahri",
]
SURVEY_ASK_CHANCE = 0.2            # anime/qism so'ralganda savol chiqish ehtimoli (20%)
SURVEY_COOLDOWN_SEC = 6 * 3600     # bir foydalanuvchiga ketma-ket savol chiqmasligi uchun
SURVEY_THANKS = "🙏 Javobingiz uchun rahmat! Yoqimli tomosha 🍿"
SURVEY_MAX_OPTIONS = 16
SURVEY_STATUS_LABELS = {
    "draft": "📝 Ko'rib chiqilmagan",
    "active": "🟢 Yoqilgan",
    "paused": "⏸ To'xtatilgan",
}
SURVEY_STEP_TTL = 600  # admin savol yozish holati 10 daqiqadan keyin bekor bo'ladi


def _ensure_survey_tables(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS surveys ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, options TEXT NOT NULL, "
        "status TEXT NOT NULL DEFAULT 'draft', created_at REAL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS survey_answers ("
        "survey_id INTEGER NOT NULL, user_id INTEGER NOT NULL, option_idx INTEGER NOT NULL, "
        "answered_at REAL, PRIMARY KEY (survey_id, user_id))"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS survey_users (user_id INTEGER PRIMARY KEY, last_asked REAL)")
    seeded = conn.execute("SELECT value FROM app_meta WHERE key='survey_region_seeded'").fetchone()
    if not seeded:
        # Tayyor viloyat savoli: avval admin ko'rib chiqishi uchun 'draft' holatida qo'shiladi.
        conn.execute(
            "INSERT INTO surveys (question, options, status, created_at) VALUES (?, ?, 'draft', ?)",
            ("📍 Qaysi viloyatdasiz?", json.dumps(REGION_OPTIONS, ensure_ascii=False), time.time())
        )
        conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('survey_region_seeded', '1')")
        conn.commit()


def _survey_row(row):
    return {"id": row[0], "question": row[1], "options": json.loads(row[2]), "status": row[3]}


@_db_locked
def create_survey(question, options):
    conn = get_db()
    _ensure_survey_tables(conn)
    cur = conn.execute(
        "INSERT INTO surveys (question, options, status, created_at) VALUES (?, ?, 'draft', ?)",
        (question, json.dumps(options, ensure_ascii=False), time.time())
    )
    conn.commit()
    return cur.lastrowid


@_db_locked
def get_survey(survey_id):
    conn = get_db()
    _ensure_survey_tables(conn)
    row = conn.execute("SELECT id, question, options, status FROM surveys WHERE id=?", (survey_id,)).fetchone()
    return _survey_row(row) if row else None


@_db_locked
def list_surveys():
    conn = get_db()
    _ensure_survey_tables(conn)
    rows = conn.execute(
        "SELECT s.id, s.question, s.options, s.status, "
        "(SELECT COUNT(*) FROM survey_answers a WHERE a.survey_id = s.id) "
        "FROM surveys s ORDER BY s.id DESC"
    ).fetchall()
    return [dict(_survey_row(r), answers=r[4]) for r in rows]


@_db_locked
def set_survey_status(survey_id, status):
    conn = get_db()
    _ensure_survey_tables(conn)
    conn.execute("UPDATE surveys SET status=? WHERE id=?", (status, survey_id))
    conn.commit()


@_db_locked
def delete_survey(survey_id):
    conn = get_db()
    _ensure_survey_tables(conn)
    conn.execute("DELETE FROM survey_answers WHERE survey_id=?", (survey_id,))
    conn.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
    conn.commit()


@_db_locked
def get_survey_results(survey_id, option_count):
    conn = get_db()
    _ensure_survey_tables(conn)
    counts = [0] * option_count
    for idx, cnt in conn.execute(
        "SELECT option_idx, COUNT(*) FROM survey_answers WHERE survey_id=? GROUP BY option_idx", (survey_id,)
    ).fetchall():
        if 0 <= idx < option_count:
            counts[idx] = cnt
    return counts, sum(counts)


@_db_locked
def pick_survey_for_user(user_id):
    """Foydalanuvchiga hali javob bermagan faol savollardan birini tanlaydi (cooldown bilan)."""
    conn = get_db()
    _ensure_survey_tables(conn)
    now = time.time()
    row = conn.execute("SELECT last_asked FROM survey_users WHERE user_id=?", (user_id,)).fetchone()
    if row and row[0] and now - row[0] < SURVEY_COOLDOWN_SEC:
        return None
    rows = conn.execute(
        "SELECT id, question, options, status FROM surveys WHERE status='active' AND id NOT IN "
        "(SELECT survey_id FROM survey_answers WHERE user_id=?)", (user_id,)
    ).fetchall()
    if not rows:
        return None
    survey = _survey_row(random.choice(rows))
    conn.execute("INSERT OR REPLACE INTO survey_users (user_id, last_asked) VALUES (?, ?)", (user_id, now))
    conn.commit()
    return survey


@_db_locked
def save_survey_answer(survey_id, user_id, option_idx):
    conn = get_db()
    _ensure_survey_tables(conn)
    row = conn.execute("SELECT options, status FROM surveys WHERE id=?", (survey_id,)).fetchone()
    if not row or row[1] != "active":
        return False
    if not (0 <= option_idx < len(json.loads(row[0]))):
        return False
    cur = conn.execute(
        "INSERT OR IGNORE INTO survey_answers (survey_id, user_id, option_idx, answered_at) VALUES (?, ?, ?, ?)",
        (survey_id, user_id, option_idx, time.time())
    )
    conn.commit()
    return cur.rowcount > 0


def _survey_keyboard(survey_id, options, preview=False):
    rows, row = [], []
    for i, opt in enumerate(options):
        data = "svyadm_noop" if preview else f"svy_{survey_id}_{i}"
        row.append(InlineKeyboardButton(opt, callback_data=data))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _survey_text(survey):
    return f"📝 <b>{html.escape(survey['question'])}</b>"


async def maybe_ask_survey(bot, user_id):
    """Anime ochilganda yoki qism yuborilganda, ba'zan (tasodifan) so'rovnoma chiqaradi."""
    try:
        if is_admin(user_id) or random.random() >= SURVEY_ASK_CHANCE:
            return
        survey = pick_survey_for_user(user_id)
        if not survey:
            return
        await bot.send_message(
            chat_id=user_id,
            text=_survey_text(survey),
            parse_mode="HTML",
            reply_markup=_survey_keyboard(survey["id"], survey["options"]),
        )
    except Exception as exc:
        logger.warning("So'rovnoma yuborilmadi (user=%s): %s", user_id, exc)


async def send_anime_info(bot, chat_id, code):
    await _send_anime_info_core(bot, chat_id, code)
    if get_anime_by_code(code):
        await maybe_ask_survey(bot, chat_id)


async def survey_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, sid, idx = query.data.split("_")
        sid, idx = int(sid), int(idx)
    except ValueError:
        await query.answer()
        return
    saved = save_survey_answer(sid, query.from_user.id, idx)
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    if saved:
        await context.bot.send_message(chat_id=query.from_user.id, text=SURVEY_THANKS)


# -- ADMIN --
def _survey_admin_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yangi savol", callback_data="svyadm_new")],
        [InlineKeyboardButton("📋 Savollar ro'yxati", callback_data="svyadm_list")],
        [InlineKeyboardButton("📈 Natijalar", callback_data="svyadm_results")],
    ])


_SURVEY_MENU_TEXT = (
    "📊 <b>So'rovnomalar</b>\n\n"
    "Yoqilgan savollar foydalanuvchilarga anime yoki qism so'raganda tasodifan chiqadi. "
    "Javob berilgach tugmalar o'chadi va bot rahmat aytadi."
)


def _survey_cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="svyadm_cancel")]])


def _survey_results_text(survey):
    counts, total = get_survey_results(survey["id"], len(survey["options"]))
    lines = [f"<b>{html.escape(survey['question'])}</b>  —  {total} ta javob"]
    for opt, cnt in zip(survey["options"], counts):
        pct = round(cnt * 100 / total) if total else 0
        lines.append(f"• {html.escape(opt)} — {cnt} ({pct}%)")
    return "\n".join(lines)


async def _survey_show(query, text, kb=None):
    try:
        await query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


def _survey_view_payload(survey):
    status = SURVEY_STATUS_LABELS.get(survey["status"], survey["status"])
    text = f"{status}\n\n{_survey_results_text(survey)}"
    sid = survey["id"]
    if survey["status"] == "active":
        toggle = InlineKeyboardButton("⏸ To'xtatish", callback_data=f"svyadm_off_{sid}")
    else:
        toggle = InlineKeyboardButton("✅ Yoqish", callback_data=f"svyadm_on_{sid}")
    kb = InlineKeyboardMarkup([
        [toggle, InlineKeyboardButton("🗑 O'chirish", callback_data=f"svyadm_delask_{sid}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="svyadm_list")],
    ])
    return text, kb


async def survey_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    for k in ("svy_step", "svy_q", "svy_ts"):
        context.user_data.pop(k, None)
    await update.message.reply_text(_SURVEY_MENU_TEXT, parse_mode="HTML", reply_markup=_survey_admin_menu_kb())


async def survey_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    data = query.data

    if data == "svyadm_noop":
        await query.answer("👀 Bu faqat ko'rinish. Tugmalar foydalanuvchida ishlaydi.", show_alert=True)
        return
    await query.answer()

    if data in ("svyadm_menu", "svyadm_cancel"):
        for k in ("svy_step", "svy_q", "svy_ts"):
            context.user_data.pop(k, None)
        await _survey_show(query, _SURVEY_MENU_TEXT, _survey_admin_menu_kb())

    elif data == "svyadm_new":
        context.user_data.update({"svy_step": "question", "svy_ts": time.time()})
        await _survey_show(query, "✍️ Savol matnini yozing (masalan: <i>Qaysi janrni yoqtirasiz?</i>):", _survey_cancel_kb())

    elif data == "svyadm_list":
        surveys = list_surveys()
        if not surveys:
            await _survey_show(query, "Hali savollar yo'q.", InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Yangi savol", callback_data="svyadm_new")],
                [InlineKeyboardButton("🔙 Orqaga", callback_data="svyadm_menu")],
            ]))
            return
        icons = {"draft": "📝", "active": "🟢", "paused": "⏸"}
        buttons = [
            [InlineKeyboardButton(f"{icons.get(s['status'], '•')} {s['question'][:32]} ({s['answers']})",
                                  callback_data=f"svyadm_view_{s['id']}")]
            for s in surveys[:30]
        ]
        buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="svyadm_menu")])
        await _survey_show(
            query,
            "📋 <b>Savollar ro'yxati</b>\n📝 ko'rib chiqilmagan · 🟢 yoqilgan · ⏸ to'xtatilgan\nQavs ichida — javoblar soni.",
            InlineKeyboardMarkup(buttons),
        )

    elif data == "svyadm_results":
        parts = [_survey_results_text(s) for s in list_surveys() if s["status"] != "draft"]
        text = "📈 <b>Natijalar</b>\n\n" + "\n\n".join(parts) if parts else "Hali yoqilgan savollar yo'q."
        await _survey_show(query, text[:4000], InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="svyadm_menu")]]))

    else:
        try:
            action, sid = data[len("svyadm_"):].rsplit("_", 1)
            sid = int(sid)
        except ValueError:
            return
        survey = get_survey(sid)
        if not survey:
            await _survey_show(query, "❌ Bu savol topilmadi (o'chirilgan bo'lishi mumkin).",
                               InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="svyadm_list")]]))
            return

        if action == "view":
            text, kb = _survey_view_payload(survey)
            await _survey_show(query, text, kb)
        elif action == "on":
            set_survey_status(sid, "active")
            text, kb = _survey_view_payload(get_survey(sid))
            await _survey_show(query, text, kb)
        elif action == "off":
            set_survey_status(sid, "paused")
            text, kb = _survey_view_payload(get_survey(sid))
            await _survey_show(query, text, kb)
        elif action == "delask":
            await _survey_show(query, f"🗑 <b>{html.escape(survey['question'])}</b>\n\nSavol va barcha javoblar o'chiriladi. Ishonchingiz komilmi?",
                               InlineKeyboardMarkup([[
                                   InlineKeyboardButton("✅ Ha, o'chirish", callback_data=f"svyadm_delyes_{sid}"),
                                   InlineKeyboardButton("❌ Yo'q", callback_data=f"svyadm_view_{sid}"),
                               ]]))
        elif action == "delyes":
            delete_survey(sid)
            await _survey_show(query, "🗑 Savol o'chirildi.", InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Ro'yxat", callback_data="svyadm_list")],
            ]))
        elif action == "ok":
            set_survey_status(sid, "active")
            await _survey_show(query, "✅ Savol yoqildi. Endi foydalanuvchilarga tasodifan chiqadi.", InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Savollar ro'yxati", callback_data="svyadm_list")],
            ]))
        elif action == "redo":
            delete_survey(sid)
            context.user_data.update({"svy_step": "question", "svy_ts": time.time()})
            await _survey_show(query, "🗑 O'chirildi.\n\n✍️ Yangi savol matnini yozing:", _survey_cancel_kb())


async def _survey_send_preview(update: Update, survey):
    """Admin uchun: savol foydalanuvchiga aynan qanday ko'rinishini va tasdiqlash tugmalarini ko'rsatadi."""
    await update.message.reply_text(
        _survey_text(survey), parse_mode="HTML",
        reply_markup=_survey_keyboard(survey["id"], survey["options"], preview=True),
    )
    sid = survey["id"]
    await update.message.reply_text(
        "👆 Foydalanuvchilarga shunday ko'rinadi. Yoqdimi?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yoqdi, yoqish", callback_data=f"svyadm_ok_{sid}"),
            InlineKeyboardButton("🗑 O'chirib, qaytadan", callback_data=f"svyadm_redo_{sid}"),
        ]]),
    )


async def survey_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    """Admin yangi savol yozayotganda handle_code dan chaqiriladi. True — matn ishlatildi."""
    step = context.user_data.get("svy_step")
    if not step:
        return False
    if time.time() - context.user_data.get("svy_ts", 0) > SURVEY_STEP_TTL:
        for k in ("svy_step", "svy_q", "svy_ts"):
            context.user_data.pop(k, None)
        return False

    if step == "question":
        if not (3 <= len(text) <= 200):
            await update.message.reply_text("❌ Savol 3 dan 200 belgigacha bo'lishi kerak. Qayta yozing:", reply_markup=_survey_cancel_kb())
            return True
        context.user_data.update({"svy_q": text, "svy_step": "options", "svy_ts": time.time()})
        await update.message.reply_text(
            f"✅ Savol: <b>{html.escape(text)}</b>\n\nEndi javob variantlarini yozing — "
            f"har birini yangi qatordan (2 tadan {SURVEY_MAX_OPTIONS} tagacha):",
            parse_mode="HTML", reply_markup=_survey_cancel_kb(),
        )
        return True

    if step == "options":
        opts = [o.strip() for o in text.split("\n") if o.strip()]
        error = None
        if not (2 <= len(opts) <= SURVEY_MAX_OPTIONS):
            error = f"Variantlar soni 2 dan {SURVEY_MAX_OPTIONS} gacha bo'lishi kerak."
        elif any(len(o) > 40 for o in opts):
            error = "Har bir variant 40 belgidan oshmasligi kerak."
        elif len(set(opts)) != len(opts):
            error = "Variantlar takrorlanmasligi kerak."
        if error:
            await update.message.reply_text(f"❌ {error} Qayta yozing (har biri yangi qatordan):", reply_markup=_survey_cancel_kb())
            return True
        question = context.user_data.get("svy_q", "")
        for k in ("svy_step", "svy_q", "svy_ts"):
            context.user_data.pop(k, None)
        sid = create_survey(question, opts)
        await _survey_send_preview(update, get_survey(sid))
        return True
    return False


# ==================== ADMIN HANDLERS ====================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Ruxsat yo'q!")
        return
    await update.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))

# -- ADD ANIME helpers --
def _cancel_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]])

async def cancel_anime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

# -- ADD ANIME --
async def add_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        "➕ *Yangi anime qo'shish*\n\n"
        "1️⃣ Anime kodini yozing:\n_(faqat raqam, masalan: 101)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("👇", reply_markup=_cancel_kb())
    return WAIT_ANIME_CODE

async def got_anime_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text(
            "⚠️ Faqat musbat *raqam* yuboring (masalan: 101):",
            parse_mode="Markdown", reply_markup=_cancel_kb()
        )
        return WAIT_ANIME_CODE
    code = int(txt)
    if get_anime_by_code(code):
        await update.message.reply_text(
            f"⚠️ *{code}* kodli anime allaqachon mavjud!\n"
            "Boshqa kod kiriting:",
            parse_mode="Markdown", reply_markup=_cancel_kb()
        )
        return WAIT_ANIME_CODE
    context.user_data["new_anime_code"] = code
    await update.message.reply_text(
        _BULK_TEMPLATE,
        parse_mode="Markdown", reply_markup=_cancel_kb()
    )
    return WAIT_ANIME_BULK

# -- Bitta xabarda barcha ma'lumotni qabul qilish (label asosida ajratish) --
_BULK_TEMPLATE = (
    "2️⃣ Endi barcha ma'lumotni *bitta xabarda* shu ko'rinishda yuboring:\n\n"
    "```\n"
    "Nom: One Piece\n"
    "Original: One Piece\n"
    "Yil: 1999\n"
    "Janr: Jangari, Sarguzasht, Komediya\n"
    "Tavsif: Dengiz qaroqchilari haqida...\n"
    "Qism: 24\n"
    "Reyting: 8.5\n"
    "Holat: davom etmoqda\n"
    "```\n\n"
    "_Holat: davom etmoqda / tugagan / tez orada / tanaffusda._"
)

_LABEL_ALIASES = {
    "nom": "name", "nomi": "name", "anime nomi": "name", "name": "name",
    "original": "original", "original nom": "original", "original nomi": "original", "orginal": "original",
    "yil": "year", "yili": "year", "chiqqan yil": "year", "chiqarilgan yil": "year", "year": "year",
    "janr": "genre", "janri": "genre", "janrlar": "genre", "genre": "genre",
    "tavsif": "desc", "tavsifi": "desc", "syujet": "desc", "izoh": "desc", "description": "desc",
    "qism": "episodes", "qismi": "episodes", "qismlar": "episodes", "qism soni": "episodes", "episodes": "episodes",
    "reyting": "rating", "reyt": "rating", "rating": "rating",
    "holat": "status", "holati": "status", "status": "status",
}
_FIELD_DISPLAY = {
    "name": "Nom", "original": "Original", "year": "Yil", "genre": "Janr",
    "desc": "Tavsif", "episodes": "Qism", "rating": "Reyting", "status": "Holat",
}
_REQUIRED_BULK_FIELDS = ["name", "original", "year", "genre", "desc", "episodes", "rating", "status"]
_GENRE_LOOKUP = {g.lower(): g for g in GENRE_LIST}
_STATUS_ALIASES = {
    "davom etmoqda": "ongoing", "davom": "ongoing", "davomida": "ongoing", "ongoing": "ongoing",
    "tugagan": "finished", "tugadi": "finished", "finished": "finished",
    "tez orada": "soon", "kutilmoqda": "soon", "soon": "soon",
    "tanaffusda": "paused", "tanaffus": "paused", "paused": "paused",
}
_BULK_LINE_RE = re.compile(r"^([^:]{1,25}):\s*(.*)$")

def _normalize_label(s):
    s = s.strip().lower()
    for ch in ("’", "‘", "ʻ", "ʼ", "`"):
        s = s.replace(ch, "'")
    return re.sub(r"\s+", " ", s)

def _parse_anime_bulk(text):
    """Bitta xabarda yuborilgan 'Label: qiymat' qatorlarini ajratib oladi.
    Label'siz qatorlar (masalan tavsifning davomi) joriy maydonga qo'shiladi."""
    raw = {}
    current_field = None
    for line in text.split("\n"):
        if not line.strip():
            continue
        m = _BULK_LINE_RE.match(line)
        matched_field = None
        if m:
            label_norm = _normalize_label(m.group(1))
            matched_field = _LABEL_ALIASES.get(label_norm)
        if matched_field:
            current_field = matched_field
            raw.setdefault(current_field, [])
            value = m.group(2).strip()
            if value:
                raw[current_field].append(value)
        elif current_field:
            raw[current_field].append(line.strip())

    data = {}
    invalid = []

    if raw.get("name"):
        name_val = " ".join(raw["name"]).strip()
        if name_val and name_val != "-":
            data["name"] = name_val

    if raw.get("original"):
        v = " ".join(raw["original"]).strip()
        if v and v != "-":
            data["original"] = v

    if raw.get("year"):
        v = " ".join(raw["year"]).strip()
        if v.isdigit() and len(v) == 4:
            data["year"] = int(v)
        else:
            invalid.append("Yil — 4 xonali raqam yozing (masalan: 2023)")

    if raw.get("genre"):
        v = " ".join(raw["genre"]).strip()
        parts = [p.strip() for p in v.split(",") if p.strip()]
        matched, unknown = [], []
        for p in parts:
            hit = _GENRE_LOOKUP.get(p.lower())
            if hit:
                if hit not in matched:
                    matched.append(hit)
            else:
                unknown.append(p)
        if unknown:
            invalid.append(f"Janr — noma'lum janr(lar): {', '.join(unknown)}. Ro'yxatdagi janrlardan foydalaning: {', '.join(GENRE_LIST)}")
        elif matched:
            data["genre"] = ", ".join(matched)

    if raw.get("desc"):
        v = "\n".join(raw["desc"]).strip()
        if v and v != "-":
            data["desc"] = v

    if raw.get("episodes"):
        v = " ".join(raw["episodes"]).strip()
        number, label = _parse_episode_count(v)
        if number <= 0:
            invalid.append("Qism — raqam kiriting (masalan: 24 yoki \"24 qism 2-fasl\")")
        else:
            data["episodes"] = number
            data["episodes_label"] = label

    if raw.get("rating"):
        v = " ".join(raw["rating"]).strip()
        try:
            r = float(v.replace(",", "."))
            if not (0 <= r <= 10):
                raise ValueError
            data["rating"] = r
        except ValueError:
            invalid.append("Reyting — 0 dan 10 gacha raqam yozing (masalan: 8.5)")

    if raw.get("status"):
        v = " ".join(raw["status"]).strip().lower()
        status_key = _STATUS_ALIASES.get(v)
        if status_key:
            data["status"] = status_key
        else:
            invalid.append("Holat — quyidagilardan birini yozing: davom etmoqda / tugagan / tez orada / tanaffusda")

    missing = [f for f in _REQUIRED_BULK_FIELDS if f not in data]
    return data, missing, invalid

async def got_anime_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text or ""
    data, missing, invalid = _parse_anime_bulk(txt)

    if missing or invalid:
        lines = [f"• {_FIELD_DISPLAY[f]} — topilmadi, shu ma'lumotni yuboring" for f in missing]
        lines += [f"• {msg}" for msg in invalid]
        await update.message.reply_text(
            "❗ Quyidagilar to'liq emas yoki noto'g'ri:\n\n" + "\n".join(lines) + "\n\n" + _BULK_TEMPLATE,
            parse_mode="Markdown", reply_markup=_cancel_kb()
        )
        return WAIT_ANIME_BULK

    context.user_data["new_anime_name"] = data["name"]
    context.user_data["new_anime_original"] = data.get("original")
    context.user_data["new_anime_year"] = data.get("year", 0)
    context.user_data["new_anime_genre"] = data["genre"]
    context.user_data["new_anime_desc"] = data.get("desc", "")
    context.user_data["new_anime_episodes"] = data["episodes"]
    context.user_data["new_anime_episodes_label"] = data.get("episodes_label")
    context.user_data["new_anime_rating"] = data.get("rating")
    context.user_data["new_anime_status"] = data["status"]

    matches = find_animes_by_name(data["name"])
    if matches:
        lines = "\n".join(f"• {code} — {_esc_md(name)}" for code, name in matches)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, baribir qo'shish", callback_data="dupanime_yes"),
            InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="cancel_anime"),
        ]])
        await update.message.reply_text(
            f"⚠️ *Diqqat!* Shu nomga o'xshash anime(lar) bazada allaqachon bor:\n\n{lines}\n\n"
            f"Baribir yangi qo'shishni davom ettirasizmi?",
            parse_mode="Markdown",
            reply_markup=kb
        )
        return WAIT_ANIME_BULK

    await update.message.reply_text(
        "3️⃣ Poster rasm yoki video yuboring:\n_(rasm yoki video fayl yuborishingiz mumkin)_",
        parse_mode="Markdown", reply_markup=_cancel_kb()
    )
    return WAIT_ANIME_POSTER

async def got_anime_bulk_dup_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👍 Davom etyapmiz.")
    await query.message.reply_text(
        "3️⃣ Poster rasm yoki video yuboring:\n_(rasm yoki video fayl yuborishingiz mumkin)_",
        parse_mode="Markdown", reply_markup=_cancel_kb()
    )
    return WAIT_ANIME_POSTER

async def got_anime_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo and not update.message.video:
        await update.message.reply_text(
            "⚠️ Faqat *rasm yoki video* yuboring:",
            parse_mode="Markdown", reply_markup=_cancel_kb()
        )
        return WAIT_ANIME_POSTER
    if update.message.video:
        poster_id = update.message.video.file_id
        poster_type = "video"
    else:
        poster_id = update.message.photo[-1].file_id
        poster_type = "photo"

    d = context.user_data
    status_key = d.get("new_anime_status")
    ep_label = d.get("new_anime_episodes_label")
    try:
        add_anime(
            d["new_anime_code"], d["new_anime_name"], d.get("new_anime_year", 0),
            d["new_anime_genre"], d["new_anime_episodes"], d.get("new_anime_desc", ""), poster_id,
            poster_type=poster_type, total_episodes_label=ep_label,
            original_title=d.get("new_anime_original"), rating=d.get("new_anime_rating")
        )
        set_anime_status(d["new_anime_code"], status_key)
        add_season(
            d["new_anime_code"], 1, poster_id, d["new_anime_episodes"],
            poster_type=poster_type, total_episodes_label=ep_label
        )
        ep_display = _episode_label(d["new_anime_episodes"], ep_label)
        extra_lines = []
        if d.get("new_anime_original"):
            extra_lines.append(f"🔤 Original: {d['new_anime_original']}")
        if d.get("new_anime_year"):
            extra_lines.append(f"📅 Yil: {d['new_anime_year']}")
        if d.get("new_anime_rating") is not None:
            extra_lines.append(f"⭐ Reyting: {d['new_anime_rating']}")
        extra_text = ("\n".join(extra_lines) + "\n") if extra_lines else ""
        await update.message.reply_text(
            f"✅ Anime muvaffaqiyatli qo'shildi!\n\n"
            f"📌 Kod: {d['new_anime_code']}\n"
            f"🎬 Nom: {d['new_anime_name']}\n"
            f"{extra_text}"
            f"🎭 Janr: {d['new_anime_genre']}\n"
            f"📺 Qismlar: {ep_display} ta\n"
            f"🏷 Holati: {ANIME_STATUSES.get(status_key, '')}\n\n"
            f"ℹ️ Kanalga yuborish uchun 📤 Kanalga Yuborish tugmasidan foydalaning.",
            reply_markup=admin_menu_keyboard(update.effective_user.id)
        )
    except Exception as e:
        logger.warning(f"Anime qo'shishda xato: {e}")
        await update.message.reply_text(
            f"❌ Anime saqlashda xato yuz berdi:\n{e}",
            reply_markup=admin_menu_keyboard(update.effective_user.id)
        )
    context.user_data.clear()
    return ConversationHandler.END

# -- ADD EPISODE --
def _done_ep_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Hozircha tugatish", callback_data="done_episodes")]])

async def recent_episodes_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'🆕 Yangi Qismlar' — so'nggi 36 soatda qo'shilgan qismlarni ko'rsatadi (bot ichida, kanalga tegishli emas)."""
    recent = get_recent_episodes(hours=36)
    if not recent:
        await update.effective_message.reply_text("🆕 Hozircha so'nggi 36 soatda yangi qism qo'shilmagan.")
        return
    buttons = []
    seen_codes = []
    for anime_code, ep_num, added_at, name in recent:
        label = f"{name} — {ep_num}-qism"
        buttons.append([InlineKeyboardButton(label, callback_data=f"recep_{anime_code}")])
        if anime_code not in seen_codes:
            seen_codes.append(anime_code)
    await update.effective_message.reply_text(
        "🆕 *So'nggi 36 soatda qo'shilgan qismlar:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def recent_episode_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = int(query.data[6:])
    await send_anime_info(context.bot, query.from_user.id, code)

# -- ADMIN: YANGI QISMLAR (kanalga xabar yuborish uchun) --
RECENT_EP_PAGE_SIZE = 15

def _recent_ep_page_kb(grouped, page):
    start = page * RECENT_EP_PAGE_SIZE
    chunk = grouped[start:start + RECENT_EP_PAGE_SIZE]
    buttons = [
        [InlineKeyboardButton(f"🎬 {name} — {season_num}-fasl — {count} ta yangi qism", callback_data=f"annep_{code}_{season_num}")]
        for code, name, season_num, count, total_ep, ep_label in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"annpage_{page-1}"))
    if start + RECENT_EP_PAGE_SIZE < len(grouped):
        nav.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"annpage_{page+1}"))
    if nav:
        buttons.append(nav)
    return buttons

async def admin_recent_episodes_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    grouped = get_recent_episode_counts(hours=36)
    if not grouped:
        await update.message.reply_text("🆕 Hozircha so'nggi 36 soatda yangi qism qo'shilmagan.")
        return
    # Eng yangi qo'shilganlari birinchi ko'rinishi uchun teskari tartibga solamiz
    grouped = list(reversed(grouped))
    total_pages = (len(grouped) - 1) // RECENT_EP_PAGE_SIZE + 1
    await update.message.reply_text(
        f"🆕 *So'nggi 36 soatda yangi qism qo'shilgan animelar* (1/{total_pages}-sahifa)\n\n"
        "Kanalga xabar berish uchun animeni tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(_recent_ep_page_kb(grouped, 0))
    )

async def recent_ep_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    page = int(query.data.split("_")[1])
    grouped = list(reversed(get_recent_episode_counts(hours=36)))
    total_pages = (len(grouped) - 1) // RECENT_EP_PAGE_SIZE + 1
    await query.message.edit_text(
        f"🆕 *So'nggi 36 soatda yangi qism qo'shilgan animelar* ({page+1}/{total_pages}-sahifa)\n\n"
        "Kanalga xabar berish uchun animeni tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(_recent_ep_page_kb(grouped, page))
    )

async def admin_new_episode_channel_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(update.effective_user.id):
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    _, code_str, season_num_str = query.data.split("_")
    code, season_num = int(code_str), int(season_num_str)
    grouped = {(c, sn): (name, count, total_ep, ep_label) for c, name, sn, count, total_ep, ep_label in get_recent_episode_counts(hours=36)}
    key = (code, season_num)
    if key not in grouped:
        await query.answer("❌ Bu anime endi ro'yxatda yo'q (36 soat o'tgan bo'lishi mumkin).", show_alert=True)
        return
    name, count, total_ep, ep_label = grouped[key]
    await query.answer()
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data=f"annepimg_yes_{code}_{season_num}"),
        InlineKeyboardButton("❌ Yo'q", callback_data=f"annepimg_no_{code}_{season_num}"),
    ]])
    await query.message.reply_text(
        f"🖼 *{_esc_md(name)}* — {season_num}-fasl uchun rasm/video yubormoqchimisiz?\n"
        f"_(\"Yo'q\" desangiz, shu faslning saqlangan posteri bilan yuboriladi)_",
        parse_mode="Markdown",
        reply_markup=kb
    )

async def admin_new_episode_image_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(update.effective_user.id):
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    # callback_data: annepimg_yes_{code}_{season_num} yoki annepimg_no_{code}_{season_num}
    _, choice, code_str, season_num_str = query.data.split("_")
    code, season_num = int(code_str), int(season_num_str)
    grouped = {(c, sn): (name, count, total_ep, ep_label) for c, name, sn, count, total_ep, ep_label in get_recent_episode_counts(hours=36)}
    key = (code, season_num)
    if key not in grouped:
        await query.answer("❌ Bu anime endi ro'yxatda yo'q (36 soat o'tgan bo'lishi mumkin).", show_alert=True)
        return
    name, count, total_ep, ep_label = grouped[key]
    await query.answer()

    if choice == "yes":
        context.user_data["awaiting_episode_poster"] = {
            "code": code, "season_num": season_num, "count": count,
            "total_ep": total_ep, "ep_label": ep_label, "name": name,
        }
        await query.message.edit_text(
            f"🖼 *{_esc_md(name)}* — {season_num}-fasl uchun kanalga yuboriladigan rasm yoki video yuboring:",
            parse_mode="Markdown"
        )
        return

    # choice == "no" — faslning saqlangan posteri bilan darhol yuboriladi
    season = get_season(code, season_num)
    if not season or not season[2]:
        await query.message.edit_text(
            f"⚠️ *{_esc_md(name)}* — {season_num}-fasl uchun saqlangan poster topilmadi. "
            f"Iltimos rasm yoki video yuboring.",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_episode_poster"] = {
            "code": code, "season_num": season_num, "count": count,
            "total_ep": total_ep, "ep_label": ep_label, "name": name,
        }
        return
    season_id, poster_id, poster_type = season[0], season[2], season[4]
    await query.message.edit_text(
        f"⏳ *{_esc_md(name)}* — {season_num}-fasl saqlangan poster bilan kanalga yuborilmoqda...",
        parse_mode="Markdown"
    )
    ok, err = await _send_new_episode_to_channel(context.bot, code, season_id, poster_id, poster_type, name, total_ep=total_ep, ep_label=ep_label)
    if ok:
        await query.message.reply_text(
            f"✅ Kanalga yuborildi: *{_esc_md(name)}* — {count} ta yangi qism.",
            parse_mode="Markdown"
        )
    else:
        logger.warning(f"Kanalga yangi qism xabarini yuborishda xato: {err}")
        await query.message.reply_text(f"❌ Kanalga yuborilmadi: {err}")

async def _send_new_episode_to_channel(bot, code, season_id, poster_id, poster_type, name, total_ep=None, ep_label=None):
    """Kanalga 'yangi qism' postini yuboradi. Qismlar soni sifatida
    'jami/yuklangan' (masalan 12/8) ko'rsatiladi — jami e'lon qilingan son
    va bazaga haqiqatan yuklangan qismlar soni."""
    watch_url = f"https://t.me/{BOT_USERNAME}?start={code}"
    uploaded_count = len(get_episodes_list(season_id))
    if total_ep:
        total_display = _episode_label(total_ep, ep_label)
        ep_count_text = f"{total_display}/{uploaded_count}"
    else:
        ep_count_text = str(uploaded_count)
    caption = (
        f"🆕 *Yangi qism qo'shildi!*\n\n"
        f"🎬 {_esc_md(name)}\n"
        f"📺 Qism: {ep_count_text}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💥 Tomosha qilish 💥", url=watch_url)]])
    try:
        if poster_type == "video":
            await bot.send_video(
                chat_id=CHANNEL_USERNAME, video=poster_id,
                caption=caption, parse_mode="Markdown", reply_markup=kb
            )
        else:
            await bot.send_photo(
                chat_id=CHANNEL_USERNAME, photo=poster_id,
                caption=caption, parse_mode="Markdown", reply_markup=kb
            )
        return True, None
    except Exception as e:
        return False, e

async def got_episode_channel_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    info = context.user_data.get("awaiting_episode_poster")
    if not info:
        return
    if not update.message.photo and not update.message.video:
        await update.message.reply_text("⚠️ Faqat rasm yoki video yuboring:")
        return
    if update.message.video:
        poster_id = update.message.video.file_id
        poster_type = "video"
    else:
        poster_id = update.message.photo[-1].file_id
        poster_type = "photo"
    context.user_data.pop("awaiting_episode_poster", None)
    code = info["code"]
    season_num = info["season_num"]
    count = info["count"]
    name = info["name"]
    total_ep = info.get("total_ep")
    ep_label = info.get("ep_label")
    season = get_season(code, season_num)
    if not season:
        await update.message.reply_text("❌ Bu fasl endi topilmadi.")
        return
    season_id = season[0]
    ok, err = await _send_new_episode_to_channel(context.bot, code, season_id, poster_id, poster_type, name, total_ep=total_ep, ep_label=ep_label)
    if ok:
        await update.message.reply_text(
            f"✅ Kanalga yuborildi: *{_esc_md(name)}* — {count} ta yangi qism.",
            parse_mode="Markdown"
        )
    else:
        logger.warning(f"Kanalga yangi qism xabarini yuborishda xato: {err}")
        await update.message.reply_text(f"❌ Kanalga yuborilmadi: {err}")


async def done_episodes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'✅ Hozircha tugatish' bosilganda — avval tasdiqlash so'raladi."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    name = context.user_data.get("ep_anime_name", "")
    count = context.user_data.get("ep_added_count", 0)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="done_ep_yes"),
        InlineKeyboardButton("❌ Yo'q", callback_data="done_ep_no"),
    ]])
    await query.message.reply_text(
        f"❗️ Rostdan ham yuklashni tugatmoqchimisiz?\n\n"
        f"🎬 Anime: {name}\n"
        f"📺 Hozircha qo'shilgan: *{count} ta* qism",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPISODE_VIDEO

async def done_episodes_confirm_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    name = context.user_data.get("ep_anime_name", "")
    count = context.user_data.get("ep_added_count", 0)
    notify_nums = list(context.user_data.get("ep_added_nums", []))
    notify_code = context.user_data.get("ep_anime_code")
    notify_season = context.user_data.get("ep_season_num")
    context.user_data.clear()
    if notify_nums and notify_code is not None and notify_season is not None:
        # Kuzatuvchilarga xabar fon vazifasida yuboriladi — bot bloklanmaydi.
        context.application.create_task(
            _run_watch_notify(context.bot, update.effective_chat.id, notify_code, notify_season, notify_nums)
        )
    await query.edit_message_text(
        f"✅ *Qism qo'shish yakunlandi!*\n\n"
        f"🎬 Anime: {name}\n"
        f"📺 Qo'shilgan qismlar: *{count} ta*",
        parse_mode="Markdown"
    )
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def done_episodes_confirm_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("👍 Davom eting, videolarni yuborishda davom etishingiz mumkin.")
    return WAIT_EPISODE_VIDEO

# -- QISM BOSHQARISH (o'chirish / raqam o'zgartirish) --
async def epm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    animes = get_all_animes()
    if not animes:
        await update.message.reply_text("❌ Hali anime qo'shilmagan!")
        return ConversationHandler.END
    context.user_data.clear()
    header = "🛠 *Qism boshqarish*\n\nMavjud animeler:\n"
    chunk = header
    for a in animes:
        line = f"*{a[0]}* — {_esc_md(a[1])}\n"
        # Telegram xabar chegarasi (4096 belgi) dan oshib ketmasligi uchun bo'laklarga bo'lib yuboramiz
        if len(chunk) + len(line) > 3500:
            await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            chunk = ""
        chunk += line
    chunk += "\nAnime kodini yuboring:"
    await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return WAIT_EPM_ANIME

async def got_epm_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("⚠️ Faqat raqam (kod) yuboring!")
        return WAIT_EPM_ANIME
    code = int(txt)
    anime = get_anime_by_code(code)
    if not anime:
        await update.message.reply_text("⚠️ Bunday anime topilmadi! Kodini qayta yuboring:")
        return WAIT_EPM_ANIME
    seasons = get_seasons(code)
    if not seasons:
        await update.message.reply_text("❌ Bu animeda hali fasl/qism yo'q.")
        return ConversationHandler.END
    context.user_data["epm_code"] = code
    context.user_data["epm_name"] = anime[2]
    buttons = [
        [InlineKeyboardButton(f"{_season_label(snum, total_ep)} ({len(get_episodes_list(sid))} ta qism)", callback_data=f"epmseason_{sid}")]
        for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons
    ]
    buttons.append([InlineKeyboardButton("🗑 Anime bo'yicha barcha qismlarni o'chirish", callback_data="epm_allanime")])
    await update.message.reply_text(
        f"🛠 *{_esc_md(anime[2])}*\n\nQaysi faslni boshqarmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_EPM_ANIME

async def epm_season_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = int(query.data[10:])
    season = get_season_by_id(season_id)
    if not season:
        await query.edit_message_text("❌ Bu fasl endi topilmadi.")
        return ConversationHandler.END
    _, anime_code, season_num, poster_id, total_ep, *_rest = season
    episodes = get_episodes_list(season_id)
    if not episodes:
        await query.edit_message_text("❌ Bu faslda hali qism yo'q.")
        return ConversationHandler.END
    context.user_data["epm_season_id"] = season_id
    context.user_data["epm_season_num"] = season_num
    name = context.user_data.get("epm_name", "")
    await query.edit_message_text(
        f"🛠 *{_esc_md(name)}* — *{season_num}-fasl*\n\nQaysi qism ustida amal bajarasiz?",
        parse_mode="Markdown",
        reply_markup=_epm_list_kb(episodes, 0)
    )
    return WAIT_EPM_ACTION

EPM_PAGE_SIZE = 30  # bir sahifada ko'rsatiladigan qismlar soni

def _epm_paginate(episodes, page):
    total_pages = max(1, (len(episodes) + EPM_PAGE_SIZE - 1) // EPM_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * EPM_PAGE_SIZE
    return episodes[start:start + EPM_PAGE_SIZE], page, total_pages

def _epm_nav_row(page, total_pages, prefix):
    if total_pages <= 1:
        return None
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"{prefix}{page - 1}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="epm_noop"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("➡️", callback_data=f"{prefix}{page + 1}"))
    return row

def _epm_list_kb(episodes, page=0):
    page_eps, page, total_pages = _epm_paginate(episodes, page)
    buttons = []
    row = []
    for ep in page_eps:
        row.append(InlineKeyboardButton(str(ep), callback_data=f"epm_sel_{ep}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = _epm_nav_row(page, total_pages, "epm_pg_")
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("☑️ Bir nechta qismni tanlash", callback_data="epm_multi")])
    buttons.append([InlineKeyboardButton("🗑 Faslning barcha qismlarini o'chirish", callback_data="epm_allseason")])
    return InlineKeyboardMarkup(buttons)

async def epm_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    page = int(query.data[len("epm_pg_"):])
    episodes = get_episodes_list(context.user_data.get("epm_season_id"))
    await query.edit_message_reply_markup(reply_markup=_epm_list_kb(episodes, page))
    return WAIT_EPM_ACTION

async def epm_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    return WAIT_EPM_ACTION

async def epm_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    ep_num = int(query.data[8:])
    context.user_data["epm_num"] = ep_num
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 O'chirish", callback_data=f"epm_del_{ep_num}")],
        [InlineKeyboardButton("🔢 Raqamini o'zgartirish", callback_data=f"epm_ren_{ep_num}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="epm_cancel")],
    ])
    name = context.user_data.get("epm_name", "")
    season_num = context.user_data.get("epm_season_num")
    label = f"{name} — {season_num}-fasl" if season_num else name
    await query.edit_message_text(
        f"🛠 *{_esc_md(label)}* — *{ep_num}-qism*\n\nQaysi amalni bajarasiz?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPM_ACTION

async def epm_delete_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    ep_num = int(query.data[8:])
    name = context.user_data.get("epm_name", "")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data=f"epm_delyes_{ep_num}"),
        InlineKeyboardButton("❌ Yo'q", callback_data="epm_cancel"),
    ]])
    await query.edit_message_text(
        f"❗️ Rostdan ham *{_esc_md(name)}* — *{ep_num}-qismni* o'chirmoqchimisiz?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPM_ACTION

async def epm_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    ep_num = int(query.data[11:])
    season_id = context.user_data.get("epm_season_id")
    name = context.user_data.get("epm_name", "")
    delete_episode(season_id, ep_num)
    context.user_data.clear()
    await query.edit_message_text(f"✅ *{_esc_md(name)}* — *{ep_num}-qism* o'chirildi!", parse_mode="Markdown")
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

def _epm_multi_kb(episodes, selected, page=0):
    page_eps, page, total_pages = _epm_paginate(episodes, page)
    buttons = []
    row = []
    for ep in page_eps:
        label = f"✅ {ep}" if ep in selected else str(ep)
        row.append(InlineKeyboardButton(label, callback_data=f"epm_tgl_{ep}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    nav = _epm_nav_row(page, total_pages, "epm_mpg_")
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(f"🗑 O'chirish ({len(selected)} ta)", callback_data="epm_selgo")])
    buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="epm_cancel")])
    return InlineKeyboardMarkup(buttons)

async def epm_multi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = context.user_data.get("epm_season_id")
    episodes = get_episodes_list(season_id)
    if not episodes:
        await query.edit_message_text("❌ Bu faslda hali qism yo'q.")
        return ConversationHandler.END
    context.user_data["epm_selected"] = []
    context.user_data["epm_mpage"] = 0
    name = context.user_data.get("epm_name", "")
    season_num = context.user_data.get("epm_season_num")
    await query.edit_message_text(
        f"☑️ *{_esc_md(name)}* — *{season_num}-fasl*\n\n"
        f"O'chirmoqchi bo'lgan qismlarni tanlang (qayta bossangiz tanlov bekor bo'ladi):",
        parse_mode="Markdown",
        reply_markup=_epm_multi_kb(episodes, [])
    )
    return WAIT_EPM_ACTION

async def epm_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    ep_num = int(query.data[len("epm_tgl_"):])
    selected = list(context.user_data.get("epm_selected", []))
    if ep_num in selected:
        selected.remove(ep_num)
    else:
        selected.append(ep_num)
    context.user_data["epm_selected"] = selected
    episodes = get_episodes_list(context.user_data.get("epm_season_id"))
    await query.edit_message_reply_markup(
        reply_markup=_epm_multi_kb(episodes, selected, context.user_data.get("epm_mpage", 0))
    )
    return WAIT_EPM_ACTION

async def epm_multipage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    page = int(query.data[len("epm_mpg_"):])
    context.user_data["epm_mpage"] = page
    selected = list(context.user_data.get("epm_selected", []))
    episodes = get_episodes_list(context.user_data.get("epm_season_id"))
    await query.edit_message_reply_markup(reply_markup=_epm_multi_kb(episodes, selected, page))
    return WAIT_EPM_ACTION

async def epm_selected_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    selected = sorted(context.user_data.get("epm_selected", []))
    if not selected:
        await query.answer("Avval o'chiriladigan qismlarni tanlang.", show_alert=True)
        return WAIT_EPM_ACTION
    await query.answer()
    name = context.user_data.get("epm_name", "")
    season_num = context.user_data.get("epm_season_num")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="epm_selyes"),
        InlineKeyboardButton("❌ Yo'q", callback_data="epm_cancel"),
    ]])
    await query.edit_message_text(
        f"❗️ Rostdan ham *{_esc_md(name)}* — *{season_num}-fasl*dan quyidagi qismlarni o'chirmoqchimisiz?\n\n"
        f"{', '.join(str(n) for n in selected)}",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPM_ACTION

async def epm_selected_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = context.user_data.get("epm_season_id")
    selected = sorted(context.user_data.get("epm_selected", []))
    name = context.user_data.get("epm_name", "")
    deleted = delete_episodes(season_id, selected)
    context.user_data.clear()
    await query.edit_message_text(
        f"✅ *{_esc_md(name)}*: {deleted} ta qism o'chirildi ({', '.join(str(n) for n in selected)}).",
        parse_mode="Markdown"
    )
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def epm_allseason_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = context.user_data.get("epm_season_id")
    name = context.user_data.get("epm_name", "")
    season_num = context.user_data.get("epm_season_num")
    count = len(get_episodes_list(season_id))
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="epm_allseasonyes"),
        InlineKeyboardButton("❌ Yo'q", callback_data="epm_cancel"),
    ]])
    await query.edit_message_text(
        f"❗️ Rostdan ham *{_esc_md(name)}* — *{season_num}-fasl*ning barcha *{count} ta qismini* o'chirmoqchimisiz?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPM_ACTION

async def epm_allseason_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = context.user_data.get("epm_season_id")
    season_num = context.user_data.get("epm_season_num")
    name = context.user_data.get("epm_name", "")
    deleted = delete_season_episodes(season_id)
    context.user_data.clear()
    await query.edit_message_text(
        f"✅ *{_esc_md(name)}* — *{season_num}-fasl*: {deleted} ta qism o'chirildi.",
        parse_mode="Markdown"
    )
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def epm_allanime_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    code = context.user_data.get("epm_code")
    if not code:
        await query.answer("Jarayon eskirgan. Qayta boshlang.", show_alert=True)
        return ConversationHandler.END
    count = sum(len(get_episodes_list(s[0])) for s in get_seasons(code))
    if count == 0:
        await query.answer("Bu animeda o'chiriladigan qism yo'q.", show_alert=True)
        return WAIT_EPM_ANIME
    await query.answer()
    name = context.user_data.get("epm_name", "")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha", callback_data="epm_allanimeyes"),
        InlineKeyboardButton("❌ Yo'q", callback_data="epm_cancel"),
    ]])
    await query.edit_message_text(
        f"❗️ Rostdan ham *{_esc_md(name)}* animening barcha fasllaridagi jami *{count} ta qismini* o'chirmoqchimisiz?",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_EPM_ACTION

async def epm_allanime_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    code = context.user_data.get("epm_code")
    name = context.user_data.get("epm_name", "")
    deleted = delete_anime_episodes(code) if code else 0
    context.user_data.clear()
    await query.edit_message_text(
        f"✅ *{_esc_md(name)}*: jami {deleted} ta qism o'chirildi.",
        parse_mode="Markdown"
    )
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def epm_rename_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    ep_num = int(query.data[8:])
    context.user_data["epm_num"] = ep_num
    await query.edit_message_text(
        f"🔢 *{ep_num}-qism* uchun yangi raqamni yuboring:",
        parse_mode="Markdown"
    )
    return WAIT_EPM_NEWNUM

async def got_epm_newnum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt.isdigit() or int(txt) <= 0:
        await update.message.reply_text("⚠️ Faqat musbat raqam yuboring:")
        return WAIT_EPM_NEWNUM
    new_num = int(txt)
    season_id = context.user_data.get("epm_season_id")
    old_num = context.user_data.get("epm_num")
    name = context.user_data.get("epm_name", "")
    if new_num == old_num:
        await update.message.reply_text("⚠️ Bu allaqachon shu raqam. Boshqa raqam yuboring:")
        return WAIT_EPM_NEWNUM
    existing = get_episodes_list(season_id)
    if new_num in existing:
        await update.message.reply_text(f"⚠️ *{new_num}-qism* raqami band. Boshqa raqam yuboring:", parse_mode="Markdown")
        return WAIT_EPM_NEWNUM
    update_episode_number(season_id, old_num, new_num)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ *{_esc_md(name)}*: {old_num}-qism → *{new_num}-qism* qilib o'zgartirildi!",
        parse_mode="Markdown",
        reply_markup=admin_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END

async def epm_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("❌ Bekor qilindi.")
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def add_episode_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    animes = get_all_animes()
    if not animes:
        await update.message.reply_text("❌ Hali anime qo'shilmagan!")
        return ConversationHandler.END
    incomplete = []
    for code, name, year, genre, total_ep in animes:
        seasons = get_seasons(code)
        if not seasons:
            incomplete.append((code, name))
            continue
        for sid, snum, poster_id, s_total, poster_type, ep_label in seasons:
            added = len(get_episodes_list(sid))
            if added < s_total:
                incomplete.append((code, name))
                break
    if not incomplete:
        await update.message.reply_text(
            "✅ Barcha animelarning barcha fasllariga qismlar to'liq qo'shilgan!\n\n"
            "Yangi fasl qo'shish uchun baribir istalgan anime kodini yuboring:",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text("👇", reply_markup=_cancel_kb())
        context.user_data.clear()
        return WAIT_EPISODE_ANIME
    context.user_data.clear()
    lines = "\n".join(f"*{code}* — {_esc_md(name)}" for code, name in incomplete)
    await update.message.reply_text(
        f"📺 *Qism qo'shish*\n\nQismi to'liq bo'lmagan animeler:\n{lines}\n\n1️⃣ Anime kodini yuboring:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("👇", reply_markup=_cancel_kb())
    return WAIT_EPISODE_ANIME

async def anime_status_list_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    ongoing = get_animes_by_status("ongoing")
    if not ongoing:
        await update.message.reply_text("✅ Hozircha \"🟢 Davom etmoqda\" holatidagi anime yo'q.")
        return ConversationHandler.END
    buttons = [
        [InlineKeyboardButton(f"{code} — {name}", callback_data=f"quickep_{code}")]
        for code, name in ongoing
    ]
    await update.message.reply_text(
        "🏷 *Davom etmoqda* holatidagi animelar:\n\nQism qo'shish uchun animeni tanlang:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ConversationHandler.END

async def quick_episode_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return ConversationHandler.END
    code = int(query.data.split("_")[1])
    anime = get_anime_by_code(code)
    if not anime:
        await query.message.reply_text("❌ Bu anime endi topilmadi.")
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["ep_anime_code"] = code
    context.user_data["ep_anime_name"] = anime[2]
    return await _show_season_picker(query.message, context, code, anime[2])

async def _show_season_picker(message, context, code, anime_name):
    seasons = get_seasons(code)
    buttons = []
    for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons:
        added = len(get_episodes_list(sid))
        label = _episode_label(total_ep, ep_label)
        buttons.append([InlineKeyboardButton(f"{_season_label(snum, total_ep)} ({added}/{label})", callback_data=f"epseason_{sid}")])
    buttons.append([InlineKeyboardButton("➕ Yangi fasl qo'shish", callback_data="epseason_new")])
    await message.reply_text(
        f"✅ Anime: *{_esc_md(anime_name)}*\n\nQaysi faslga qism qo'shmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_EPISODE_NUM

async def got_episode_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text("⚠️ Faqat raqam (kod) yuboring!")
        return WAIT_EPISODE_ANIME
    code = int(txt)
    anime = get_anime_by_code(code)
    if not anime:
        await update.message.reply_text("⚠️ Bunday anime topilmadi! Kodini qayta yuboring:")
        return WAIT_EPISODE_ANIME
    context.user_data["ep_anime_code"] = code
    context.user_data["ep_anime_name"] = anime[2]
    return await _show_season_picker(update.message, context, code, anime[2])

async def got_episode_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tanlangan anime qismlarining video cover’ini qabul qiladi."""
    if not update.message.photo:
        await update.message.reply_text("⚠️ Faqat rasm yuboring. Shu rasm qism videosining cover’i bo‘ladi:")
        return WAIT_EPISODE_POSTER
    poster_id = update.message.photo[-1].file_id
    code = context.user_data.get("ep_anime_code")
    anime_name = context.user_data.get("ep_anime_name", "")
    season_id = context.user_data.get("ep_season_id")
    if not code:
        await update.message.reply_text("⚠️ Avval anime kodini tanlang.")
        return ConversationHandler.END
    context.user_data["ep_poster_id"] = poster_id
    context.user_data["ep_poster_type"] = "photo"
    if season_id:
        set_season_episode_cover(season_id, poster_id)
        season_num = context.user_data.get("ep_season_num", 1)
        next_num = context.user_data.get("ep_next_num", 1)
        await update.message.reply_text(
            f"✅ *{_esc_md(anime_name)}* — {season_num}-fasl qismlari uchun cover saqlandi.\n\n"
            f"Videolarni *{next_num}-qism*dan boshlab yuklashingiz mumkin:",
            parse_mode="Markdown",
            reply_markup=_season_upload_ready_kb()
        )
        return WAIT_EPISODE_NUM
    await update.message.reply_text(
        "⚠️ Cover faqat aniq faslga saqlanadi. Avval faslni tanlang:",
        parse_mode="Markdown"
    )
    return await _show_season_picker(update.message, context, code, anime_name)

def _season_upload_ready_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Qism yuklash", callback_data="ep_upload_start")],
        [InlineKeyboardButton("✅ Hozircha tugatish", callback_data="done_episodes")],
    ])

async def epseason_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    season_id = int(query.data[9:])
    season = get_season_by_id(season_id)
    if not season:
        await query.edit_message_text("❌ Bu fasl endi topilmadi.")
        return ConversationHandler.END
    _, anime_code, season_num, poster_id, total_ep, *_rest = season
    context.user_data["ep_season_id"] = season_id
    context.user_data["ep_season_num"] = season_num
    context.user_data["ep_added_count"] = 0
    context.user_data["ep_added_nums"] = []
    existing = get_episodes_list(season_id)
    next_num = get_next_free_episode_num(season_id)
    context.user_data["ep_next_num"] = next_num
    existing_str = ", ".join(str(e) for e in existing) if existing else "Yo'q"
    info_text = (
        f"✅ Anime: *{_esc_md(context.user_data.get('ep_anime_name', ''))}*\n"
        f"🎬 Fasl: *{season_num}*\n"
        f"📌 Mavjud qismlar: {existing_str}\n"
        f"➡️ Keyingi qism *{next_num}*-dan boshlanadi.\n\n"
    )
    if get_season_episode_cover(season_id):
        # Bu faslning coveri allaqachon saqlangan — qayta so'ralmaydi.
        await query.edit_message_text(
            info_text + "🖼 Shu faslning cover'i saqlangan. Videolarni yuklashingiz mumkin:",
            parse_mode="Markdown",
            reply_markup=_season_upload_ready_kb()
        )
        return WAIT_EPISODE_NUM
    await query.edit_message_text(
        info_text + "Endi shu fasl qismlari uchun video cover rasmni yuboring:",
        parse_mode="Markdown"
    )
    return WAIT_EPISODE_POSTER

async def epseason_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text(
        "🆕 *Yangi fasl* uchun jami qism sonini yuboring _(masalan: 24)_:",
        parse_mode="Markdown"
    )
    return WAIT_NEWSEASON_EPISODES

async def got_newseason_episodes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt:
        await update.message.reply_text("⚠️ Bo'sh yuborildi. Qism sonini yozing (masalan: 24 yoki \"24 qism 2-fasl\"):")
        return WAIT_NEWSEASON_EPISODES
    number, label = _parse_episode_count(txt)
    context.user_data["new_season_total"] = number
    context.user_data["new_season_total_label"] = label
    await update.message.reply_text(
        "🖼 Endi yangi faslning *asosiy poster rasmini* yuboring. "
        "Bu rasm fasl kartasida chiqadi:",
        parse_mode="Markdown"
    )
    return WAIT_NEWSEASON_POSTER

async def got_newseason_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi faslning katta posterini qabul qilib, keyin qism cover’ini so‘raydi."""
    if not update.message.photo:
        await update.message.reply_text("⚠️ Faqat rasm yuboring. Bu yangi faslning asosiy posteri bo‘ladi:")
        return WAIT_NEWSEASON_POSTER
    season_poster_id = update.message.photo[-1].file_id
    code = context.user_data.get("ep_anime_code")
    total_ep = context.user_data.get("new_season_total", 0)
    ep_label = context.user_data.get("new_season_total_label")
    if not code:
        await update.message.reply_text("⚠️ Anime topilmadi. Jarayonni qayta boshlang.")
        return ConversationHandler.END
    seasons = get_seasons(code)
    next_season_num = (max(s[1] for s in seasons) + 1) if seasons else 1
    season_id = add_season(
        code, next_season_num, season_poster_id, total_ep,
        poster_type="photo", total_episodes_label=ep_label
    )
    context.user_data["ep_season_id"] = season_id
    context.user_data["ep_season_num"] = next_season_num
    context.user_data["ep_added_count"] = 0
    context.user_data["ep_added_nums"] = []
    context.user_data["ep_next_num"] = 1
    ep_display = _episode_label(total_ep, ep_label)
    global_cover = get_global_episode_cover()
    if global_cover:
        set_season_episode_cover(season_id, global_cover)
        await update.message.reply_text(
            f"✅ *{next_season_num}-fasl* yaratildi! ({ep_display} ta qism e'lon qilindi)\n\n"
            "🖼 Umumiy cover avtomatik qo'yildi. Videolarni *1-qism*dan boshlab yuklashingiz mumkin:",
            parse_mode="Markdown",
            reply_markup=_season_upload_ready_kb()
        )
        return WAIT_EPISODE_NUM
    await update.message.reply_text(
        f"✅ *{next_season_num}-fasl* yaratildi! ({ep_display} ta qism e'lon qilindi)\n\n"
        "🖼 Endi shu fasl qismlari uchun *video cover rasmni* yuboring:",
        parse_mode="Markdown"
    )
    return WAIT_EPISODE_POSTER

@_db_locked
def _anime_season_count(anime_code):
    conn = get_db()
    return conn.execute("SELECT COUNT(*) FROM seasons WHERE anime_code=?", (anime_code,)).fetchone()[0]

def _episode_caption(anime_name, season, ep_num):
    """Anime 2 va undan ko'p fasldan iborat bo'lsa: «2-fasl 3-qism», aks holda: «3-qism»."""
    if season and _anime_season_count(season[1]) > 1:
        return f"🎬 {anime_name} — {season[2]}-fasl {ep_num}-qism"
    return f"🎬 {anime_name} — {ep_num}-qism"

async def global_cover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cover — barcha anime qismlari uchun bitta umumiy cover o'rnatadi. /cover off — o'chiradi."""
    if not is_admin(update.effective_user.id):
        return
    if context.args and context.args[0].lower() == "off":
        context.user_data.pop("await_global_cover", None)
        clear_global_episode_cover()
        await update.message.reply_text(
            "✅ Umumiy cover o'chirildi. Hozirgi coverlar joyida qoladi, "
            "lekin yangi fasl uchun cover yana so'raladi."
        )
        return
    context.user_data["await_global_cover"] = time.time()
    note = "\nHozir umumiy cover o'rnatilgan — yangisini yuborsangiz, almashadi." if get_global_episode_cover() else ""
    await update.message.reply_text(
        "🖼 Barcha anime qismlari uchun umumiy cover rasmni yuboring "
        "(fayl emas, oddiy rasm sifatida, 10 daqiqa ichida)." + note,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cover_cancel")]])
    )

async def global_cover_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    context.user_data.pop("await_global_cover", None)
    await query.answer("Bekor qilindi")
    try:
        await query.message.edit_text("❌ Cover o'rnatish bekor qilindi.")
    except Exception:
        pass

async def global_cover_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    started = context.user_data.get("await_global_cover")
    if not started or not is_admin(update.effective_user.id):
        return
    if time.time() - started > 600:
        context.user_data.pop("await_global_cover", None)
        return
    context.user_data.pop("await_global_cover", None)
    file_id = update.message.photo[-1].file_id
    wait = await update.message.reply_text("⏳ Cover qo'yilmoqda, bot odatdagidek ishlashda davom etadi...")
    animes_count, seasons_count = await asyncio.to_thread(apply_global_episode_cover, file_id)
    await wait.edit_text(
        f"✅ Tayyor! Umumiy cover {animes_count} ta anime va {seasons_count} ta faslga qo'yildi.\n"
        "Endi barcha qism videolari shu cover bilan ketadi, yangi anime va fasl uchun cover so'ralmaydi.\n"
        "O'chirish: /cover off"
    )

async def got_episode_upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    next_num = context.user_data.get("ep_next_num", 1)
    await query.edit_message_text(
        f"🎬 Videolarni ketma-ket (yoki birdaniga) yuboring.\n\n"
        f"Men ularni *{next_num}-qismdan* boshlab, bo'sh raqamlarni ketma-ket to'ldirib belgilab, saqlab boraman.\n\n"
        f"Yuklab bo'lgach, «✅ Hozircha tugatish» tugmasini bosing.",
        parse_mode="Markdown",
        reply_markup=_done_ep_kb()
    )
    return WAIT_EPISODE_VIDEO

async def got_episode_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video and not update.message.document:
        await update.message.reply_text(
            "⚠️ Video fayl yuboring!",
            reply_markup=_done_ep_kb()
        )
        return WAIT_EPISODE_VIDEO

    file_id = update.message.video.file_id if update.message.video else update.message.document.file_id
    d = context.user_data
    season_id = d.get("ep_season_id")
    season_num = d.get("ep_season_num", 1)
    ep_num = get_next_free_episode_num(season_id)
    add_episode(season_id, ep_num, file_id)
    d["ep_added_count"] = d.get("ep_added_count", 0) + 1
    d.setdefault("ep_added_nums", []).append(ep_num)
    d["ep_next_num"] = get_next_free_episode_num(season_id)
    await update.message.reply_text(
        f"✅ *{d['ep_anime_name']} — {season_num}-fasl — {ep_num}-qism* saqlandi!\n\n"
        f"Davom eting yoki «✅ Hozircha tugatish» tugmasini bosing.",
        parse_mode="Markdown",
        reply_markup=_done_ep_kb()
    )
    return WAIT_EPISODE_VIDEO

# -- DELETE ANIME --
async def delete_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    animes = get_recent_animes(hours=48)
    if not animes:
        await update.message.reply_text(
            "❌ So'nggi 48 soatda qo'shilgan anime yo'q.\n"
            "Baribir o'chirmoqchi bo'lgan animening kodini bilsangiz, shuni yuborishingiz mumkin:",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAIT_DELETE_CODE
    header = "🗑 O'chirmoqchi bo'lgan anime kodini yuboring:\n_(faqat so'nggi 48 soatda qo'shilganlar ko'rsatilmoqda)_\n\n"
    chunk = header
    for a in animes:
        line = f"*{a[0]}* — {_esc_md(a[1])} ({a[2]})\n"
        if len(chunk) + len(line) > 3500:
            await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            chunk = ""
        chunk += line
    chunk += "\n/cancel — bekor qilish"
    await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return WAIT_DELETE_CODE

async def got_delete_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    if not update.message.text.isdigit():
        await update.message.reply_text("❌ Faqat raqam (kod) yuboring!")
        return WAIT_DELETE_CODE
    code = int(update.message.text)
    anime = get_anime_by_code(code)
    if not anime:
        await update.message.reply_text("❌ Bunday anime topilmadi! Kodini qayta yuboring:")
        return WAIT_DELETE_CODE
    context.user_data["delete_code"] = code
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ha, o'chirish", callback_data="delconfirm_yes"),
         InlineKeyboardButton("❌ Yo'q", callback_data="delconfirm_no")]
    ])
    await update.message.reply_text(
        f"❗️ *Rostdan ham o'chirmoqchimisiz?*\n\n"
        f"📌 Kod: *{anime[1]}*\n"
        f"🎬 Nom: {_esc_md(anime[2])}",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return WAIT_DELETE_CONFIRM

async def got_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = context.user_data.get("delete_code")

    if query.data == "delconfirm_no":
        context.user_data.clear()
        await query.message.edit_text("❌ Bekor qilindi, anime o'chirilmadi.")
        await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    anime = get_anime_by_code(code)
    if not anime:
        context.user_data.clear()
        await query.message.edit_text("❌ Bunday anime endi topilmadi.")
        await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    delete_anime(code)
    context.user_data.clear()
    await query.message.edit_text(f"✅ *{_esc_md(anime[2])}* o'chirildi!", parse_mode="Markdown")
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

# -- EDIT ANIME --
def _edit_fields_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Nom", callback_data="editfield_name"),
         InlineKeyboardButton("📅 Yil", callback_data="editfield_year")],
        [InlineKeyboardButton("🎭 Janr", callback_data="editfield_genre"),
         InlineKeyboardButton("📺 Qismlar", callback_data="editfield_episodes")],
        [InlineKeyboardButton("📝 Tavsif", callback_data="editfield_desc"),
         InlineKeyboardButton("🏷 Holati", callback_data="editstatus")],
        [InlineKeyboardButton("🔤 Original nom", callback_data="editfield_original"),
         InlineKeyboardButton("⭐ Reyting", callback_data="editfield_rating")],
        [InlineKeyboardButton("🖼 Poster", callback_data="editposter")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")],
    ])

EDIT_FIELD_MAP = {
    "editfield_name":     ("name",           "🎬 Yangi nomni yozing:"),
    "editfield_year":     ("year",           "📅 Yangi yilni yozing:\n_(4 xonali raqam, masalan: 2023)_"),
    "editfield_genre":    ("genre",          "🎭 Yangi janrni yozing:"),
    "editfield_episodes": ("total_episodes", "📺 Yangi qismlar sonini yozing:\n_(masalan: 24 yoki \"24 qism 2-fasl\")_"),
    "editfield_desc":     ("description",    "📝 Yangi tavsifni yozing:"),
    "editfield_original": ("original_title", "🔤 Yangi original nomni yozing:"),
    "editfield_rating":   ("rating",         "⭐ Yangi reytingni yozing:\n_(0 dan 10 gacha, masalan: 8.5)_"),
    "editfield_featured": ("is_featured",    "🌟 Tavsiya etilganmi? 1 (ha) yoki 0 (yo'q) yozing:"),
    "editfield_popular":  ("is_popular",     "🔥 Mashhurmi? 1 (ha) yoki 0 (yo'q) yozing:"),
}

async def edit_anime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    animes = get_recent_animes(hours=48)
    if not animes:
        await update.message.reply_text(
            "❌ So'nggi 48 soatda qo'shilgan anime yo'q.\n"
            "Baribir tahrirlamoqchi bo'lgan animening kodini bilsangiz, shuni yuborishingiz mumkin:",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text("👇", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]]
        ))
        return WAIT_EDIT_CODE
    header = "✏️ *Anime Tahrirlash*\n_(faqat so'nggi 48 soatda qo'shilganlar ko'rsatilmoqda)_\n\nMavjud animeler:\n"
    chunk = header
    for a in animes:
        line = f"*{a[0]}* — {_esc_md(a[1])} ({a[2]})\n"
        if len(chunk) + len(line) > 3500:
            await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            chunk = ""
        chunk += line
    chunk += "\nTahrirlamoqchi bo'lgan anime kodini yozing:"
    await update.message.reply_text(chunk, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("👇", reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]]
    ))
    return WAIT_EDIT_CODE

async def got_edit_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    if not txt.isdigit():
        await update.message.reply_text(
            "⚠️ Faqat *raqam* yuboring:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]]))
        return WAIT_EDIT_CODE
    anime = get_anime_by_code(int(txt))
    if not anime:
        await update.message.reply_text(
            "⚠️ Bunday kodli anime topilmadi. Qaytadan kiriting:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]]))
        return WAIT_EDIT_CODE
    context.user_data["edit_code"] = int(txt)
    original = anime[15] if len(anime) > 15 and anime[15] else "—"
    rating = anime[16] if len(anime) > 16 and anime[16] is not None else "—"
    status_label = ANIME_STATUSES.get(get_anime_status(int(txt)), "—")
    seasons_for_edit = get_seasons(int(txt))
    if seasons_for_edit:
        poster_info = ", ".join(
            f"{s[1]}-fasl {'✅' if s[2] else '—'}" for s in seasons_for_edit
        )
    else:
        poster_info = "fasl yo'q"
    await update.message.reply_text(
        f"✅ Topildi!\n\n"
        f"📌 Kod: *{anime[1]}*\n"
        f"🎬 Nom: {_esc_md(anime[2])}\n"
        f"🔤 Original: {_esc_md(str(original))}\n"
        f"📅 Yil: {anime[3]}\n"
        f"🎭 Janr: {anime[4]}\n"
        f"📺 Qismlar: {anime[5]} ta\n"
        f"⭐ Reyting: {rating}\n"
        f"🏷 Holati: {status_label}\n"
        f"🖼 Poster: {poster_info}\n"
        f"📝 Tavsif: {_esc_md(anime[6])}\n\n"
        f"Qaysi maydonni tahrirlaysiz?",
        parse_mode="Markdown",
        reply_markup=_edit_fields_kb()
    )
    return WAIT_EDIT_FIELD

async def got_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    data = query.data
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]])

    if data == "cancel_anime":
        context.user_data.clear()
        await query.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu_keyboard(update.effective_user.id))
        return ConversationHandler.END

    if data == "editfield_episodes":
        code = context.user_data.get("edit_code")
        seasons = get_seasons(code)
        if not seasons:
            db_field, prompt = EDIT_FIELD_MAP[data]
            context.user_data["edit_field"] = db_field
            context.user_data["edit_field_key"] = data
            await query.message.reply_text(prompt, parse_mode="Markdown", reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        if len(seasons) == 1:
            sid, snum, poster_id, total_ep, poster_type, ep_label = seasons[0]
            context.user_data["edit_season_id"] = sid
            context.user_data["edit_field"] = "season_episodes"
            context.user_data["edit_field_key"] = data
            await query.message.reply_text(
                f"📺 *{_season_label(snum, total_ep)}* uchun yangi jami qism sonini yuboring:",
                parse_mode="Markdown", reply_markup=cancel_kb
            )
            return WAIT_EDIT_VALUE
        buttons = [
            [InlineKeyboardButton(f"{_season_label(snum, total_ep)} (hozir: {_episode_label(total_ep, ep_label)} ta)", callback_data=f"editseason_{sid}")]
            for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons
        ]
        buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")])
        await query.message.reply_text(
            "📺 Qaysi faslning jami qism sonini o'zgartirasiz?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return WAIT_EDIT_FIELD

    if data == "editposter":
        code = context.user_data.get("edit_code")
        seasons = get_seasons(code)
        if not seasons:
            context.user_data["edit_field"] = "poster"
            context.user_data["edit_season_id"] = None
            await query.message.reply_text("🖼 Yangi poster rasmini yuboring:", reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        if len(seasons) == 1:
            sid, snum = seasons[0][0], seasons[0][1]
            context.user_data["edit_field"] = "poster"
            context.user_data["edit_season_id"] = sid
            await query.message.reply_text("🖼 Yangi poster (rasm yoki video) yuboring:", reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        buttons = [
            [InlineKeyboardButton(f"{_season_label(snum, total_ep)}", callback_data=f"editposterseason_{sid}")]
            for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons
        ]
        buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")])
        await query.message.reply_text(
            "🖼 Qaysi faslning posterini o'zgartirasiz?",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return WAIT_EDIT_FIELD

    if data.startswith("editposterseason_"):
        context.user_data["edit_field"] = "poster"
        context.user_data["edit_season_id"] = int(data[len("editposterseason_"):])
        await query.message.reply_text("🖼 Yangi poster (rasm yoki video) yuboring:", reply_markup=cancel_kb)
        return WAIT_EDIT_VALUE

    if data == "editstatus":
        buttons = [
            [InlineKeyboardButton(label, callback_data=f"editstatusval_{key}")]
            for key, label in ANIME_STATUSES.items()
        ]
        buttons.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")])
        await query.message.reply_text(
            "🏷 Yangi holatni tanlang:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return WAIT_EDIT_FIELD

    if data.startswith("editstatusval_"):
        status_key = data.split("_", 1)[1]
        code = context.user_data.get("edit_code")
        set_anime_status(code, status_key)
        context.user_data.clear()
        await query.message.reply_text(
            f"✅ Holat *{ANIME_STATUSES[status_key]}* ga o'zgartirildi!",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    if data.startswith("editseason_"):
        sid = int(data[11:])
        context.user_data["edit_season_id"] = sid
        context.user_data["edit_field"] = "season_episodes"
        context.user_data["edit_field_key"] = "editfield_episodes"
        await query.message.reply_text(
            "📺 Yangi jami qism sonini yuboring:",
            reply_markup=cancel_kb
        )
        return WAIT_EDIT_VALUE

    db_field, prompt = EDIT_FIELD_MAP[data]
    context.user_data["edit_field"] = db_field
    context.user_data["edit_field_key"] = data
    await query.message.reply_text(
        prompt,
        parse_mode="Markdown",
        reply_markup=cancel_kb
    )
    return WAIT_EDIT_VALUE

async def got_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _esc_result = await _check_menu_escape(update, context)
    if _esc_result is not None:
        return _esc_result
    txt = update.message.text.strip()
    field = context.user_data.get("edit_field")
    field_key = context.user_data.get("edit_field_key")
    code = context.user_data.get("edit_code")
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]])

    if field == "year":
        if not txt.isdigit() or len(txt) != 4:
            await update.message.reply_text(
                "⚠️ Faqat *4 xonali yil* yuboring (masalan: 2023):",
                parse_mode="Markdown", reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        value = int(txt)
    elif field == "total_episodes":
        if not txt or txt in ADMIN_BUTTONS:
            await update.message.reply_text(
                "⚠️ Bo'sh yuborildi. Qism sonini yozing (masalan: 24 yoki \"24 qism 2-fasl\"):",
                reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        value, _legacy_label = _parse_episode_count(txt)
    elif field == "season_episodes":
        if not txt or txt in ADMIN_BUTTONS:
            await update.message.reply_text(
                "⚠️ Bo'sh yuborildi. Qism sonini yozing (masalan: 24 yoki \"24 qism 2-fasl\"):",
                reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        value, value_label = _parse_episode_count(txt)
    elif field == "rating":
        try:
            value = float(txt.replace(",", "."))
            if not (0 <= value <= 10):
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "⚠️ 0 dan 10 gacha raqam yuboring (masalan: 8.5):",
                reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
    elif field in ("is_featured", "is_popular"):
        if txt not in ("0", "1"):
            await update.message.reply_text(
                "⚠️ Faqat 0 yoki 1 yuboring:",
                reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        value = int(txt)
    else:
        if txt in ADMIN_BUTTONS or len(txt) == 0:
            await update.message.reply_text(
                "⚠️ Tugma bosildi yoki bo'sh yuborildi. Matn yozing:",
                reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        value = txt

    if field == "season_episodes":
        season_id = context.user_data.get("edit_season_id")
        update_season_total_episodes(season_id, value, value_label)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ *Muvaffaqiyatli yangilandi!*\n\nKod: *{code}* — Jami qismlar → `{value_label}`",
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

    update_anime_field(code, field, value)
    _, label = EDIT_FIELD_MAP[field_key]
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ *Muvaffaqiyatli yangilandi!*\n\nKod: *{code}* — *{field}* → `{value}`",
        parse_mode="Markdown",
        reply_markup=admin_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END

# ==================== FOYDALANUVCHI TEZLIK CHEGARASI ====================
RATE_LIMIT_ACTIONS = 5     # RATE_LIMIT_WINDOW soniya ichida shuncha harakat (tugma/buyruq/xabar) qilinsa, bloklanadi
RATE_LIMIT_WINDOW = 3.0    # soniya
RATE_LIMIT_BLOCK = 8.0     # chegaradan oshganda kutish vaqti (soniya)
_rate_state = {}

async def _delete_message_later(message, delay):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

async def rate_limit_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oddiy foydalanuvchi juda tez harakat qilsa, vaqtincha e'tiborsiz qoldiriladi. Admin chegaradan mustasno."""
    if not (update.message or update.callback_query):
        return
    user = update.effective_user
    if not user or is_admin(user.id):
        return
    now = time.monotonic()
    if len(_rate_state) > 5000:
        for uid in [u for u, s in _rate_state.items() if s["blocked_until"] < now and not s["hits"]]:
            _rate_state.pop(uid, None)
    st = _rate_state.setdefault(user.id, {"hits": deque(), "blocked_until": 0.0})
    if now < st["blocked_until"]:
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except Exception:
                pass
        raise ApplicationHandlerStop
    hits = st["hits"]
    while hits and now - hits[0] > RATE_LIMIT_WINDOW:
        hits.popleft()
    hits.append(now)
    if len(hits) >= RATE_LIMIT_ACTIONS:
        st["blocked_until"] = now + RATE_LIMIT_BLOCK
        hits.clear()
        chat_id = update.effective_chat.id if update.effective_chat else user.id
        try:
            if update.callback_query:
                await update.callback_query.answer()
            warn = await context.bot.send_message(chat_id=chat_id, text="⏳ Juda tez! Iltimos, biroz kuting.")
            # Vaqt tugagach ogohlantirish xabari avtomatik o'chadi va bot yana so'rovlarga javob beradi.
            context.application.create_task(_delete_message_later(warn, RATE_LIMIT_BLOCK))
        except Exception:
            pass
        raise ApplicationHandlerStop

async def watch_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anime sahifasidagi 🔔 tugmasi: kuzatishni yoqadi/o'chiradi."""
    query = update.callback_query
    code = int(query.data[len("watch_"):])
    user_id = query.from_user.id
    if is_watching(user_id, code):
        remove_watch(user_id, code)
        watching = False
        await query.answer("🔕 Kuzatuv bekor qilindi.")
    else:
        add_watch(user_id, code)
        watching = True
        await query.answer("🔔 Yangi qism chiqsa, sizga xabar beraman!")
    try:
        rows = []
        for row in query.message.reply_markup.inline_keyboard:
            new_row = []
            for button in row:
                if button.callback_data == query.data:
                    button = InlineKeyboardButton(_watch_button_label(watching), callback_data=query.data)
                new_row.append(button)
            rows.append(new_row)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
    except Exception:
        pass

WATCH_NOTIFY_PER_MINUTE = 20  # yangi qism haqida bir daqiqada nechta kuzatuvchiga xabar yuboriladi

def _format_episode_nums(nums):
    nums = sorted(set(nums))
    parts = []
    start = prev = nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(parts)

async def _run_watch_notify(bot, admin_chat_id, code, season_num, ep_nums):
    """Yangi yuklangan qismlar haqida animeni kuzatayotganlarga fon rejimida xabar yuboradi."""
    sent = 0
    failed = 0
    name = str(code)
    try:
        watchers = get_watchers(code)
        if not watchers:
            return
        anime = get_anime_by_code(code)
        if anime:
            name = anime[2]
        nums = sorted(set(ep_nums))
        header = f"🔔 {name}"
        if len(get_seasons(code)) > 1:
            header += f" — {season_num}-fasl"
        if len(nums) == 1:
            body = f"🆕 {nums[0]}-qism yuklandi!"
        else:
            body = f"🆕 {len(nums)} ta yangi qism yuklandi: {_format_episode_nums(nums)}"
        text = f"{header}\n\n{body}"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("▶️ Tomosha qilish", url=f"https://t.me/{BOT_USERNAME}?start={code}_{season_num}")
        ]])
        for uid in watchers:
            delivered = False
            for attempt in range(3):
                try:
                    await bot.send_message(chat_id=uid, text=text, reply_markup=kb)
                    delivered = True
                    break
                except Forbidden:
                    set_user_active(uid, False)
                    break
                except RetryAfter as exc:
                    if attempt == 2:
                        break
                    await asyncio.sleep(max(float(exc.retry_after), 1.0))
                except Exception as exc:
                    logger.warning("Kuzatuv xabari %s ga yuborilmadi: %s", uid, exc)
                    break
            if delivered:
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(60.0 / WATCH_NOTIFY_PER_MINUTE)
    except Exception:
        logger.exception("Kuzatuvchilarga xabar yuborishda kutilmagan xato")
        return
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=f"🔔 {name}: yangi qism haqida {sent} ta kuzatuvchiga xabar yuborildi"
                 + (f" ({failed} ta yetib bormadi)." if failed else ".")
        )
    except Exception:
        pass

async def got_edit_poster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tahrirlashda yangi poster (rasm yoki video) qabul qiladi."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_anime")]])
    if context.user_data.get("edit_field") != "poster":
        await update.message.reply_text("⚠️ Bu maydon uchun matn yuboring:", reply_markup=cancel_kb)
        return WAIT_EDIT_VALUE
    code = context.user_data.get("edit_code")
    season_id = context.user_data.get("edit_season_id")
    if update.message.video:
        poster_id = update.message.video.file_id
        poster_type = "video"
    else:
        poster_id = update.message.photo[-1].file_id
        poster_type = "photo"
    if season_id:
        update_season_poster(season_id, poster_id, poster_type)
    else:
        if poster_type == "video":
            await update.message.reply_text("⚠️ Bu animeda fasl yo'q, faqat rasm yuboring:", reply_markup=cancel_kb)
            return WAIT_EDIT_VALUE
        update_anime_poster(code, poster_id)
    context.user_data.clear()
    await update.message.reply_text(
        f"✅ *Muvaffaqiyatli yangilandi!*\n\nKod: *{code}* — poster almashtirildi.",
        parse_mode="Markdown",
        reply_markup=admin_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END

# -- STATS --
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    animes_this_month, users, total_animes, total_episodes = get_monthly_stats()
    total_ep_requests, month_ep_requests, total_anime_requests = get_request_stats()
    month = datetime.now().strftime("%B %Y")
    buttons = [[InlineKeyboardButton("🔝 Top 10 Anime", callback_data="top10_animes")]]
    growth = get_growth_stats()
    new_cur, new_prev = growth["new_users"]
    act_cur, act_prev = growth["active_users"]
    watch_cur, watch_prev = growth["new_watches"]
    top_watched_lines = "".join(
        f"\n{i}. {_esc_md(name)} — {count}" for i, (name, count) in enumerate(growth["top_watched"], start=1)
    )
    await update.message.reply_text(
        f"📊 *Statistika — {month}*\n\n"
        f"👥 Jami foydalanuvchilar: {users}\n"
        f"🎬 Jami animeler: {total_animes}\n"
        f"📺 Jami qismlar: {total_episodes}\n"
        f"➕ Bu oy qo'shilgan: {animes_this_month} ta anime\n\n"
        f"📥 Jami so'ralgan qismlar: {total_ep_requests}\n"
        f"📅 Bu oy so'ralgan qismlar: {month_ep_requests}\n"
        f"🔍 Jami so'ralgan animeler: {total_anime_requests}\n\n"
        f"📈 *Foydalanuvchilar o'sishi*\n"
        f"🆕 Bu oy yangi: {new_cur}\n"
        f"🗓 O'tgan oy yangi: {new_prev}\n"
        f"📊 O'zgarish: {_percent_change_text(new_cur, new_prev)}\n\n"
        f"🔥 *Faollik* (anime ochgan yoki qism so'ragan)\n"
        f"👤 Bu oy: {act_cur} kishi\n"
        f"🗓 O'tgan oy: {act_prev} kishi\n"
        f"📊 O'zgarish: {_percent_change_text(act_cur, act_prev)}\n\n"
        f"🔔 *Kuzatuvchilar*\n"
        f"👥 Jami: {growth['total_watchers']} kishi ({growth['total_watches']} ta kuzatuv)\n"
        f"🆕 Bu oy yangi kuzatuv: {watch_cur}\n"
        f"🗓 O'tgan oy: {watch_prev}\n"
        f"📊 O'zgarish: {_percent_change_text(watch_cur, watch_prev)}"
        + (f"\n\n🔝 *Eng ko'p kuzatilgan:*{top_watched_lines}" if top_watched_lines else ""),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def show_top_animes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    top_animes = get_top_animes(10)
    if not top_animes:
        await query.message.reply_text("Hali statistika uchun yetarli ma'lumot yo'q.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🔝 *Top 10 Anime (eng ko'p so'ralgan):*\n"]
    for i, (name, code, count) in enumerate(top_animes):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {name} (kod: {code}) — {count} marta")
    await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

# -- BROADCAST --
async def _start_broadcast_from_message(message, context, user_id):
    if not is_primary_admin(user_id):
        return ConversationHandler.END
    users = get_broadcast_users()
    await message.reply_text(
        f"📣 *Xabar yuborish*\n\n"
        f"👥 Faol foydalanuvchilar soni: *{len(users)} ta*\n\n"
        f"Yuboriladigan xabarni yozing yoki rasm+izoh yuboring:\n"
        f"_(Matn, rasm, yoki rasm+sarlavha qabul qilinadi)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.reply_text(
        "👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_broadcast")]])
    )
    return WAIT_BROADCAST_MSG

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await _start_broadcast_from_message(
        update.message, context, update.effective_user.id
    )

async def broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await _start_broadcast_from_message(
        query.message, context, query.from_user.id
    )

async def cancel_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

BROADCAST_PER_MINUTE = 20  # bir daqiqada nechta foydalanuvchiga yuboriladi

async def _run_broadcast(bot, admin_chat_id, admin_id, users, photo_file_id, caption, text, reply_markup=None, skipped=0):
    """Xabarni fon rejimida yuboradi, shuning uchun bot boshqa foydalanuvchilarga javob berishda davom etadi."""
    sent = 0
    failed = 0
    deactivated = 0
    try:
        for uid in users:
            delivered = False
            for attempt in range(3):
                try:
                    if photo_file_id:
                        await bot.send_photo(chat_id=uid, photo=photo_file_id, caption=caption or "", reply_markup=reply_markup)
                    else:
                        await bot.send_message(chat_id=uid, text=text, reply_markup=reply_markup)
                    delivered = True
                    sent += 1
                    break
                except Forbidden as exc:
                    # Foydalanuvchi botni bloklagan yoki hisobi o'chirilgan — keyingi safar o'tkazib yuboriladi.
                    logger.info("Broadcast: %s faol emas deb belgilandi: %s", uid, exc)
                    set_user_active(uid, False)
                    deactivated += 1
                    break
                except RetryAfter as exc:
                    # Telegram qaytargan aniq kutish vaqtiga amal qilamiz.
                    if attempt == 2:
                        break
                    await asyncio.sleep(max(float(exc.retry_after), 1.0))
                except Exception as exc:
                    logger.warning("Broadcast %s foydalanuvchiga yuborilmadi: %s", uid, exc)
                    break
            if not delivered:
                failed += 1
            # Bir daqiqada BROADCAST_PER_MINUTE ta foydalanuvchiga yuboriladi.
            await asyncio.sleep(60.0 / BROADCAST_PER_MINUTE)
    except Exception:
        logger.exception("Broadcast jarayonida kutilmagan xato")
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=(
                f"✅ *Xabar yuborildi!*\n\n"
                f"📤 Muvaffaqiyatli: *{sent}* ta\n"
                f"❌ Xato: *{failed}* ta\n"
                f"🚫 Botni bloklagani uchun faol emas deb belgilandi: *{deactivated}* ta\n"
                f"⏭ Oldin faol emas bo'lgani uchun o'tkazib yuborildi: *{skipped}* ta"
            ),
            parse_mode="Markdown",
            reply_markup=admin_menu_keyboard(admin_id)
        )
    except Exception:
        logger.exception("Broadcast natijasini adminga yuborib bo'lmadi")

async def got_broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        context.user_data.clear()
        return ConversationHandler.END
    all_users_count = len(get_all_users())
    users = get_broadcast_users()
    photo_file_id = update.message.photo[-1].file_id if update.message.photo else None
    # Yuborish fon vazifasida ishlaydi — handler darhol tugaydi va bot bloklanmaydi.
    context.application.create_task(
        _run_broadcast(
            context.bot,
            update.effective_chat.id,
            update.effective_user.id,
            users,
            photo_file_id,
            update.message.caption,
            update.message.text,
            update.message.reply_markup,  # xabarga biriktirilgan tugmalar (masalan "Tomosha qilish") ham yuboriladi
            all_users_count - len(users),
        )
    )
    await update.message.reply_text(
        f"📤 Xabar yuborish boshlandi ({len(users)} ta foydalanuvchi). "
        f"Tugagach natijani yuboraman. Bot shu vaqtda odatdagidek ishlayveradi.",
        reply_markup=admin_menu_keyboard(update.effective_user.id)
    )
    return ConversationHandler.END

# -- ANIME LIST --
async def show_anime_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    animes, seasons_by_anime, ep_counts = get_anime_list_summary()
    if not animes:
        await update.message.reply_text("❌ Hali anime yo'q!")
        return

    lines = []
    for code, name, post_count in animes:
        post_info = f" | 📤 {post_count}-marta yuborilgan" if post_count else ""
        seasons = seasons_by_anime.get(code)
        if not seasons:
            lines.append(f"*{code}* — {_esc_md(name)} (fasl yo'q){post_info}")
            continue
        parts = []
        for sid, snum, s_total, s_label in seasons:
            added = ep_counts.get(sid, 0)
            label = _episode_label(s_total, s_label)
            parts.append(f"{_season_label(snum, s_total)}: {added}/{label}")
        lines.append(f"*{code}* — {_esc_md(name)} — " + ", ".join(parts) + post_info)

    # Telegram xabar chegarasi (4096 belgi) dan oshib ketmasligi uchun bo'laklarga bo'lib yuboramiz
    header = "📋 *Animeler ro'yxati:*\n\n"
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > 3500:
            await update.message.reply_text(chunk, parse_mode="Markdown")
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await update.message.reply_text(chunk, parse_mode="Markdown")

# -- MANAGE CHANNELS --
def _format_channels_list(channels):
    text = "📡 *Majburiy obuna kanallari:*\n\n"
    buttons = []
    if channels:
        for identifier, link, title, expires_at in channels:
            label = title or identifier
            if expires_at:
                try:
                    exp_text = f"⏳ {datetime.fromisoformat(expires_at).strftime('%d.%m.%Y')} gacha"
                except ValueError:
                    exp_text = "⏳ muddatli"
            else:
                exp_text = "♾ Doimiy"
            text += f"• {label} — {exp_text}\n"
            buttons.append([InlineKeyboardButton(f"🗑 {label} ni o'chirish", callback_data=f"rmchan_{identifier}")])
    else:
        text += "Hali kanal qo'shilmagan.\n"
    buttons.append([InlineKeyboardButton("➕ Kanal Qo'shish", callback_data="add_channel")])
    instagram = _instagram_link()
    if instagram:
        text += (
            f"\n📸 *Instagram havolasi:*\n{instagram}\n"
            "_Bu havola ko'rsatiladi, lekin Instagram obunasi tekshirilmaydi._\n"
        )
        buttons.append([InlineKeyboardButton("🗑 Instagram linkni o'chirish", callback_data="rm_instagram", style="danger")])
    else:
        text += "\n📸 Instagram havolasi: ulanmagan.\n"
    buttons.append([InlineKeyboardButton("📸 Instagram link qo'shish", callback_data="set_instagram", style="primary")])
    return text, buttons

async def manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    message = update.message or update.callback_query.message
    channels = get_required_channels()
    text, buttons = _format_channels_list(channels)
    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def manage_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(update.effective_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "add_channel":
        await query.message.reply_text(
            "📡 Yangi kanal havolasini yuboring.\n\n"
            "🔓 Ochiq kanal uchun: https://t.me/kanal_nomi (yoki @kanal_nomi)\n"
            "🔒 Yopiq kanal uchun: https://t.me/+XXXXXXXX"
        )
        context.user_data["awaiting_channel"] = True
        return

    if data == "set_instagram":
        context.user_data["awaiting_instagram_link"] = True
        await query.message.reply_text(
            "📸 Instagram profil yoki kanal havolasini yuboring.\n"
            "Masalan: https://instagram.com/username\n\n"
            "⚠️ Bot bu obunani tekshirmaydi — foydalanuvchi obuna bo'lmasa ham davom eta oladi."
        )
        return

    if data == "rm_instagram":
        delete_bot_setting("instagram_link")
        channels = get_required_channels()
        text, buttons = _format_channels_list(channels)
        await query.message.edit_text(
            "✅ Instagram havolasi o'chirildi.\n\n" + text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    if data.startswith("rmchan_"):
        identifier = data[7:]
        remove_required_channel(identifier)
        channels = get_required_channels()
        text, buttons = _format_channels_list(channels)
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def ask_channel_expiry(message, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 1 hafta", callback_data="chexp_7"), InlineKeyboardButton("📅 15 kun", callback_data="chexp_15")],
        [InlineKeyboardButton("📅 30 kun", callback_data="chexp_30"), InlineKeyboardButton("♾ Doimiy", callback_data="chexp_never")],
        [InlineKeyboardButton("✍️ Qo'lda kiritish", callback_data="chexp_custom")],
    ])
    await message.reply_text(
        "⏳ Bu kanal majburiy obunada qancha muddat tursin?\n"
        "(muddat tugagach ro'yxatdan avtomatik olib tashlanadi)",
        reply_markup=kb
    )

async def ask_channel_title(message, context, detected_title):
    context.user_data["awaiting_channel_title"] = True
    context.user_data["pending_channel"]["detected_title"] = detected_title
    hint = f" (aniqlangan nom: {detected_title})" if detected_title else ""
    await message.reply_text(
        f"✏️ Bu kanal uchun ko'rinadigan nom kiriting{hint}:"
    )

async def _bot_is_channel_admin(bot, chat_id):
    """Bot ko'rsatilgan kanalda administrator ekanini tekshiradi."""
    try:
        bot_user = await bot.get_me()
        member = await bot.get_chat_member(chat_id, bot_user.id)
        return member.status in ("administrator", "creator")
    except Exception as exc:
        logger.info("Kanal adminligi tekshiruvi muvaffaqiyatsiz: chat_id=%s xato=%r", chat_id, exc)
        return False

async def _reject_channel_without_bot_admin(message):
    await message.reply_text(
        "❌ Bu kanal qo'shilmadi.\n\n"
        "Bot bu kanalda administrator emas. Avval botni kanalga administrator qilib qo'shing, "
        "keyin kanalni qaytadan yuboring."
    )

async def got_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_channel"):
        return
    context.user_data["awaiting_channel"] = False
    text = update.message.text.strip()

    parsed = parse_channel_link(text)
    if not parsed:
        await update.message.reply_text(
            "❌ Havola noto'g'ri formatda!\n\n"
            "Quyidagi ko'rinishlardan birida yuboring:\n"
            "• https://t.me/kanal_nomi\n"
            "• @kanal_nomi\n"
            "• https://t.me/+XXXXXXXX (yopiq kanal uchun)"
        )
        context.user_data["awaiting_channel"] = True
        return

    kind, value = parsed
    if kind == "public":
        try:
            chat = await context.bot.get_chat(f"@{value}")
        except Exception as e:
            await update.message.reply_text(
                f"❌ Kanal topilmadi yoki botga ruxsat yo'q.\n"
                f"Botni shu kanalga *administrator* qilib qo'shganingizga ishonch hosil qiling, so'ng qaytadan yuboring.\n\n"
                f"_Xato: {_esc_md(str(e))}_",
                parse_mode="Markdown"
            )
            context.user_data["awaiting_channel"] = True
            return
        if chat.type != "channel":
            await update.message.reply_text(
                "❌ Faqat Telegram kanalini qo'shish mumkin. Guruh yoki superguruh havolasini yubormang."
            )
            context.user_data["awaiting_channel"] = True
            return
        if not await _bot_is_channel_admin(context.bot, chat.id):
            await _reject_channel_without_bot_admin(update.message)
            context.user_data["awaiting_channel"] = True
            return
        context.user_data["pending_channel"] = {
            "identifier": f"@{value}",
            "link": f"https://t.me/{value}",
        }
        await ask_channel_title(update.message, context, chat.title or value)
    else:
        context.user_data["pending_channel_link"] = value
        context.user_data["awaiting_channel_forward"] = True
        await update.message.reply_text(
            "🔒 Bu — yopiq kanal havolasi. Kanalni avtomatik aniqlash uchun:\n\n"
            "1️⃣ Botni shu kanalga *administrator* qilib qo'shing.\n"
            "2️⃣ Keyin o'sha kanaldan istalgan xabarni shu botga *forward* (uzatib) yuboring.",
            parse_mode="Markdown"
        )

async def got_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yopiq kanaldan forward qilingan xabarni tutib, kanalni aniqlaydi."""
    if not update.message:
        return
    msg = update.message

    if not (is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_forward")):
        return
    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is None:
        origin = getattr(msg, "forward_origin", None)
        fwd_chat = getattr(origin, "chat", None) if origin else None
    if fwd_chat is None or fwd_chat.type != "channel":
        await msg.reply_text("❌ Bu — kanaldan uzatilgan (forward) post emas. Iltimos, o'sha yopiq kanaldan bitta postni forward qiling.")
        return
    if not await _bot_is_channel_admin(context.bot, fwd_chat.id):
        await _reject_channel_without_bot_admin(msg)
        return
    context.user_data["awaiting_channel_forward"] = False
    link = context.user_data.pop("pending_channel_link", None)
    context.user_data["pending_channel"] = {
        "identifier": str(fwd_chat.id),
        "link": link,
    }
    await ask_channel_title(msg, context, fwd_chat.title or "Yopiq kanal")

async def got_channel_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin kanal uchun qo'lda kiritgan ko'rinadigan nomni tutib oladi."""
    if not (is_primary_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_title")):
        return
    context.user_data["awaiting_channel_title"] = False
    title = update.message.text.strip()
    pending = context.user_data.get("pending_channel")
    if not pending:
        await update.message.reply_text("❌ Xatolik: qaytadan «➕ Kanal Qo'shish» dan boshlang.")
        return
    pending["title"] = title or pending.pop("detected_title", None)
    pending.pop("detected_title", None)
    await ask_channel_expiry(update.message, context)

async def channel_expiry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_primary_admin(query.from_user.id):
        return
    if query.data == "chexp_custom":
        # pending yo'qotilmasin — got_channel_custom_days uni keyin ishlatadi
        context.user_data["awaiting_channel_custom_days"] = True
        await query.message.reply_text(
            "✍️ Necha kun tursin? Faqat son kiriting (masalan: 10):"
        )
        return
    pending = context.user_data.pop("pending_channel", None)
    if not pending:
        await query.message.reply_text("❌ Xatolik: qo'shilayotgan kanal topilmadi. Qaytadan «➕ Kanal Qo'shish» dan boshlang.")
        return
    days_map = {"chexp_7": 7, "chexp_15": 15, "chexp_30": 30}
    days = days_map.get(query.data)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat() if days else None
    add_required_channel(pending["identifier"], pending["link"], pending["title"], expires_at)
    channels = get_required_channels()
    text, buttons = _format_channels_list(channels)
    await query.message.edit_text(
        f"✅ *{_esc_md(pending['title'])}* qo'shildi!\n\n" + text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def got_channel_custom_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_channel_custom_days"):
        return
    text = update.message.text.strip()
    pending = context.user_data.get("pending_channel")
    if not pending:
        context.user_data["awaiting_channel_custom_days"] = False
        await update.message.reply_text("❌ Xatolik: qo'shilayotgan kanal topilmadi. Qaytadan «➕ Kanal Qo'shish» dan boshlang.")
        return
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ Faqat musbat son kiriting (masalan: 10).")
        return
    context.user_data["awaiting_channel_custom_days"] = False
    context.user_data.pop("pending_channel", None)
    days = int(text)
    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    add_required_channel(pending["identifier"], pending["link"], pending["title"], expires_at)
    channels = get_required_channels()
    ch_text, buttons = _format_channels_list(channels)
    await update.message.reply_text(
        f"✅ *{_esc_md(pending['title'])}* {days} kunga qo'shildi!\n\n" + ch_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# -- KANALGA QO'LDA YUBORISH --
CHANNEL_SEND_PAGE_SIZE = 15

def _channel_send_page_kb(animes, page):
    start = page * CHANNEL_SEND_PAGE_SIZE
    chunk = animes[start:start + CHANNEL_SEND_PAGE_SIZE]
    buttons = [
        [InlineKeyboardButton(
            f"{code} — {name}" + (f" (📤 {post_count})" if post_count else ""),
            callback_data=f"chsel_{code}"
        )]
        for code, name, post_count in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Oldingi", callback_data=f"chpage_{page-1}"))
    if start + CHANNEL_SEND_PAGE_SIZE < len(animes):
        nav.append(InlineKeyboardButton("Keyingi ▶️", callback_data=f"chpage_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔢 Kod orqali kiritish", callback_data="chsel_bycode")])
    buttons.append([InlineKeyboardButton("📤 Barchasini Yuborish", callback_data="chsendall_ask")])
    return buttons

async def channel_send_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    recent = get_recent_animes(hours=48)
    if not recent:
        await update.message.reply_text(
            "❌ So'nggi 48 soatda qo'shilgan anime yo'q.\n"
            "Baribir kanalga yubormoqchi bo'lgan animening kodini bilsangiz, shuni yuborishingiz mumkin:",
        )
        context.user_data["awaiting_channel_send_code"] = True
        return
    recent_codes = {a[0] for a in recent}
    all_summary, _seasons_by_anime, _ep_counts = get_anime_list_summary()
    post_counts = {code: post_count for code, name, post_count in all_summary}
    # get_recent_animes tartibida (eng yangisi birinchi) ketma-ketlikni saqlab, post_count qo'shamiz
    animes = [(a[0], a[1], post_counts.get(a[0], 0)) for a in recent]
    total_pages = (len(animes) - 1) // CHANNEL_SEND_PAGE_SIZE + 1
    await update.message.reply_text(
        f"📤 *Kanalga yuborish* (1/{total_pages}-sahifa)\n"
        f"_(faqat so'nggi 48 soatda qo'shilganlar ko'rsatilmoqda — eski anime uchun \"🔢 Kod orqali kiritish\" tugmasidan foydalaning)_\n\n"
        f"Qaysi animeni kanalga yubormoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(_channel_send_page_kb(animes, 0))
    )

async def channel_send_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_primary_admin(query.from_user.id):
        return
    page = int(query.data.split("_")[1])
    recent = get_recent_animes(hours=48)
    all_summary, _seasons_by_anime, _ep_counts = get_anime_list_summary()
    post_counts = {code: post_count for code, name, post_count in all_summary}
    animes = [(a[0], a[1], post_counts.get(a[0], 0)) for a in recent]
    total_pages = (len(animes) - 1) // CHANNEL_SEND_PAGE_SIZE + 1
    await query.message.edit_text(
        f"📤 *Kanalga yuborish* ({page+1}/{total_pages}-sahifa)\n"
        f"_(faqat so'nggi 48 soatda qo'shilganlar ko'rsatilmoqda — eski anime uchun \"🔢 Kod orqali kiritish\" tugmasidan foydalaning)_\n\n"
        f"Qaysi animeni kanalga yubormoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(_channel_send_page_kb(animes, page))
    )

async def channel_send_bycode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_primary_admin(query.from_user.id):
        return
    context.user_data["awaiting_channel_send_code"] = True
    await query.message.reply_text("🔢 Kanalga yubormoqchi bo'lgan animening kodini yuboring:")

async def got_channel_send_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_channel_send_code"):
        return
    context.user_data["awaiting_channel_send_code"] = False
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Faqat raqam (kod) yuboring!")
        context.user_data["awaiting_channel_send_code"] = True
        return
    code = int(text)
    anime = get_anime_by_code(code)
    if not anime:
        await update.message.reply_text("❌ Bunday anime topilmadi!")
        return
    name, genre = anime[2], anime[4]
    seasons = get_seasons(code)
    if not seasons:
        await update.message.reply_text("❌ Bu animeda hali fasl yo'q.")
        return
    if len(seasons) == 1:
        sid, snum, poster_id, total_ep, poster_type, ep_label = seasons[0]
        ok = await post_anime_to_channel(context, code, name, genre, total_ep, poster_id, poster_type=poster_type, ep_label=ep_label, season_num=snum)
        if ok:
            increment_channel_post_count(code)
            count = get_channel_post_count(code)
            await update.message.reply_text(
                f"✅ *{_esc_md(name)}* — {snum}-fasl kanalga yuborildi!\n"
                f"📊 Bu anime posteri kanalga jami *{count}-marta* joylandi.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"❌ *{_esc_md(name)}* kanalga yuborilmadi. Bot kanalda admin ekanligini tekshiring.",
                parse_mode="Markdown"
            )
        return
    buttons = [
        [InlineKeyboardButton(f"{_season_label(snum, total_ep)}", callback_data=f"chsend_{sid}")]
        for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons
    ]
    await update.message.reply_text(
        f"📤 *{_esc_md(name)}*\n\nQaysi faslni kanalga yubormoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def _do_channel_send(query, context, code, name, genre, season):
    sid, season_num, poster_id, total_ep, poster_type, ep_label = season
    await query.answer("⏳ Yuborilmoqda...")
    ok = await post_anime_to_channel(context, code, name, genre, total_ep, poster_id, poster_type=poster_type, ep_label=ep_label, season_num=season_num)
    if ok:
        increment_channel_post_count(code)
        count = get_channel_post_count(code)
        await query.message.reply_text(
            f"✅ *{_esc_md(name)}* — {season_num}-fasl kanalga yuborildi!\n"
            f"📊 Bu anime posteri kanalga jami *{count}-marta* joylandi.",
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text(
            f"❌ *{_esc_md(name)}* kanalga yuborilmadi. Bot kanalda admin ekanligini tekshiring.",
            parse_mode="Markdown"
        )

async def chsel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    code = int(query.data[6:])
    anime = get_anime_by_code(code)
    if not anime:
        await query.answer("❌ Bunday anime topilmadi!", show_alert=True)
        return
    name, genre = anime[2], anime[4]
    seasons = get_seasons(code)
    if not seasons:
        await query.answer()
        await query.edit_message_text("❌ Bu animeda hali fasl yo'q.")
        return
    if len(seasons) == 1:
        await _do_channel_send(query, context, code, name, genre, seasons[0])
        return
    await query.answer()
    buttons = [
        [InlineKeyboardButton(f"{_season_label(snum, total_ep)}", callback_data=f"chsend_{sid}")]
        for sid, snum, poster_id, total_ep, poster_type, ep_label in seasons
    ]
    await query.edit_message_text(
        f"📤 *{_esc_md(name)}*\n\nQaysi faslni kanalga yubormoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def chsend_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    season_id = int(query.data[7:])
    season = get_season_by_id(season_id)
    if not season:
        await query.answer("❌ Bu fasl topilmadi!", show_alert=True)
        return
    _, code, season_num, poster_id, total_ep, poster_type, ep_label = season
    anime = get_anime_by_code(code)
    if not anime:
        await query.answer("❌ Bunday anime topilmadi!", show_alert=True)
        return
    name, genre = anime[2], anime[4]
    await _do_channel_send(query, context, code, name, genre, (season_id, season_num, poster_id, total_ep, poster_type, ep_label))

# -- KANALGA BARCHASINI YUBORISH (tasdiqlash + asta-sekin yuborish) --
CHANNEL_SEND_ALL_DELAY = 4  # soniya — har bir post orasidagi pauza (Telegram flood-limitidan qochish uchun)

async def channel_send_all_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_primary_admin(query.from_user.id):
        return
    animes = get_all_animes()
    if not animes:
        await query.message.reply_text("❌ Bazada anime topilmadi.")
        return
    total_seasons = sum(len(get_seasons(code)) for code, *_ in animes)
    await query.message.reply_text(
        f"⚠️ *Diqqat!*\n\n"
        f"Bazadagi barcha animelar (*{len(animes)}* ta anime, *{total_seasons}* ta fasl) "
        f"rostdan ham ketma-ket, asta-sekin kanalga yuborilsinmi?\n\n"
        f"_Bu ancha vaqt (taxminan {total_seasons * CHANNEL_SEND_ALL_DELAY} soniya) davom etishi mumkin._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ha, yubor", callback_data="chsendall_yes"),
            InlineKeyboardButton("❌ Yo'q", callback_data="chsendall_no"),
        ]])
    )

async def channel_send_all_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(query.from_user.id):
        await query.answer("⛔ Sizda admin huquqi yo'q.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text("❌ Bekor qilindi.")

async def _run_channel_send_all(context, query, animes):
    """Barcha animelarni kanalga fon rejimida yuboradi — bot shu vaqtda boshqalarga javob berishda davom etadi."""
    total = len(animes)
    sent_seasons = 0
    failed = 0
    try:
        for idx, (code, name, year, genre, _total_ep) in enumerate(animes, start=1):
            seasons = get_seasons(code)
            for sid, snum, poster_id, s_total_ep, poster_type, ep_label in seasons:
                ok = await post_anime_to_channel(
                    context, code, name, genre, s_total_ep, poster_id,
                    poster_type=poster_type, ep_label=ep_label, season_num=snum
                )
                if ok:
                    increment_channel_post_count(code)
                    sent_seasons += 1
                else:
                    failed += 1
                await asyncio.sleep(CHANNEL_SEND_ALL_DELAY)
            if idx % 5 == 0 or idx == total:
                try:
                    status = f"⏳ Yuborilmoqda... ({idx}/{total} anime, {sent_seasons} fasl yuborildi"
                    status += f", {failed} ta xato)" if failed else ")"
                    await query.edit_message_text(status)
                except Exception:
                    pass
    finally:
        context.bot_data["sending_all_in_progress"] = False
    result_text = f"✅ Tugadi! Jami *{sent_seasons}* fasl kanalga yuborildi."
    if failed:
        result_text += f"\n⚠️ *{failed}* ta fasl yuborilmadi (bot kanalda admin ekanligini tekshiring)."
    await query.message.reply_text(result_text, parse_mode="Markdown")

async def channel_send_all_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_primary_admin(query.from_user.id):
        await query.answer()
        return
    if context.bot_data.get("sending_all_in_progress"):
        await query.answer("⏳ Hozir allaqachon yuborish jarayoni ketmoqda!", show_alert=True)
        return
    await query.answer()
    context.bot_data["sending_all_in_progress"] = True
    animes = get_all_animes()
    total = len(animes)
    await query.edit_message_text(f"⏳ Yuborish boshlandi... (0/{total} anime)")
    # Yuborish fon vazifasida ishlaydi — handler darhol tugaydi va bot bloklanmaydi.
    context.application.create_task(_run_channel_send_all(context, query, animes))

# -- ADMINLIK BOSHQARUVI (faqat asosiy admin) --
def _admins_kb():
    admins = get_all_admins()
    buttons = [
        [InlineKeyboardButton(f"🗑 {uid}", callback_data=f"rmadmin_{uid}")]
        for uid, _ in admins
    ]
    buttons.append([InlineKeyboardButton("➕ Admin Qo'shish", callback_data="add_admin")])
    return buttons, admins

# -- BACKUP / RESTORE --

async def _download_backup_media(bot, file_id, output_path):
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(output_path)


async def _create_media_database(bot, db_path, backup_path):
    """Bitta .db fayl ichida sof matn bazani saqlaydi.

    Rasm/video fayllar backup ichiga BLOB sifatida qo'shilmaydi — aks holda
    backup fayli 20 MB'dan oshib, botning get_file() cheklovi tufayli
    o'zini tiklashning imkoni bo'lmay qoladi ("File is too big"). Barcha
    posterlar, thumbnail'lar va videolar o'zlarining file_id'lari orqali
    ishlashda davom etadi — bular shu bazada saqlanadi, alohida yuklab
    olish shart emas.
    """
    source_conn = sqlite3.connect(db_path)
    backup_conn = sqlite3.connect(backup_path)
    try:
        with backup_conn:
            source_conn.backup(backup_conn)
        media_count = 0
        skipped_count = sum(
            backup_conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NOT NULL AND {col} != ''").fetchone()[0]
            for table, col in (
                ("animes", "poster_file_id"),
                ("animes", "episode_thumb_file_id"),
                ("seasons", "episode_thumb_file_id"),
                ("seasons", "poster_file_id"),
                ("episodes", "video_file_id"),
            )
        )
        backup_conn.commit()
        return media_count, skipped_count
    finally:
        source_conn.close()
        backup_conn.close()


async def _create_backup_archive(bot, db_path, archive_path):
    """DB bilan birga Telegram media fayllarini ham arxivlaydi."""
    with tempfile.TemporaryDirectory(prefix="anime_backup_") as work_dir:
        snapshot_path = os.path.join(work_dir, "anime.db")
        media_dir = os.path.join(work_dir, "media")
        os.makedirs(media_dir, exist_ok=True)

        source_conn = sqlite3.connect(db_path)
        snapshot_conn = sqlite3.connect(snapshot_path)
        try:
            with snapshot_conn:
                source_conn.backup(snapshot_conn)
        finally:
            snapshot_conn.close()
            source_conn.close()

        manifest = {"files": {}, "failed": []}
        conn = sqlite3.connect(snapshot_path)
        try:
            media_rows = []
            media_rows.extend(
                ("anime_poster", file_id, "photo")
                for file_id, _poster_type in conn.execute(
                    "SELECT poster_file_id, COALESCE(poster_type, 'photo') FROM animes "
                    "WHERE poster_file_id IS NOT NULL AND poster_file_id != ''"
                ).fetchall()
            )
            media_rows.extend(
                ("anime_episode_cover", file_id, "photo")
                for (file_id,) in conn.execute(
                    "SELECT episode_thumb_file_id FROM animes "
                    "WHERE episode_thumb_file_id IS NOT NULL AND episode_thumb_file_id != ''"
                ).fetchall()
            )
            media_rows.extend(
                ("season_episode_cover", file_id, "photo")
                for (file_id,) in conn.execute(
                    "SELECT episode_thumb_file_id FROM seasons "
                    "WHERE episode_thumb_file_id IS NOT NULL AND episode_thumb_file_id != ''"
                ).fetchall()
            )
            media_rows.extend(
                ("season_poster", file_id, "photo")
                for file_id, _poster_type in conn.execute(
                    "SELECT poster_file_id, COALESCE(poster_type, 'photo') FROM seasons "
                    "WHERE poster_file_id IS NOT NULL AND poster_file_id != ''"
                ).fetchall()
            )
            media_rows.extend(
                ("episode_video", file_id, "video")
                for (file_id,) in conn.execute(
                    "SELECT video_file_id FROM episodes "
                    "WHERE video_file_id IS NOT NULL AND video_file_id != ''"
                ).fetchall()
            )
        finally:
            conn.close()

        for index, (source, file_id, media_type) in enumerate(media_rows, start=1):
            if file_id in manifest["files"]:
                continue
            relative_path = os.path.join("media", f"{index}_{media_type}")
            output_path = os.path.join(work_dir, relative_path)
            try:
                await _download_backup_media(bot, file_id, output_path)
                manifest["files"][file_id] = {
                    "path": relative_path,
                    "type": media_type,
                    "source": source,
                }
            except Exception as exc:
                logger.warning("Backup media yuklanmadi (%s): %s", source, exc)
                manifest["failed"].append({"source": source, "type": media_type})

        with open(os.path.join(work_dir, "manifest.json"), "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "anime.db")
            archive.write(os.path.join(work_dir, "manifest.json"), "manifest.json")
            for item in manifest["files"].values():
                archive.write(os.path.join(work_dir, item["path"]), item["path"])

        return len(manifest["files"]), len(manifest["failed"])


async def _reupload_embedded_media(bot, chat_id):
    """Bitta .db ichiga joylangan media'ni botga qayta yuklaydi."""
    with _DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT old_file_id, media_type, data FROM backup_media"
            ).fetchall()
        except sqlite3.Error:
            return 0, 0

    replacements = {}
    failed = 0
    for old_file_id, media_type, data in rows:
        try:
            media = io.BytesIO(data)
            media.name = "restore.mp4" if media_type == "video" else "restore.jpg"
            if media_type == "video":
                message = await bot.send_video(chat_id=chat_id, video=media)
                new_file_id = message.video.file_id
            else:
                message = await bot.send_photo(chat_id=chat_id, photo=media)
                new_file_id = message.photo[-1].file_id
            replacements[old_file_id] = new_file_id
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as exc:
            failed += 1
            logger.warning("DB ichidagi media tiklanmadi: %s", exc)

    with _DB_LOCK:
        conn = get_db()
        _ensure_season_cover_column(conn)
        for old_file_id, new_file_id in replacements.items():
            conn.execute("UPDATE animes SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE animes SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE seasons SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE seasons SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE episodes SET video_file_id=? WHERE video_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE app_meta SET value=? WHERE key='global_episode_cover' AND value=?", (new_file_id, old_file_id))
        conn.commit()
    return len(replacements), failed


MAX_BACKUP_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_BACKUP_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_MEMBER_BYTES = 512 * 1024 * 1024
MAX_BACKUP_MEMBERS = 5000


def _safe_extract_zip(archive_path, target_dir):
    archive_size = os.path.getsize(archive_path)
    if archive_size > MAX_BACKUP_ARCHIVE_BYTES:
        raise RuntimeError("Backup ZIP hajmi ruxsat etilgan limitdan katta")

    with zipfile.ZipFile(archive_path) as archive:
        target_root = os.path.realpath(target_dir) + os.sep
        total_uncompressed = 0
        members = archive.infolist()
        if len(members) > MAX_BACKUP_MEMBERS:
            raise RuntimeError("Backup ZIP ichida juda ko'p fayl bor")

        for member in members:
            if member.file_size > MAX_BACKUP_MEMBER_BYTES:
                raise RuntimeError("Backup ZIP ichidagi fayl hajmi juda katta")
            total_uncompressed += member.file_size
            if total_uncompressed > MAX_BACKUP_EXTRACTED_BYTES:
                raise RuntimeError("Backup ochilgandan keyingi hajm ruxsat etilgan limitdan katta")
            # Symlink orqali target papkadan tashqariga chiqishni ham bloklaymiz.
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError("Backup arxivida symbolic link ruxsat etilmaydi")
            destination = os.path.realpath(os.path.join(target_dir, member.filename))
            if not destination.startswith(target_root):
                raise RuntimeError("Backup arxivida xavfli fayl yo'li bor")
        archive.extractall(target_dir)


async def _reupload_restored_media(bot, chat_id, restore_dir, manifest):
    """Arxivdagi media fayllarni joriy botga yuklaydi va yangi file_idlarni qaytaradi."""
    if not manifest or not manifest.get("files"):
        return 0, 0

    replacements = {}
    failed = 0
    restore_root = os.path.realpath(restore_dir) + os.sep
    for old_file_id, item in manifest["files"].items():
        relative_path = item.get("path") if isinstance(item, dict) else None
        media_path = os.path.realpath(os.path.join(restore_dir, relative_path or ""))
        if not media_path.startswith(restore_root) or not os.path.isfile(media_path):
            failed += 1
            continue
        try:
            with open(media_path, "rb") as media_file:
                if item.get("type") == "video":
                    message = await bot.send_video(chat_id=chat_id, video=media_file)
                    new_file_id = message.video.file_id
                else:
                    message = await bot.send_photo(chat_id=chat_id, photo=media_file)
                    new_file_id = message.photo[-1].file_id
            replacements[old_file_id] = new_file_id
            try:
                await message.delete()
            except Exception:
                pass
        except Exception as exc:
            failed += 1
            logger.warning("Restore media qayta yuklanmadi: %s", exc)

    if replacements:
        with _DB_LOCK:
            conn = get_db()
            _ensure_season_cover_column(conn)
            for old_file_id, new_file_id in replacements.items():
                conn.execute("UPDATE animes SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
                conn.execute("UPDATE animes SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
                conn.execute("UPDATE seasons SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
                conn.execute("UPDATE seasons SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
                conn.execute("UPDATE episodes SET video_file_id=? WHERE video_file_id=?", (new_file_id, old_file_id))
                conn.execute("UPDATE app_meta SET value=? WHERE key='global_episode_cover' AND value=?", (new_file_id, old_file_id))
            conn.commit()

    return len(replacements), failed


async def backup_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    message = update.message or update.callback_query.message
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    filename = f"anime_backup_{timestamp}.db"
    tmp_path = f"/tmp/{filename}"
    try:
        _media_count, media_ref_count = await _create_media_database(
            context.bot, os.path.abspath("anime.db"), tmp_path
        )
        with open(tmp_path, "rb") as f:
            await message.reply_document(
                document=f,
                filename=filename,
                caption=(
                    f"💾 Zaxira nusxa tayyor (faqat baza, media fayllarsiz).\n"
                    f"🔗 file_id orqali bog'langan media: {media_ref_count} ta "
                    f"(rasm/video o'zi yuklanmagan — botning shu tokeni orqali ishlashda davom etadi)\n"
                    f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                )
            )
    except Exception as e:
        logger.warning(f"Backup olishda xato: {e}")
        await message.reply_text(f"❌ Zaxira olishda xatolik: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

async def restore_db_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    message = update.message or update.callback_query.message
    await message.reply_text(
        "♻️ Tiklamoqchi bo'lgan *.db* faylini yuboring.\n\n"
        "⚠️ *Diqqat:* bu joriy ma'lumotlar bazasini butunlay almashtiradi — "
        "hozirgi barcha ma'lumotlar yuborilgan fayl bilan almashtiriladi!",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_restore_file"] = True

async def got_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_primary_admin(update.effective_user.id):
        return
    if not context.user_data.get("awaiting_restore_file"):
        return
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith((".db", ".zip")):
        await update.message.reply_text("❌ Faqat *.db yoki *.zip backup fayl yuboring!", parse_mode="Markdown")
        return
    context.user_data["awaiting_restore_file"] = False
    context.user_data["restore_file_id"] = doc.file_id
    context.user_data["restore_file_name"] = doc.file_name
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha, tiklash", callback_data="restore_confirm"),
        InlineKeyboardButton("❌ Yo'q, bekor qilish", callback_data="restore_cancel"),
    ]])
    await update.message.reply_text(
        "⚠️ Rostdan ham joriy ma'lumotlar bazasini shu fayl bilan almashtirmoqchimisiz?\n"
        "Bu amalni qaytarib bo'lmaydi!",
        reply_markup=kb
    )

async def restore_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_primary_admin(query.from_user.id):
        return
    if query.data == "restore_cancel":
        context.user_data.pop("restore_file_id", None)
        context.user_data.pop("restore_file_name", None)
        await query.message.edit_text("❌ Tiklash bekor qilindi.")
        return

    file_id = context.user_data.get("restore_file_id")
    file_name = context.user_data.get("restore_file_name", "")
    if not file_id:
        await query.message.edit_text("❌ Xatolik: fayl topilmadi. Qaytadan «♻️ Backup Tiklash» dan boshlang.")
        return

    db_path = os.path.abspath("anime.db")
    # os.replace() cross-device ishlamaydi. Vaqtinchalik fayllar anime.db
    # bilan bir xil fayl tizimida bo'lishi kerak.
    db_dir = os.path.dirname(db_path)
    tmp_path = os.path.join(db_dir, f".restore_upload_{query.from_user.id}.db")
    old_path = os.path.join(db_dir, f".anime_before_restore_{query.from_user.id}.db")
    restore_work_dir = None
    source_db_path = tmp_path
    restore_manifest = None
    old_backup_created = False

    def validate_restore_db(path):
        """Backup to'liq SQLite baza ekanini almashtirishdan oldin tekshiradi."""
        test_conn = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
        try:
            integrity = test_conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError("SQLite integrity_check muvaffaqiyatsiz tugadi")

            tables = {
                row[0]
                for row in test_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            required_tables = {
                "animes", "episodes", "users", "seasons",
                "admins", "required_channels", "app_meta",
            }
            missing = required_tables - tables
            if missing:
                raise RuntimeError(
                    f"Kerakli jadvallar topilmadi: {', '.join(sorted(missing))}"
                )

            required_columns = {
                "animes": {"code", "name"},
                "seasons": {"anime_code", "season_num"},
                "episodes": {"season_id", "episode_num", "video_file_id"},
            }
            for table, cols in required_columns.items():
                existing_cols = {
                    row[1] for row in test_conn.execute(f"PRAGMA table_info({table})")
                }
                missing_cols = cols - existing_cols
                if missing_cols:
                    raise RuntimeError(
                        f"'{table}' jadvalida kerakli ustunlar yo'q: {', '.join(sorted(missing_cols))}"
                    )

            test_conn.execute("SELECT COUNT(*) FROM animes").fetchone()
        finally:
            test_conn.close()

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(tmp_path)
        if file_name.lower().endswith(".zip"):
            restore_work_dir = tempfile.mkdtemp(prefix="anime_restore_")
            _safe_extract_zip(tmp_path, restore_work_dir)
            source_db_path = os.path.join(restore_work_dir, "anime.db")
            manifest_path = os.path.join(restore_work_dir, "manifest.json")
            if not os.path.isfile(source_db_path):
                raise RuntimeError("ZIP backup ichida anime.db topilmadi")
            if os.path.isfile(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                    restore_manifest = json.load(manifest_file)
        validate_restore_db(source_db_path)

        global _DB_CONN
        with _DB_LOCK:
            # WAL fayllari yangi baza bilan aralashib ketmasligi uchun avval checkpoint qilamiz.
            if _DB_CONN is not None:
                try:
                    _DB_CONN.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                _DB_CONN.close()
                _DB_CONN = None

            # Haqiqiy almashtirishdan oldin joriy bazaning qaytarish nusxasini saqlaymiz.
            if os.path.exists(db_path):
                shutil.copy2(db_path, old_path)
                old_backup_created = True

            for sidecar in (f"{db_path}-wal", f"{db_path}-shm"):
                if os.path.exists(sidecar):
                    os.remove(sidecar)

            # os.replace atomik ishlaydi: yarim ko'chgan baza qolib ketmaydi.
            os.replace(source_db_path, db_path)
            get_db()  # yangi tiklangan faylga qayta ulanadi
        # Backup shu botning o'zidan olingan bo'lsa, migratsiyani qayta ishga
        # tushirish shart emas. Bu bosqichdagi xato tiklangan bazani xato deb
        # ko'rsatib qo'yishi mumkin.

        context.user_data.pop("restore_file_id", None)
        context.user_data.pop("restore_file_name", None)
        if old_backup_created and os.path.exists(old_path):
            os.remove(old_path)
    except Exception as e:
        logger.exception("Backup tiklashda xato")
        # Tiklashning oxirgi bosqichida xato bo'lsa, foydalanuvchi ma'lumotlarini saqlab qolamiz.
        try:
            with _DB_LOCK:
                if _DB_CONN is not None:
                    _DB_CONN.close()
                    _DB_CONN = None
                for sidecar in (f"{db_path}-wal", f"{db_path}-shm"):
                    if os.path.exists(sidecar):
                        os.remove(sidecar)
                if old_backup_created and os.path.exists(old_path):
                    os.replace(old_path, db_path)
                    get_db()
        except Exception:
            logger.exception("Eski bazani qaytarishda xato")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if restore_work_dir and os.path.isdir(restore_work_dir):
            shutil.rmtree(restore_work_dir, ignore_errors=True)
        context.user_data.pop("restore_file_id", None)
        context.user_data.pop("restore_file_name", None)
        await query.message.edit_text(
            "❌ Backup tiklanmadi.\n"
            f"Sabab: {e}\n"
            "Joriy baza xavfsizlik uchun saqlab qolindi."
        )
        return

    # Telegram xabarini yangilashdagi alohida xato tiklashni bekor qilmasligi
    # kerak: baza bu nuqtaga kelganda allaqachon muvaffaqiyatli tiklangan.
    try:
        media_text = ""
        if restore_manifest:
            restored_count, failed_count = await _reupload_restored_media(
                context.bot, query.from_user.id, restore_work_dir, restore_manifest
            )
            media_text = (
                f"\n📦 Media qayta tiklandi: {restored_count} ta."
                f"\n⚠️ Tiklanmagan media: {failed_count} ta."
            )
        else:
            restored_count, failed_count = await _reupload_embedded_media(
                context.bot, query.from_user.id
            )
            if restored_count or failed_count:
                media_text = (
                    f"\n📦 Media qayta tiklandi: {restored_count} ta."
                    f"\n⚠️ Tiklanmagan media: {failed_count} ta."
                )
            else:
                media_text = (
                    "\n⚠️ Bu eski .db backup edi: unda poster/video fayllari yo‘q."
                    "\nYangi «💾 Backup Olish» orqali olingan .db fayl media bilan tiklanadi."
                )
        await query.message.edit_text("✅ Backup muvaffaqiyatli tiklandi." + media_text)
    except Exception:
        logger.exception("Backup tiklangani haqida xabar yuborishda xato")
    finally:
        if restore_work_dir and os.path.isdir(restore_work_dir):
            shutil.rmtree(restore_work_dir, ignore_errors=True)

async def admins_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    message = update.message or update.callback_query.message
    buttons, admins = _admins_kb()
    text = "👥 *Adminlar ro'yxati:*\n\n"
    if admins:
        for uid, date in admins:
            text += f"• `{uid}` — {date}\n"
    else:
        text += "Hali qo'shimcha admin yo'q.\n"
    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def admin_manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "add_admin":
        context.user_data["awaiting_admin_id"] = True
        await query.message.reply_text(
            "🆔 Yangi adminning Telegram ID raqamini yuboring:\n"
            "_(ID ni bilish uchun @userinfobot dan foydalanishi mumkin)_",
            parse_mode="Markdown"
        )
        return

    if data.startswith("rmadmin_"):
        uid = int(data[8:])
        remove_admin(uid)
        buttons, admins = _admins_kb()
        text = "👥 *Adminlar ro'yxati:*\n\n"
        if admins:
            for a_uid, date in admins:
                text += f"• `{a_uid}` — {date}\n"
        else:
            text += "Hali qo'shimcha admin yo'q.\n"
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def got_add_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.user_data.get("awaiting_admin_id"):
        return
    context.user_data["awaiting_admin_id"] = False
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Faqat raqamli Telegram ID yuboring!")
        return
    new_admin_id = int(text)
    add_admin(new_admin_id, update.effective_user.id)
    try:
        await context.bot.send_message(
            chat_id=new_admin_id,
            text="👑 Sizga admin huquqi berildi! /admin buyrug'ini yuboring."
        )
    except Exception:
        pass
    buttons, admins = _admins_kb()
    text_out = f"✅ *{new_admin_id}* admin qilib qo'shildi!\n\n👥 *Adminlar ro'yxati:*\n\n"
    for a_uid, date in admins:
        text_out += f"• `{a_uid}` — {date}\n"
    await update.message.reply_text(text_out, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in ("awaiting_channel", "awaiting_channel_forward", "awaiting_channel_title",
                "awaiting_channel_custom_days", "awaiting_admin_id", "pending_channel", "pending_channel_link",
                "awaiting_instagram_link", "awaiting_auto_backup_channel", "awaiting_auto_backup_times"):
        context.user_data.pop(key, None)
    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=admin_menu_keyboard(update.effective_user.id) if is_admin(update.effective_user.id) else ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# ==================== UNIVERSAL CONVERSATION ESCAPE FALLBACKS ====================
async def _start_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END

async def _admin_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await admin_command(update, context)
    return ConversationHandler.END

async def _interrupt_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    txt = update.message.text if update.message else ""
    direct_map = {
        "📋 Animeler Ro'yxati": show_anime_list,
        "📊 Statistika":        show_stats,
        "📡 Kanallar":          manage_channels,
        "🔙 Asosiy Menu":       start,
        "🔍 Anime Izlash":      anime_search,
        "📢 Reklama":           reklama_info,
        "📖 Qo'llanma":         guide_info,
        "📺 Animelar Kanali":   channel_info,
        "📤 Kanalga Yuborish":  channel_send_list,
        "👥 Adminlar":          admins_panel,
        "🆕 Yangi Qismlar":     admin_recent_episodes_panel,
        "💾 Backup Olish":      backup_db_command,
        "♻️ Backup Tiklash":    restore_db_start,
        "🏷 Anime Holati":      anime_status_list_start,
        "📊 So'rovnomalar":     survey_admin_start,
    }
    direct = direct_map.get(txt)
    if direct:
        await direct(update, context)
    else:
        user_is_admin = is_admin(update.effective_user.id)
        await update.message.reply_text(
            f"⚠️ Oldingi jarayon bekor qilindi.\nDavom etish uchun yana bir marta «{txt}» tugmasini bosing.",
            reply_markup=admin_menu_keyboard(update.effective_user.id) if user_is_admin else ReplyKeyboardRemove()
        )
    return ConversationHandler.END

# ==================== MAIN ====================
async def _auto_backup_loop_async(application):
    """Bitta hostingda ishlaydigan, qo'shimcha scheduler talab qilmaydigan loop."""
    last_run_key = None
    while True:
        try:
            if _auto_backup_enabled():
                times = set(_auto_backup_times())
                channel = _auto_backup_channel()
                now = datetime.now(BACKUP_TIMEZONE)
                current_time = now.strftime("%H:%M")
                run_key = now.strftime("%Y-%m-%d %H:%M")
                if channel and current_time in times and run_key != last_run_key:
                    last_run_key = run_key
                    try:
                        await send_auto_backup_now(application.bot, channel)
                        logger.info(
                            "Avtomatik backup yuborildi: channel=%s vaqt=%s",
                            channel,
                            run_key,
                        )
                    except Exception:
                        logger.exception("Avtomatik backup yuborishda xato")
                        try:
                            await application.bot.send_message(
                                chat_id=ADMIN_ID,
                                text=(
                                    "⚠️ Avtomatik backup yuborilmadi.\n"
                                    f"Sabab: {datetime.now(BACKUP_TIMEZONE).strftime('%Y-%m-%d %H:%M')}"
                                )
                            )
                        except Exception:
                            pass
        except Exception:
            logger.exception("Avtomatik backup scheduler xatosi")
        await asyncio.sleep(20)

async def _post_init(application):
    application.create_task(_auto_backup_loop_async(application))

def _render_port():
    raw_port = os.environ.get("PORT", "10000").strip()
    try:
        port = int(raw_port)
    except ValueError:
        logger.warning("PORT noto'g'ri qiymatga ega: %r — 10000 ishlatiladi.", raw_port)
        return 10000
    if not 1 <= port <= 65535:
        logger.warning("PORT diapazondan tashqarida: %s — 10000 ishlatiladi.", port)
        return 10000
    return port


class _HealthCheckHandler(BaseHTTPRequestHandler):
    """Render'ning port-skanerlashi uchun eng oddiy va ishonchli javob beruvchi handler.

    Bu server Telegram bilan aloqa yoki bazani tekshirish (init_db) tugashini
    kutmaydi — port DARHOL, botning qolgan qismidan mustaqil ravishda ochiladi.
    Shu tufayli Render deployni "Timed Out" deb bekor qilmaydi."""

    def do_GET(self):
        body = b'{"status": "ok", "service": "telegram-bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # Ba'zi uptime-monitoring xizmatlari (UptimeRobot va h.k.) GET o'rniga
        # HEAD so'rovi yuborishi mumkin — javob bermasa, "down" deb belgilaydi.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        # Har bir so'rovni stderr'ga yozmaslik — bot loglarini keraksiz
        # health-check yozuvlari bilan to'ldirmaslik uchun.
        pass


def _start_health_server_thread():
    """Render kutayotgan $PORT'ni ALOHIDA background thread'da, botning asosiy
    event loop'i, bazasi yoki Telegram bilan aloqasidan mustaqil holda ochadi.

    ThreadingHTTPServer ishlatiladi — har bir ulanish o'z alohida thread'ida
    qayta ishlanadi, shuning uchun bitta sekin/tugallanmagan so'rov (masalan
    portni skanerlayotgan bot) qolgan barcha so'rovlarni (jumladan UptimeRobot
    kabi monitoring xizmatlarini) bloklab qo'ymaydi."""
    port = _render_port()
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Render health server 0.0.0.0:%s portda ishga tushdi (alohida thread).", port)
    return server


# ==================== XATOLARNI USHLASH ====================
_error_notify_times = {}

def _is_benign_error(exc):
    """Muhim bo'lmagan, odatiy xatolar: adminga xabar yuborilmaydi."""
    if isinstance(exc, (Forbidden, RetryAfter, NetworkError)):  # NetworkError ichida TimedOut ham bor
        return True
    if isinstance(exc, BadRequest):
        text = str(exc).lower()
        return any(s in text for s in (
            "message is not modified", "query is too old", "query id is invalid",
            "message to edit not found", "message can't be edited", "message to delete not found",
        ))
    return False

async def error_handler(update, context):
    """Kutilmagan xatolar: log'ga yozadi, adminga qisqa hisobot yuboradi, foydalanuvchiga muloyim javob beradi."""
    exc = context.error
    logger.error("Handler xatosi", exc_info=exc)
    if exc is None or _is_benign_error(exc):
        return
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    tb_lines = tb.split("\n")
    signature = f"{type(exc).__name__}:{tb_lines[-3] if len(tb_lines) >= 3 else ''}"
    now = time.monotonic()
    if len(_error_notify_times) > 200:
        _error_notify_times.clear()
    notify_admin = now - _error_notify_times.get(signature, 0.0) >= 60  # bir xil xato 1 daqiqada bir marta
    if notify_admin:
        _error_notify_times[signature] = now

    user_id = None
    request_text = "—"
    if isinstance(update, Update):
        if update.effective_user:
            user_id = update.effective_user.id
        if update.callback_query:
            request_text = f"tugma: {update.callback_query.data}"
        elif update.message:
            request_text = (update.message.text or update.message.caption or "(matnsiz xabar)")[:100]

    if notify_admin:
        report = (
            f"⚠️ Bot xatosi\n\n"
            f"{type(exc).__name__}: {str(exc)[:300]}\n\n"
            f"👤 Foydalanuvchi: {user_id if user_id is not None else '—'}\n"
            f"📩 So'rov: {request_text}\n\n"
            f"{chr(10).join(tb_lines[-8:])}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=report[:3900])
        except Exception:
            logger.exception("Xato hisobotini adminga yuborib bo'lmadi")

    if isinstance(update, Update) and user_id is not None and not is_admin(user_id):
        notice = "⚠️ Kutilmagan xatolik yuz berdi. Iltimos, birozdan keyin qayta urinib ko'ring."
        try:
            if update.callback_query:
                await update.callback_query.answer(notice, show_alert=True)
            elif update.message:
                await update.message.reply_text(notice)
        except Exception:
            pass

def _install_markdown_fallback():
    """Matnda Markdown'ga zid belgi (masalan _ yoki *) bo'lib, xabar yuborilmay qolsa,
    xabar parse_mode'siz, oddiy matn sifatida qayta yuboriladi."""
    def make_wrapper(orig):
        @functools.wraps(orig)
        async def wrapper(self, *args, **kwargs):
            try:
                return await orig(self, *args, **kwargs)
            except BadRequest as exc:
                if "can't parse entities" in str(exc).lower() and kwargs.get("parse_mode"):
                    logger.warning("Markdown xatosi, oddiy matn sifatida qayta yuborilmoqda: %s", exc)
                    kwargs["parse_mode"] = None
                    return await orig(self, *args, **kwargs)
                raise
        wrapper._md_fallback = True
        return wrapper
    for name in ("send_message", "edit_message_text", "send_photo", "send_video",
                 "send_animation", "send_document", "edit_message_caption"):
        orig = getattr(Bot, name, None)
        if orig is not None and not getattr(orig, "_md_fallback", False):
            setattr(Bot, name, make_wrapper(orig))

def main():
    # Render'ning port-skaneri kutib turgani uchun bu ENG BIRINCHI bajarilishi
    # kerak — init_db() yoki Telegram bilan bog'lanishdan oldin.
    _start_health_server_thread()
    init_db()
    _install_markdown_fallback()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()
    app.add_error_handler(error_handler)
    # Eng birinchi ishlaydi (group=-1): juda tez harakat qilayotgan oddiy foydalanuvchini to'xtatadi.
    app.add_handler(TypeHandler(Update, rate_limit_check), group=-1)
    app.add_handler(CallbackQueryHandler(watch_toggle_callback, pattern=r"^watch_\d+$"))

    # Shared escape fallbacks — added to every conversation
    _esc = [
        CommandHandler("start", _start_fallback),
        CommandHandler("admin", _admin_fallback),
        CommandHandler("cancel", cancel),
        MessageHandler(_MENU_BTN_FILTER, _interrupt_fallback),
    ]

    # Add anime conversation
    add_anime_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Anime Qo'shish$"), add_anime_start)],
        states={
            WAIT_ANIME_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_anime_code)],
            WAIT_ANIME_BULK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_anime_bulk),
                CallbackQueryHandler(got_anime_bulk_dup_confirm, pattern="^dupanime_yes$"),
            ],
            WAIT_ANIME_POSTER: [MessageHandler(filters.PHOTO | filters.VIDEO, got_anime_poster)],
        },
        fallbacks=_esc + [CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$")],
        per_message=False,
    )

    # Add episode conversation
    _done_ep_cb = CallbackQueryHandler(done_episodes_callback, pattern="^done_episodes$")
    _done_ep_yes_cb = CallbackQueryHandler(done_episodes_confirm_yes, pattern="^done_ep_yes$")
    _done_ep_no_cb = CallbackQueryHandler(done_episodes_confirm_no, pattern="^done_ep_no$")
    add_episode_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📺 Qism Qo'shish$"), add_episode_start),
            MessageHandler(filters.Regex("^🏷 Anime Holati$"), anime_status_list_start),
            CallbackQueryHandler(quick_episode_select_callback, pattern="^quickep_"),
        ],
        states={
            WAIT_EPISODE_ANIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_episode_anime)],
            WAIT_EPISODE_POSTER: [MessageHandler(filters.PHOTO | filters.VIDEO, got_episode_poster)],
            WAIT_EPISODE_NUM: [
                _done_ep_cb,
                _done_ep_yes_cb,
                _done_ep_no_cb,
                CallbackQueryHandler(epseason_select_callback, pattern="^epseason_\\d"),
                CallbackQueryHandler(epseason_new_callback, pattern="^epseason_new$"),
                CallbackQueryHandler(got_episode_upload_start, pattern="^ep_upload_start$"),
            ],
            WAIT_NEWSEASON_EPISODES: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_newseason_episodes)],
            WAIT_NEWSEASON_POSTER: [MessageHandler(filters.PHOTO | filters.VIDEO, got_newseason_poster)],
            WAIT_EPISODE_VIDEO: [
                _done_ep_cb,
                _done_ep_yes_cb,
                _done_ep_no_cb,
                MessageHandler(filters.VIDEO | filters.Document.ALL, got_episode_video),
            ],
        },
        fallbacks=_esc + [_done_ep_cb, CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$")],
        per_message=False,
    )

    # Episode management conversation (delete / renumber)
    epm_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🛠 Qism Boshqarish$"), epm_start)],
        states={
            WAIT_EPM_ANIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_epm_anime),
                CallbackQueryHandler(epm_season_select_callback, pattern="^epmseason_"),
                CallbackQueryHandler(epm_allanime_ask_callback, pattern="^epm_allanime$"),
            ],
            WAIT_EPM_ACTION: [
                CallbackQueryHandler(epm_select_callback, pattern="^epm_sel_"),
                CallbackQueryHandler(epm_delete_ask_callback, pattern="^epm_del_"),
                CallbackQueryHandler(epm_delete_confirm_callback, pattern="^epm_delyes_"),
                CallbackQueryHandler(epm_rename_ask_callback, pattern="^epm_ren_"),
                CallbackQueryHandler(epm_multi_callback, pattern="^epm_multi$"),
                CallbackQueryHandler(epm_page_callback, pattern=r"^epm_pg_\d+$"),
                CallbackQueryHandler(epm_multipage_callback, pattern=r"^epm_mpg_\d+$"),
                CallbackQueryHandler(epm_noop_callback, pattern="^epm_noop$"),
                CallbackQueryHandler(epm_toggle_callback, pattern="^epm_tgl_"),
                CallbackQueryHandler(epm_selected_ask_callback, pattern="^epm_selgo$"),
                CallbackQueryHandler(epm_selected_confirm_callback, pattern="^epm_selyes$"),
                CallbackQueryHandler(epm_allseason_ask_callback, pattern="^epm_allseason$"),
                CallbackQueryHandler(epm_allseason_confirm_callback, pattern="^epm_allseasonyes$"),
                CallbackQueryHandler(epm_allanime_confirm_callback, pattern="^epm_allanimeyes$"),
                CallbackQueryHandler(epm_cancel_callback, pattern="^epm_cancel$"),
            ],
            WAIT_EPM_NEWNUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_epm_newnum)],
        },
        fallbacks=_esc,
        per_message=False,
    )

    # Delete anime conversation
    delete_anime_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🗑 Anime O'chirish$"), delete_anime_start)],
        states={
            WAIT_DELETE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_delete_code)],
            WAIT_DELETE_CONFIRM: [CallbackQueryHandler(got_delete_confirm, pattern="^delconfirm_(yes|no)$")],
        },
        fallbacks=_esc,
        per_message=False,
    )

    # Edit anime conversation
    edit_anime_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ Anime Tahrirlash$"), edit_anime_start)],
        states={
            WAIT_EDIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_code)],
            WAIT_EDIT_FIELD: [CallbackQueryHandler(got_edit_field_callback, pattern="^(editfield_|editseason_|editstatus|editposter|cancel_anime)")],
            WAIT_EDIT_VALUE: [
                CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$"),
                MessageHandler(filters.PHOTO | filters.VIDEO, got_edit_poster),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_value),
            ],
        },
        fallbacks=_esc + [CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$")],
        per_message=False,
    )

    # Broadcast conversation
    broadcast_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📣 Xabar Yuborish$"), broadcast_start),
            CallbackQueryHandler(broadcast_start_callback, pattern="^botset_broadcast$"),
        ],
        states={
            WAIT_BROADCAST_MSG: [
                CallbackQueryHandler(cancel_broadcast_callback, pattern="^cancel_broadcast$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_broadcast_msg),
                MessageHandler(filters.PHOTO, got_broadcast_msg),
            ],
        },
        fallbacks=_esc + [CallbackQueryHandler(cancel_broadcast_callback, pattern="^cancel_broadcast$")],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cover", global_cover_command))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, global_cover_photo), group=1)
    app.add_handler(add_anime_conv)
    app.add_handler(add_episode_conv)
    app.add_handler(epm_conv)
    app.add_handler(delete_anime_conv)
    app.add_handler(edit_anime_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(search_result_callback, pattern="^srch_"))
    app.add_handler(CallbackQueryHandler(search_menu_callback, pattern="^srchmenu_"))
    app.add_handler(CallbackQueryHandler(search_genre_pick_callback, pattern="^srchgnr_"))
    app.add_handler(CallbackQueryHandler(browse_all_page_callback, pattern="^allanp_"))
    app.add_handler(CallbackQueryHandler(inline_menu_callback, pattern="^(anime_search|kabinet|guide|reklama)$"))
    app.add_handler(CallbackQueryHandler(
        manage_channels_callback,
        pattern="^(add_channel|rmchan_.+|set_instagram|rm_instagram)$"
    ))
    app.add_handler(CallbackQueryHandler(channel_expiry_callback, pattern="^chexp_"))
    app.add_handler(CallbackQueryHandler(channel_send_page_callback, pattern="^chpage_"))
    app.add_handler(CallbackQueryHandler(recent_ep_page_callback, pattern="^annpage_"))
    app.add_handler(CallbackQueryHandler(channel_send_bycode_callback, pattern="^chsel_bycode$"))
    app.add_handler(CallbackQueryHandler(channel_send_all_ask, pattern="^chsendall_ask$"))
    app.add_handler(CallbackQueryHandler(channel_send_all_yes, pattern="^chsendall_yes$"))
    app.add_handler(CallbackQueryHandler(channel_send_all_no, pattern="^chsendall_no$"))
    app.add_handler(CallbackQueryHandler(chsel_callback, pattern="^chsel_"))
    app.add_handler(CallbackQueryHandler(chsend_callback, pattern="^chsend_"))
    app.add_handler(CallbackQueryHandler(admin_manage_callback, pattern="^(add_admin|rmadmin_.+)$"))
    app.add_handler(CallbackQueryHandler(admin_new_episode_image_choice, pattern="^annepimg_"))
    app.add_handler(CallbackQueryHandler(admin_new_episode_channel_send, pattern="^annep_"))
    app.add_handler(CallbackQueryHandler(show_season_callback, pattern="^showseason_"))
    # Bot settings callbacks must run before the catch-all episode handler.
    app.add_handler(CallbackQueryHandler(global_cover_cancel, pattern="^cover_cancel$"))
    app.add_handler(CallbackQueryHandler(survey_answer_callback, pattern=r"^svy_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(survey_admin_callback, pattern="^svyadm_"))
    app.add_handler(CallbackQueryHandler(bot_settings_callback, pattern="^botset_"))
    # Restore callbacks must be registered before the catch-all episode handler.
    # Otherwise "restore_confirm"/"restore_cancel" are swallowed silently.
    app.add_handler(CallbackQueryHandler(restore_confirm_callback, pattern="^restore_(confirm|cancel)$"))
    app.add_handler(CallbackQueryHandler(episode_callback))

    app.add_handler(MessageHandler(filters.FORWARDED, got_channel_forward), group=-1)
    app.add_handler(ChatJoinRequestHandler(record_join_request))

    app.add_handler(MessageHandler(filters.Regex("^🔍 Anime Izlash$"), anime_search))
    app.add_handler(MessageHandler(filters.Regex("^(📖 Qo'llanma|⏭ Shorts)"), guide_info))
    app.add_handler(MessageHandler(filters.Regex("^📢 Reklama$"), reklama_info))
    app.add_handler(MessageHandler(filters.Regex("^📺 Animelar Kanali$"), channel_info))
    app.add_handler(MessageHandler(filters.Regex("^📊 Statistika$"), show_stats))
    app.add_handler(MessageHandler(filters.Regex("^📊 So'rovnomalar$"), survey_admin_start))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Bot Sozlamalari$"), bot_settings_start))
    app.add_handler(MessageHandler(filters.ANIMATION, handle_start_gif_upload))
    app.add_handler(MessageHandler(filters.Regex("^📋 Animeler Ro'yxati$"), show_anime_list))
    app.add_handler(MessageHandler(filters.Regex("^📡 Kanallar$"), manage_channels))
    app.add_handler(MessageHandler(filters.Regex("^📤 Kanalga Yuborish$"), channel_send_list))
    app.add_handler(MessageHandler(filters.Regex("^👥 Adminlar$"), admins_panel))
    app.add_handler(MessageHandler(filters.Regex("^🆕 Yangi Qismlar$"), admin_recent_episodes_panel))
    app.add_handler(MessageHandler(filters.Regex("^🔙 Asosiy Menu$"), start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, got_episode_channel_poster))
    app.add_handler(MessageHandler(filters.Regex("^💾 Backup Olish$"), backup_db_command))
    app.add_handler(MessageHandler(filters.Regex("^♻️ Backup Tiklash$"), restore_db_start))
    app.add_handler(MessageHandler(filters.Document.ALL, got_restore_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_code))

    print("✅ Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
