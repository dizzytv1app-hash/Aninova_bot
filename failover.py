"""
2-BOSQICH: Failover watchdog — asosiy botni boshqaradi.

Bu skript endi bot bilan bog'langan: u har doim fonda ishlab turadi va:
  - Qulfni olsa (FAOL bo'lsa) -> main.py'ni ishga tushiradi
  - Qulfni yo'qotsa (aslida sodir bo'lmasligi kerak, lekin xavfsizlik uchun)
    -> main.py'ni to'xtatadi
  - Har bir holat o'zgarishida ADMIN_ID'ga Telegram orqali xabar yuboradi

ISHLATISH (ikkala hostingda ham):
  Alwaysdata'dagi "Command" maydonini o'zgartiring:
    ESKI: venv/bin/python main.py
    YANGI: venv/bin/python failover.py hosting1      (Hosting2'da: hosting2)

  BOT_TOKEN environment variable orqali kelishi kerak (main.py bilan bir xil).
"""
import os
import sys
import time
import uuid
import signal
import subprocess
import urllib.request
import urllib.parse
import json

# ==================== SOZLAMALAR ====================
UPSTASH_URL = "https://powerful-buck-75920.upstash.io"
UPSTASH_TOKEN = "gQAAAAAAASiQAAIgcDJmMDQ0Yzc1NzAwMjE0ZjMyYWI1ZjA2MWNjYmE3NTdlMQ"

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip().strip("\"'")
ADMIN_ID = 6222096713  # main.py bilan bir xil bo'lishi kerak

LOCK_KEY = "active_node"
LOCK_TTL_SECONDS = 60
RENEW_INTERVAL = 20
CHECK_INTERVAL = 20

BOT_COMMAND = ["venv/bin/python", "main.py"]  # kerak bo'lsa moslashtiring

DB_PATH = "anime.db"
LITESTREAM_BIN = "./litestream"          # binary shu papkada bo'lishi kerak
LITESTREAM_CONFIG = "litestream.yml"


# ==================== UPSTASH QULF ====================
def _upstash_call(*parts):
    path = "/".join(urllib.parse.quote(str(p), safe="") for p in parts)
    url = f"{UPSTASH_URL}/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def try_acquire_or_renew(node_id):
    try:
        current = _upstash_call("GET", LOCK_KEY).get("result")
        if current == node_id:
            _upstash_call("PEXPIRE", LOCK_KEY, str(LOCK_TTL_SECONDS * 1000))
            return True
        if current is None:
            result = _upstash_call(
                "SET", LOCK_KEY, node_id, "NX", "PX", str(LOCK_TTL_SECONDS * 1000)
            ).get("result")
            return result == "OK"
        return False
    except Exception as e:
        print(f"[qulf xatosi] {e}")
        return False  # tarmoq xatosida standby holatida qolamiz — xavfsizroq


def release_lock(node_id):
    """Faol node tozalik bilan chiqayotganda qulfni darhol bo'shatadi
    (boshqasi 30s kutmasdan darhol faol bo'lishi uchun)."""
    try:
        current = _upstash_call("GET", LOCK_KEY).get("result")
        if current == node_id:
            _upstash_call("DEL", LOCK_KEY)
    except Exception as e:
        print(f"[qulfni bo'shatishda xato] {e}")


# ==================== TELEGRAM XABARI ====================
def notify_admin(text):
    if not BOT_TOKEN:
        print(f"[ADMIN XABARI yuborilmadi — BOT_TOKEN yo'q] {text}")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": ADMIN_ID, "text": text}).encode()
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[Admin xabar yuborishda xato] {e}")


# ==================== BOT JARAYONINI BOSHQARISH ====================
_bot_process = None
_litestream_process = None


def litestream_restore():
    """QOIDA #1: main.py ishga tushishidan OLDIN, eng so'nggi nusxani tortib oladi.
    -if-replica-exists tufayli — agar R2'da hali hech narsa bo'lmasa (birinchi
    marta ishga tushirilayotgan bo'lsa), xato bermaydi, jim o'tkazib yuboradi."""
    print("[litestream] eng so'nggi nusxa tortib olinmoqda...")
    result = subprocess.run(
        [LITESTREAM_BIN, "restore", "-if-replica-exists",
         "-config", LITESTREAM_CONFIG, DB_PATH],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[litestream restore xatosi] {result.stderr}")
    else:
        print("[litestream] baza tiklandi (yoki mavjud nusxa yo'q edi — yangi baza bilan davom etiladi).")


def start_litestream_replicate():
    """QOIDA #2: faqat FAOL node chaqiradi — bazani uzluksiz R2'ga oqizib turadi."""
    global _litestream_process
    if _litestream_process is not None and _litestream_process.poll() is None:
        return
    print("[litestream] replikatsiya boshlandi (bu node endi bazaga yozmoqda).")
    _litestream_process = subprocess.Popen(
        [LITESTREAM_BIN, "replicate", "-config", LITESTREAM_CONFIG]
    )


def stop_litestream_replicate():
    """QOIDA #2: standby holatga o'tganda — bazaga umuman tegmaslik uchun to'xtatiladi."""
    global _litestream_process
    if _litestream_process is None or _litestream_process.poll() is not None:
        return
    print("[litestream] replikatsiya to'xtatilmoqda (bu node endi bazaga tegmaydi).")
    _litestream_process.terminate()
    try:
        _litestream_process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _litestream_process.kill()
    _litestream_process = None


def start_bot():
    global _bot_process
    if _bot_process is not None and _bot_process.poll() is None:
        return  # allaqachon ishlab turibdi
    print("[bot ishga tushirilmoqda...]")
    _bot_process = subprocess.Popen(BOT_COMMAND)


def stop_bot():
    global _bot_process
    if _bot_process is None or _bot_process.poll() is not None:
        return  # allaqachon to'xtagan
    print("[bot to'xtatilmoqda...]")
    _bot_process.terminate()
    try:
        _bot_process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _bot_process.kill()
    _bot_process = None


# ==================== ASOSIY DOIRA ====================
def main():
    if len(sys.argv) < 2:
        print("Ishlatish: python3 failover.py <node_nomi>   (masalan: hosting1)")
        sys.exit(1)

    node_label = sys.argv[1]
    node_id = f"{node_label}-{uuid.uuid4().hex[:6]}"
    print(f"[{node_id}] failover watchdog ishga tushdi.")

    was_active = False

    def _graceful_shutdown(signum, frame):
        print(f"[{node_id}] to'xtatilmoqda...")
        stop_bot()
        stop_litestream_replicate()
        if was_active:
            release_lock(node_id)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _graceful_shutdown)
    signal.signal(signal.SIGINT, _graceful_shutdown)

    while True:
        is_active = try_acquire_or_renew(node_id)

        if is_active and not was_active:
            print(f"[{node_id}] ✅ FAOL bo'ldim.")
            # QOIDA #1: avval eng so'nggi nusxani tortib olamiz, FAQAT SHUNDAN
            # KEYIN botni ishga tushiramiz.
            litestream_restore()
            start_litestream_replicate()
            start_bot()
            notify_admin(f"✅ {node_label} endi FAOL. Bot shu yerda ishlamoqda.")

        elif not is_active and was_active:
            print(f"[{node_id}] ⚠️ Qulfni yo'qotdim.")
            # QOIDA #2: standby holatga o'tganda bazaga umuman tegmasligimiz kerak —
            # avval botni (yozuvchi tomonni), keyin replikatsiyani to'xtatamiz.
            stop_bot()
            stop_litestream_replicate()
            notify_admin(f"⚠️ {node_label} qulfni yo'qotdi. Bot to'xtatildi (split-brain oldini olish uchun).")

        elif is_active:
            # Bot jarayoni kutilmaganda o'lib qolgan bo'lsa, qayta ishga tushiramiz
            if _bot_process is not None and _bot_process.poll() is not None:
                print(f"[{node_id}] bot jarayoni kutilmaganda to'xtagan, qayta ishga tushiraman.")
                start_bot()

        was_active = is_active
        time.sleep(RENEW_INTERVAL if is_active else CHECK_INTERVAL)


if __name__ == "__main__":
    main()
