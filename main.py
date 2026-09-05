import logging
import os
import shutil
import re
import asyncio
import sqlite3
import threading
import json
import tempfile
import zipfile
import io
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler,
    ChatJoinRequestHandler, filters
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
    "🔍 Anime Izlash", "⏭ Shorts — Tez Orada!", "📢 Reklama", "📺 Animelar Kanali"
}

# Filter matching every reply-keyboard button — used as a universal conversation escape
_MENU_BTN_FILTER = filters.Regex(
    r"^(➕ Anime Qo'shish|📺 Qism Qo'shish|📋 Animeler Ro'yxati"
    r"|📊 Statistika|🗑 Anime O'chirish|✏️ Anime Tahrirlash|📡 Kanallar"
    r"|📣 Xabar Yuborish|🔙 Asosiy Menu|🔍 Anime Izlash"
    r"|📢 Reklama|📺 Animelar Kanali|📤 Kanalga Yuborish|👥 Adminlar|🆕 Yangi Qismlar|🛠 Qism Boshqarish|💾 Backup Olish|♻️ Backup Tiklash|🏷 Anime Holati|⏭ Shorts.*)$"
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
# Butun bot davomida bitta umumiy ulanishdan foydalaniladi — har bir so'rov uchun
# alohida sqlite3.connect()/close() ochish ortiqcha xarajat va sekinlikka olib kelardi.
_DB_CONN = None

def get_db():
    global _DB_CONN
    if _DB_CONN is None:
        _DB_CONN = sqlite3.connect("anime.db", check_same_thread=False)
        _DB_CONN.execute("PRAGMA journal_mode=WAL")       # bir vaqtda o'qish va yozishga ruxsat beradi
        _DB_CONN.execute("PRAGMA synchronous=NORMAL")     # WAL bilan xavfsiz, sezilarli tezroq yozish
        _DB_CONN.execute("PRAGMA cache_size=-10000")      # ~10 MB keshni xotirada saqlaydi (ko'p o'qishlarni tezlashtiradi)
    return _DB_CONN

def init_db():
    conn = get_db()
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
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
    try:
        c.execute("ALTER TABLE animes ADD COLUMN episode_thumb_file_id TEXT")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
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
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
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
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
    try:
        c.execute("ALTER TABLE required_channels ADD COLUMN expires_at TEXT")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
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
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE seasons ADD COLUMN total_episodes_label TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN poster_type TEXT DEFAULT 'photo'")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN total_episodes_label TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN added_at REAL")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
    try:
        c.execute("ALTER TABLE animes ADD COLUMN status TEXT")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud
    try:
        c.execute("ALTER TABLE animes ADD COLUMN original_title TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN rating REAL")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN is_featured INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE animes ADD COLUMN is_popular INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Eski (vaqt belgisi yo'q) animelarga hozirgi vaqtni belgilaymiz — shunda ular darhol
    # 48 soatlik ro'yxatlarga (O'chirish/Tahrirlash/Kanalga Yuborish) kirib keladi.
    # Bu faqat vaqt belgisi ALI yo'q qatorlarga tegadi, shuning uchun xavfsiz bir martalik amal.
    c.execute("UPDATE animes SET added_at=? WHERE added_at IS NULL", (datetime.now().timestamp(),))
    try:
        c.execute("ALTER TABLE episodes ADD COLUMN season_id INTEGER")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon mavjud

    # Qism video cover'i endi alohida animes.episode_thumb_file_id ustunida saqlanadi.
    # Avvalgi versiya cover'ni fasl posteriga yozib qo'ygan bo'lishi mumkin. Quyidagi
    # tiklash faqat bir marta bajariladi; keyingi yangi fasl posterlariga tegilmaydi.
    c.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)")
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
            "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
            ("episode_cover_separation_v1", datetime.now().isoformat())
        )

    # Tezlik uchun indekslar (anime/qism ko'payishi bilan sekinlashmasligi uchun)
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(season_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_episodes_season_num ON episodes(season_id, episode_num)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_seasons_anime ON seasons(anime_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_animes_code ON animes(code)")

    # Migratsiya: har bir anime uchun 1-fasl yozuvi yo'q bo'lsa, avtomatik yaratamiz
    # (eski, fasl tushunchasi bo'lmagan davrda qo'shilgan animelar/qismlar uchun)
    c.execute("SELECT code, total_episodes, poster_file_id FROM animes")
    for code, total_ep, poster_id in c.fetchall():
        c.execute("SELECT id FROM seasons WHERE anime_code=? AND season_num=1", (code,))
        if not c.fetchone():
            c.execute(
                "INSERT INTO seasons (anime_code, season_num, poster_file_id, total_episodes, added_date) VALUES (?, 1, ?, ?, ?)",
                (code, poster_id, total_ep, datetime.now().strftime("%Y-%m-%d"))
            )
            season1_id = c.lastrowid
            c.execute(
                "UPDATE episodes SET season_id=? WHERE anime_code=? AND season_id IS NULL",
                (season1_id, code)
            )
    conn.commit()

def get_next_code():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT MAX(code) FROM animes")
    result = c.fetchone()[0]
    return (result or 0) + 1

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

def update_anime_field(code, field, value):
    if field not in ALLOWED_ANIME_FIELDS:
        raise ValueError(f"Ruxsat etilmagan ustun: {field}")
    conn = get_db()
    c = conn.cursor()
    c.execute(f"UPDATE animes SET {field}=? WHERE code=?", (value, code))
    conn.commit()

def set_anime_status(code, status_key):
    if status_key not in ANIME_STATUSES:
        raise ValueError(f"Noma'lum holat: {status_key}")
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE animes SET status=? WHERE code=?", (status_key, code))
    conn.commit()

def get_anime_status(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status FROM animes WHERE code=?", (code,))
    row = c.fetchone()
    return row[0] if row else None

def get_animes_by_status(status_key):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name FROM animes WHERE status=? ORDER BY id", (status_key,))
    return c.fetchall()

def add_episode(season_id, episode_num, video_file_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO episodes (season_id, episode_num, video_file_id, added_at)
        VALUES (?, ?, ?, ?)
    """, (season_id, episode_num, video_file_id, datetime.now().timestamp()))
    conn.commit()

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

def get_anime_by_code(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM animes WHERE code=?", (code,))
    result = c.fetchone()
    return result

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

def get_all_animes():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name, year, genre, total_episodes FROM animes ORDER BY id")
    result = c.fetchall()
    return result

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

def find_animes_by_name(name):
    """Nomi bo'yicha (harf katta-kichikligiga qaramasdan) o'xshash animelarni topadi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, name FROM animes WHERE LOWER(name) LIKE ?", (f"%{name.lower()}%",))
    result = c.fetchall()
    return result

def increment_channel_post_count(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE animes SET channel_post_count = COALESCE(channel_post_count, 0) + 1 WHERE code=?", (code,))
    conn.commit()

def get_channel_post_count(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT channel_post_count FROM animes WHERE code=?", (code,))
    row = c.fetchone()
    return row[0] if row and row[0] else 0

# -- FASLLAR (SEASONS) --
def add_season(anime_code, season_num, poster_file_id, total_episodes, poster_type="photo", total_episodes_label=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO seasons (anime_code, season_num, poster_file_id, total_episodes, added_date, poster_type, total_episodes_label) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (anime_code, season_num, poster_file_id, total_episodes, datetime.now().strftime("%Y-%m-%d"), poster_type, total_episodes_label)
    )
    conn.commit()
    season_id = c.lastrowid
    return season_id

def update_season_total_episodes(season_id, total_episodes, total_episodes_label=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE seasons SET total_episodes=?, total_episodes_label=? WHERE id=?", (total_episodes, total_episodes_label, season_id))
    conn.commit()

def update_season_poster(season_id, poster_file_id, poster_type="photo"):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE seasons SET poster_file_id=?, poster_type=? WHERE id=?", (poster_file_id, poster_type, season_id))
    conn.commit()

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

def get_anime_episode_cover(anime_code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT episode_thumb_file_id FROM animes WHERE code=?", (anime_code,))
    row = c.fetchone()
    return row[0] if row else None

def get_anime_main_poster(anime_code):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT poster_file_id, COALESCE(poster_type, 'photo') FROM animes WHERE code=?",
        (anime_code,)
    )
    return c.fetchone()

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

def get_season(anime_code, season_num):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label FROM seasons WHERE anime_code=? AND season_num=?",
        (anime_code, season_num)
    )
    result = c.fetchone()
    return result

def get_season_by_id(season_id):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, anime_code, season_num, poster_file_id, total_episodes, poster_type, total_episodes_label FROM seasons WHERE id=?",
        (season_id,)
    )
    result = c.fetchone()
    return result

def get_episode(season_id, episode_num):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT video_file_id FROM episodes WHERE season_id=? AND episode_num=?",
              (season_id, episode_num))
    result = c.fetchone()
    return result

def get_episodes_list(season_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT episode_num FROM episodes WHERE season_id=? ORDER BY episode_num",
              (season_id,))
    result = c.fetchall()
    return [r[0] for r in result]

def delete_anime(code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM seasons WHERE anime_code=?", (code,))
    season_ids = [r[0] for r in c.fetchall()]
    c.execute("DELETE FROM animes WHERE code=?", (code,))
    c.execute("DELETE FROM seasons WHERE anime_code=?", (code,))
    for sid in season_ids:
        c.execute("DELETE FROM episodes WHERE season_id=?", (sid,))
    conn.commit()

def delete_episode(season_id, episode_num):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM episodes WHERE season_id=? AND episode_num=?", (season_id, episode_num))
    conn.commit()

def update_episode_number(season_id, old_num, new_num):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE episodes SET episode_num=? WHERE season_id=? AND episode_num=?",
        (new_num, season_id, old_num)
    )
    conn.commit()

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

def add_required_channel(identifier, link, title=None, expires_at=None):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO required_channels (username, link, title, expires_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(username) DO UPDATE SET link=excluded.link, title=excluded.title, expires_at=excluded.expires_at",
        (identifier, link, title, expires_at)
    )
    conn.commit()

def remove_required_channel(identifier):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE username=?", (identifier,))
    conn.commit()

def cleanup_expired_channels():
    """Muddati o'tgan (1 hafta/15 kun/30 kun) kanallarni majburiy obuna ro'yxatidan avtomatik olib tashlaydi."""
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE expires_at IS NOT NULL AND expires_at <= ?", (datetime.now().isoformat(),))
    conn.commit()

def get_required_channels():
    cleanup_expired_channels()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, link, title, expires_at FROM required_channels")
    result = c.fetchall()
    return result

def register_user(user_id, username):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (id, username, joined_date)
        VALUES (?, ?, ?)
    """, (user_id, username or "", datetime.now().strftime("%Y-%m-%d")))
    conn.commit()

def get_all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    rows = c.fetchall()
    return [r[0] for r in rows]

def add_admin(user_id, added_by):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)",
        (user_id, added_by, datetime.now().strftime("%Y-%m-%d"))
    )
    conn.commit()

def remove_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
    conn.commit()

def get_all_admins():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, added_date FROM admins")
    rows = c.fetchall()
    return rows

def is_admin(user_id):
    """Asosiy admin yoki qo'shilgan sub-admin bo'lsa True qaytaradi."""
    if user_id == ADMIN_ID:
        return True
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    result = c.fetchone()
    return result is not None

# ==================== HELPERS ====================
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
    keyboard = [
        [KeyboardButton("🔍 Anime Izlash")],
        [KeyboardButton("⏭ Shorts — Tez Orada!"), KeyboardButton("📢 Reklama")],
        [KeyboardButton("📺 Animelar Kanali")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_menu_keyboard(user_id=None):
    keyboard = [
        [KeyboardButton("➕ Anime Qo'shish"), KeyboardButton("📺 Qism Qo'shish")],
        [KeyboardButton("📋 Animeler Ro'yxati"), KeyboardButton("📊 Statistika")],
        [KeyboardButton("🗑 Anime O'chirish"), KeyboardButton("✏️ Anime Tahrirlash")],
        [KeyboardButton("📡 Kanallar"), KeyboardButton("📣 Xabar Yuborish")],
        [KeyboardButton("📤 Kanalga Yuborish"), KeyboardButton("🆕 Yangi Qismlar")],
        [KeyboardButton("🛠 Qism Boshqarish")],
        [KeyboardButton("💾 Backup Olish"), KeyboardButton("♻️ Backup Tiklash")],
        [KeyboardButton("🏷 Anime Holati")],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([KeyboardButton("👥 Adminlar")])
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

    return InlineKeyboardMarkup(buttons)

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
    caption = (
        f"{title}\n\n"
        f"{status_line}"
        f"{code_line}"
        f"🎭 Janr: {genre}\n"
        f"📺 Jami qismlar: {ep_count_display} ta\n"
        f"✅ Yuklangan: {len(episodes)} ta\n\n"
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

async def send_anime_info(bot, chat_id, code):
    """Anime kodini kanal deep-link orqali yoki qo'lda yozilganda ko'rsatish uchun umumiy funksiya."""
    anime = get_anime_by_code(code)
    if not anime:
        await bot.send_message(chat_id=chat_id, text="❌ Bunday kodli anime topilmadi!")
        return
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

async def post_anime_to_channel(context, code, name, genre, total_episodes, poster_id, poster_type="photo", ep_label=None):
    """Admin '📤 Kanalga Yuborish' tugmasi orqali bossagina kanalga poster + ma'lumot joylash."""
    watch_url = f"https://t.me/{BOT_USERNAME}?start={code}"
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
    buttons = [[InlineKeyboardButton(f"📢 {u} ga Obuna Bo'lish", url=lnk)] for u, lnk in not_joined]
    buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")])
    await update.message.reply_text(
        "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username)

    deep_code = None
    if context.args and context.args[0].isdigit():
        deep_code = int(context.args[0])

    # Obuna faqat anime kodi orqali (havola bilan) kirganda tekshiriladi —
    # oddiy /start da botning asosiy menyusi darhol ko'rsatiladi.
    if deep_code is not None:
        if not await require_subscription(update, context, pending_code=deep_code):
            return

    await send_start(update, context, deep_code)

async def send_start(update, context, deep_code=None):
    if deep_code is not None:
        await send_anime_info(context.bot, update.effective_chat.id, deep_code)
        return

    text = (
        "👋 Assalomu aleykum botimizga xush kelibsiz.\n\n"
        "🖥 Botimizda animelerni yuklab olib, tomosha qilishingiz mumkin.\n\n"
        "‼️ Botga anime kodini yoki nomini yuborishingiz mumkin!"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Anime Izlash", callback_data="anime_search")],
        [InlineKeyboardButton("⚙️ Kabinet", callback_data="kabinet"), InlineKeyboardButton("🔴 Shorts", callback_data="shorts")],
        [InlineKeyboardButton("📺 Animelar Kanali", url=CHANNEL_LINK), InlineKeyboardButton("📢 Reklama", callback_data="reklama")],
    ])
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
            buttons = [[InlineKeyboardButton(f"📢 {u} ga Obuna Bo'lish", url=lnk)] for u, lnk in not_joined]
            buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")])
            await query.message.reply_text(
                "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
    await send_anime_info(context.bot, query.from_user.id, code)

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    not_joined = await check_subscription(query.from_user.id, context)
    if not not_joined:
        await query.answer()
        await query.message.delete()
        pending_code = context.user_data.pop("pending_anime_code", None)
        if pending_code is not None:
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
    text = (
        "👋 Assalomu aleykum botimizga xush kelibsiz.\n\n"
        "🖥 Botimizda animelerni yuklab olib, tomosha qilishingiz mumkin.\n\n"
        "‼️ Botga anime kodini yoki nomini yuborishingiz mumkin!"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Anime Izlash", callback_data="anime_search")],
        [InlineKeyboardButton("⚙️ Kabinet", callback_data="kabinet"), InlineKeyboardButton("🔴 Shorts", callback_data="shorts")],
        [InlineKeyboardButton("📺 Animelar Kanali", url=CHANNEL_LINK), InlineKeyboardButton("📢 Reklama", callback_data="reklama")],
    ])
    if user_is_admin:
        await context.bot.send_message(
            chat_id=user.id,
            text=f"👑 Admin paneliga xush kelibsiz!\n\n{text}",
            reply_markup=admin_menu_keyboard(user.id)
        )
    else:
        await context.bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=keyboard
        )

# ==================== USER HANDLERS ====================

async def anime_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔢 Anime kodini yoki nomini yuboring (masalan: 1, 2, 3... yoki \"Naruto\")")

async def shorts_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔴 Shorts — Tez Orada! Kuting...")

async def reklama_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Admin bilan bog'lanish", url=ADMIN_CONTACT_URL)]
    ])
    await update.message.reply_text(
        "📢 *REKLAMA NARXLARI*\n\n"
        "⏳ 7 kun — 25 000 so'm\n"
        "⏳ 14 kun — 40 000 so'm\n"
        "⏳ 30 kun — 70 000 so'm\n\n"
        "💬 Kerakli muddat yuqorida ko'rsatilmagan bo'lsa, admin bilan bog'laning — boshqa muddatlar bo'yicha ham kelishib olamiz.\n\n"
        "🚫 Qimor, betting yoki 18+ kanallar joylashtirilmaydi!\n\n"
        "📩 Reklama berish uchun admin bilan bog'laning:",
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

async def kabinet_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT joined_date FROM users WHERE id=?", (user.id,))
    row = c.fetchone()
    joined = row[0] if row else "—"
    await update.message.reply_text(
        f"⚙️ *Kabinet*\n\n"
        f"👤 Ism: {user.full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📅 Ro'yxatdan o'tgan: {joined}",
        parse_mode="Markdown"
    )

# ==================== INLINE BUTTON CALLBACKS ====================

async def inline_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "anime_search":
        await query.message.reply_text("🔢 Anime kodini yoki nomini yuboring (masalan: 1, 2, 3... yoki \"Naruto\")")

    elif data == "shorts":
        await query.message.reply_text("🔴 Shorts — Tez Orada! Kuting...")

    elif data == "reklama":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📩 Admin bilan bog'lanish", url=ADMIN_CONTACT_URL)]
        ])
        await query.message.reply_text(
            "📢 *REKLAMA NARXLARI*\n\n"
            "⏳ 7 kun — 25 000 so'm\n"
            "⏳ 14 kun — 40 000 so'm\n"
            "⏳ 30 kun — 70 000 so'm\n\n"
            "💬 Kerakli muddat yuqorida ko'rsatilmagan bo'lsa, admin bilan bog'laning — boshqa muddatlar bo'yicha ham kelishib olamiz.\n\n"
            "🚫 Qimor, betting yoki 18+ kanallar joylashtirilmaydi!\n\n"
            "📩 Reklama berish uchun admin bilan bog'laning:",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

    elif data == "kabinet":
        user = query.from_user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT joined_date FROM users WHERE id=?", (user.id,))
        row = c.fetchone()
        joined = row[0] if row else "—"
        await query.message.reply_text(
            f"⚙️ *Kabinet*\n\n"
            f"👤 Ism: {user.full_name}\n"
            f"🆔 ID: {user.id}\n"
            f"📅 Ro'yxatdan o'tgan: {joined}",
            parse_mode="Markdown"
        )

async def handle_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Handle awaiting channel input from admin
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel"):
        await got_add_channel(update, context)
        return

    # Handle admin qo'lda kiritayotgan kanal nomi
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_title"):
        await got_channel_title(update, context)
        return

    # Handle admin qo'lda kiritayotgan majburiy obuna muddati (kun)
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_custom_days"):
        await got_channel_custom_days(update, context)
        return

    # Handle admin "Kanalga Yuborish" uchun qo'lda kod kiritishi
    if is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_send_code"):
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
        matches = find_animes_by_name(text)
        if not matches:
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
                episode_cover = get_anime_episode_cover(season[1])

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
                    "caption": f"🎬 {anime_name} — {ep_num}-qism",
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
                buttons = [[InlineKeyboardButton(f"📢 {u} ga Obuna Bo'lish", url=lnk)] for u, lnk in not_joined]
                buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="check_sub")])
                await query.message.reply_text(
                    "🚫 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
                    reply_markup=InlineKeyboardMarkup(buttons)
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
            try:
                video_kwargs = {
                    "chat_id": query.from_user.id,
                    "video": episode[0],
                    "caption": f"🎬 {anime_name} — {ep_num}-qism",
                }
                # Qism cover'i anime katta posteridan alohida saqlanadi va faqat videoga biriktiriladi.
                episode_cover = get_anime_episode_cover(season[1]) if season else None
                if episode_cover:
                    video_kwargs["cover"] = episode_cover
                await context.bot.send_video(**video_kwargs)
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    await query.answer()
    name = context.user_data.get("ep_anime_name", "")
    count = context.user_data.get("ep_added_count", 0)
    context.user_data.clear()
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
    await update.message.reply_text(
        f"🛠 *{_esc_md(anime[2])}*\n\nQaysi faslni boshqarmoqchisiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_EPM_ANIME

async def epm_season_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
    buttons = []
    row = []
    for ep in episodes:
        row.append(InlineKeyboardButton(str(ep), callback_data=f"epm_sel_{ep}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    name = context.user_data.get("epm_name", "")
    await query.edit_message_text(
        f"🛠 *{_esc_md(name)}* — *{season_num}-fasl*\n\nQaysi qism ustida amal bajarasiz?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return WAIT_EPM_ACTION

async def epm_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
    await query.answer()
    ep_num = int(query.data[11:])
    season_id = context.user_data.get("epm_season_id")
    name = context.user_data.get("epm_name", "")
    delete_episode(season_id, ep_num)
    context.user_data.clear()
    await query.edit_message_text(f"✅ *{_esc_md(name)}* — *{ep_num}-qism* o'chirildi!", parse_mode="Markdown")
    await query.message.reply_text("👑 Admin paneli:", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def epm_rename_ask_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
    set_anime_episode_cover(code, poster_id)
    if season_id:
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
        f"✅ *{_esc_md(anime_name)}* qismlari uchun cover saqlandi.\n\nEndi qaysi faslga qism qo'shmoqchisiz?",
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
    existing = get_episodes_list(season_id)
    next_num = (max(existing) + 1) if existing else 1
    context.user_data["ep_next_num"] = next_num
    existing_str = ", ".join(str(e) for e in existing) if existing else "Yo'q"
    await query.edit_message_text(
        f"✅ Anime: *{_esc_md(context.user_data.get('ep_anime_name', ''))}*\n"
        f"🎬 Fasl: *{season_num}*\n"
        f"📌 Mavjud qismlar: {existing_str}\n"
        f"➡️ Keyingi qism *{next_num}*-dan boshlanadi.\n\n"
        f"Endi shu fasl qismlari uchun video cover rasmni yuboring:",
        parse_mode="Markdown"
    )
    return WAIT_EPISODE_POSTER

async def epseason_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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
    context.user_data["ep_next_num"] = 1
    ep_display = _episode_label(total_ep, ep_label)
    await update.message.reply_text(
        f"✅ *{next_season_num}-fasl* yaratildi! ({ep_display} ta qism e'lon qilindi)\n\n"
        "🖼 Endi shu fasl qismlari uchun *video cover rasmni* yuboring:",
        parse_mode="Markdown"
    )
    return WAIT_EPISODE_POSTER

async def got_episode_upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    next_num = context.user_data.get("ep_next_num", 1)
    await query.edit_message_text(
        f"🎬 Videolarni ketma-ket (yoki birdaniga) yuboring.\n\n"
        f"Men ularni avtomatik *{next_num}, {next_num + 1}, {next_num + 2}...* deb ketma-ket belgilab, saqlab boraman.\n\n"
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
    ep_num = d.get("ep_next_num", 1)
    season_id = d.get("ep_season_id")
    season_num = d.get("ep_season_num", 1)
    add_episode(season_id, ep_num, file_id)
    d["ep_added_count"] = d.get("ep_added_count", 0) + 1
    d["ep_next_num"] = ep_num + 1
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
        [InlineKeyboardButton("🌟 Tavsiya (0/1)", callback_data="editfield_featured"),
         InlineKeyboardButton("🔥 Mashhur (0/1)", callback_data="editfield_popular")],
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
    await update.message.reply_text(
        f"✅ Topildi!\n\n"
        f"📌 Kod: *{anime[1]}*\n"
        f"🎬 Nom: {_esc_md(anime[2])}\n"
        f"🔤 Original: {_esc_md(str(original))}\n"
        f"📅 Yil: {anime[3]}\n"
        f"🎭 Janr: {anime[4]}\n"
        f"📺 Qismlar: {anime[5]} ta\n"
        f"⭐ Reyting: {rating}\n"
        f"📝 Tavsif: {_esc_md(anime[6])}\n\n"
        f"Qaysi maydonni tahrirlaysiz?",
        parse_mode="Markdown",
        reply_markup=_edit_fields_kb()
    )
    return WAIT_EDIT_FIELD

async def got_edit_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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

# -- STATS --
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    animes_this_month, users, total_animes, total_episodes = get_monthly_stats()
    month = datetime.now().strftime("%B %Y")
    await update.message.reply_text(
        f"📊 *Statistika — {month}*\n\n"
        f"👥 Jami foydalanuvchilar: {users}\n"
        f"🎬 Jami animeler: {total_animes}\n"
        f"📺 Jami qismlar: {total_episodes}\n"
        f"➕ Bu oy qo'shilgan: {animes_this_month} ta anime",
        parse_mode="Markdown"
    )

# -- BROADCAST --
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    users = get_all_users()
    await update.message.reply_text(
        f"📣 *Xabar yuborish*\n\n"
        f"👥 Foydalanuvchilar soni: *{len(users)} ta*\n\n"
        f"Yuboriladigan xabarni yozing yoki rasm+izoh yuboring:\n"
        f"_(Matn, rasm, yoki rasm+sarlavha qabul qilinadi)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        "👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_broadcast")]])
    )
    return WAIT_BROADCAST_MSG

async def cancel_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END

async def got_broadcast_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = get_all_users()
    sent = 0
    failed = 0

    for uid in users:
        try:
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=uid,
                    photo=update.message.photo[-1].file_id,
                    caption=update.message.caption or "",
                )
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=update.message.text,
                )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegramning tezlik chegarasidan (rate limit) saqlanish uchun

    await update.message.reply_text(
        f"✅ *Xabar yuborildi!*\n\n"
        f"📤 Muvaffaqiyatli: *{sent}* ta\n"
        f"❌ Xato: *{failed}* ta",
        parse_mode="Markdown",
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
    return text, buttons

async def manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    channels = get_required_channels()
    text, buttons = _format_channels_list(channels)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def manage_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
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

async def got_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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

    if not (is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_forward")):
        return
    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is None:
        origin = getattr(msg, "forward_origin", None)
        fwd_chat = getattr(origin, "chat", None) if origin else None
    if fwd_chat is None or fwd_chat.type != "channel":
        await msg.reply_text("❌ Bu — kanaldan uzatilgan (forward) post emas. Iltimos, o'sha yopiq kanaldan bitta postni forward qiling.")
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
    if not (is_admin(update.effective_user.id) and context.user_data.get("awaiting_channel_title")):
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
    if not is_admin(query.from_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(update.effective_user.id):
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
    if not is_admin(query.from_user.id):
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
    if not is_admin(query.from_user.id):
        return
    context.user_data["awaiting_channel_send_code"] = True
    await query.message.reply_text("🔢 Kanalga yubormoqchi bo'lgan animening kodini yuboring:")

async def got_channel_send_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
        ok = await post_anime_to_channel(context, code, name, genre, total_ep, poster_id, poster_type=poster_type, ep_label=ep_label)
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
    ok = await post_anime_to_channel(context, code, name, genre, total_ep, poster_id, poster_type=poster_type, ep_label=ep_label)
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
    if not is_admin(query.from_user.id):
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
    await query.answer()
    await query.edit_message_text("❌ Bekor qilindi.")

async def channel_send_all_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
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
    sent_seasons = 0
    failed = 0
    try:
        for idx, (code, name, year, genre, _total_ep) in enumerate(animes, start=1):
            seasons = get_seasons(code)
            for sid, snum, poster_id, s_total_ep, poster_type, ep_label in seasons:
                ok = await post_anime_to_channel(
                    context, code, name, genre, s_total_ep, poster_id,
                    poster_type=poster_type, ep_label=ep_label
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

    for old_file_id, new_file_id in replacements.items():
        conn.execute("UPDATE animes SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
        conn.execute("UPDATE animes SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
        conn.execute("UPDATE seasons SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
        conn.execute("UPDATE episodes SET video_file_id=? WHERE video_file_id=?", (new_file_id, old_file_id))
    conn.commit()
    return len(replacements), failed


def _safe_extract_zip(archive_path, target_dir):
    with zipfile.ZipFile(archive_path) as archive:
        target_root = os.path.realpath(target_dir) + os.sep
        for member in archive.infolist():
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
    for old_file_id, item in manifest["files"].items():
        media_path = os.path.join(restore_dir, item["path"])
        if not os.path.isfile(media_path):
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
        conn = get_db()
        for old_file_id, new_file_id in replacements.items():
            conn.execute("UPDATE animes SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE animes SET episode_thumb_file_id=? WHERE episode_thumb_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE seasons SET poster_file_id=? WHERE poster_file_id=?", (new_file_id, old_file_id))
            conn.execute("UPDATE episodes SET video_file_id=? WHERE video_file_id=?", (new_file_id, old_file_id))
        conn.commit()

    return len(replacements), failed


async def backup_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    filename = f"anime_backup_{timestamp}.db"
    tmp_path = f"/tmp/{filename}"
    try:
        _media_count, media_ref_count = await _create_media_database(
            context.bot, os.path.abspath("anime.db"), tmp_path
        )
        with open(tmp_path, "rb") as f:
            await update.message.reply_document(
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
        await update.message.reply_text(f"❌ Zaxira olishda xatolik: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

async def restore_db_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "♻️ Tiklamoqchi bo'lgan *.db* faylini yuboring.\n\n"
        "⚠️ *Diqqat:* bu joriy ma'lumotlar bazasini butunlay almashtiradi — "
        "hozirgi barcha ma'lumotlar yuborilgan fayl bilan almashtiriladi!",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_restore_file"] = True

async def got_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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
    if not is_admin(query.from_user.id):
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
            required_tables = {"animes", "episodes", "users"}
            missing = required_tables - tables
            if missing:
                raise RuntimeError(
                    f"Kerakli jadvallar topilmadi: {', '.join(sorted(missing))}"
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
    buttons, admins = _admins_kb()
    text = "👥 *Adminlar ro'yxati:*\n\n"
    if admins:
        for uid, date in admins:
            text += f"• `{uid}` — {date}\n"
    else:
        text += "Hali qo'shimcha admin yo'q.\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

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
                "awaiting_channel_custom_days", "awaiting_admin_id", "pending_channel", "pending_channel_link"):
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
        "📺 Animelar Kanali":   channel_info,
        "📤 Kanalga Yuborish":  channel_send_list,
        "👥 Adminlar":          admins_panel,
        "🆕 Yangi Qismlar":     admin_recent_episodes_panel,
        "💾 Backup Olish":      backup_db_command,
        "♻️ Backup Tiklash":    restore_db_start,
        "🏷 Anime Holati":      anime_status_list_start,
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
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

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
            ],
            WAIT_EPM_ACTION: [
                CallbackQueryHandler(epm_select_callback, pattern="^epm_sel_"),
                CallbackQueryHandler(epm_delete_ask_callback, pattern="^epm_del_"),
                CallbackQueryHandler(epm_delete_confirm_callback, pattern="^epm_delyes_"),
                CallbackQueryHandler(epm_rename_ask_callback, pattern="^epm_ren_"),
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
            WAIT_EDIT_FIELD: [CallbackQueryHandler(got_edit_field_callback, pattern="^(editfield_|editseason_|editstatus|cancel_anime)")],
            WAIT_EDIT_VALUE: [
                CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_value),
            ],
        },
        fallbacks=_esc + [CallbackQueryHandler(cancel_anime_callback, pattern="^cancel_anime$")],
        per_message=False,
    )

    # Broadcast conversation
    broadcast_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📣 Xabar Yuborish$"), broadcast_start)],
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
    app.add_handler(add_anime_conv)
    app.add_handler(add_episode_conv)
    app.add_handler(epm_conv)
    app.add_handler(delete_anime_conv)
    app.add_handler(edit_anime_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(search_result_callback, pattern="^srch_"))
    app.add_handler(CallbackQueryHandler(inline_menu_callback, pattern="^(anime_search|kabinet|shorts|reklama)$"))
    app.add_handler(CallbackQueryHandler(manage_channels_callback, pattern="^(add_channel|rmchan_.+)$"))
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
    # Restore callbacks must be registered before the catch-all episode handler.
    # Otherwise "restore_confirm"/"restore_cancel" are swallowed silently.
    app.add_handler(CallbackQueryHandler(restore_confirm_callback, pattern="^restore_(confirm|cancel)$"))
    app.add_handler(CallbackQueryHandler(episode_callback))

    app.add_handler(MessageHandler(filters.FORWARDED, got_channel_forward), group=-1)
    app.add_handler(ChatJoinRequestHandler(record_join_request))

    app.add_handler(MessageHandler(filters.Regex("^🔍 Anime Izlash$"), anime_search))
    app.add_handler(MessageHandler(filters.Regex("^⏭ Shorts"), shorts_info))
    app.add_handler(MessageHandler(filters.Regex("^📢 Reklama$"), reklama_info))
    app.add_handler(MessageHandler(filters.Regex("^📺 Animelar Kanali$"), channel_info))
    app.add_handler(MessageHandler(filters.Regex("^📊 Statistika$"), show_stats))
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
