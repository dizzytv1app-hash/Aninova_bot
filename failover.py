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
BOT_PID_FILE = "bot.pid"  # watchdog qulab tushib qayta ishga tushsa, eski botni topish uchun
HEARTBEAT_FILE = "bot_heartbeat.txt"  # main.py yozadi, biz kuzatamiz
HEARTBEAT_STALE_SECONDS = 90  # main.py har 20s yozadi — 90s yangilanmasa, osilib qolgan deb hisoblaymiz


# ==================== UPSTASH QULF ====================
def _upstash_call(*parts):
    path = "/".join(urllib.parse.quote(str(p), safe="") for p in parts)
    url = f"{UPSTASH_URL}/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def try_acquire_or_renew(node_id):
    """True = faolman, False = boshqa node faol (aniq), None = noma'lum (Upstash
    bilan bog'lanishda xato) — None holatida chaqiruvchi joriy holatni o'zgartirmasligi kerak,
    aks holda Upstash vaqtincha ishlamay qolganda ikkala node ham bir vaqtda
    o'chib qolishi mumkin edi."""
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
        print(f"[qulf xatosi — Upstash bilan bog'lanib bo'lmadi, joriy holat saqlanadi] {e}")
        return None


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
def notify_admin(text, max_attempts=3, retry_delay=3):
    if not BOT_TOKEN:
        print(f"[ADMIN XABARI yuborilmadi — BOT_TOKEN yo'q] {text}")
        return
    for attempt in range(1, max_attempts + 1):
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({"chat_id": ADMIN_ID, "text": text}).encode()
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
            return
        except Exception as e:
            print(f"[Admin xabar yuborishda xato, urinish {attempt}/{max_attempts}] {e}")
            if attempt < max_attempts:
                time.sleep(retry_delay)
    print(f"[ADMIN XABARI YO'QOLDI — {max_attempts} urinish ham muvaffaqiyatsiz] {text}")


# ==================== BOT JARAYONINI BOSHQARISH ====================
_bot_process = None
_litestream_process = None


def litestream_restore(max_attempts=3, retry_delay=5):
    """QOIDA #1: main.py ishga tushishidan OLDIN, eng so'nggi nusxani tortib oladi.
    -if-replica-exists tufayli — agar R2'da hali hech narsa bo'lmasa (birinchi
    marta ishga tushirilayotgan bo'lsa), xato bermaydi, jim o'tkazib yuboradi.
    Vaqtinchalik tarmoq muammolarida bir necha marta qayta urinadi.
    Qaytaradi: True — muvaffaqiyatli (yoki nusxa yo'q edi), False — barcha urinishlar muvaffaqiyatsiz."""
    for attempt in range(1, max_attempts + 1):
        print(f"[litestream] eng so'nggi nusxa tortib olinmoqda... (urinish {attempt}/{max_attempts})")
        result = subprocess.run(
            [LITESTREAM_BIN, "restore", "-if-replica-exists",
             "-config", LITESTREAM_CONFIG, DB_PATH],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("[litestream] baza tiklandi (yoki mavjud nusxa yo'q edi — yangi baza bilan davom etiladi).")
            return True
        print(f"[litestream restore xatosi, urinish {attempt}/{max_attempts}] {result.stderr}")
        if attempt < max_attempts:
            time.sleep(retry_delay)
    return False


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


def is_litestream_replicating():
    return _litestream_process is not None and _litestream_process.poll() is None


_bot_started_at = None
BOT_STARTUP_GRACE_SECONDS = 90  # bot ishga tushgandan keyin shuncha vaqt hang-tekshiruvi o'tkazilmaydi


def is_bot_hung():
    """Bot jarayoni 'ishlab turibdi' deb ko'rinsa ham, aslida event loop qotib
    qolgan (hang) bo'lishi mumkin — buni faqat heartbeat fayli orqali bilamiz."""
    if _bot_started_at is not None and (time.time() - _bot_started_at) < BOT_STARTUP_GRACE_SECONDS:
        return False  # endigina ishga tushdi, hali birinchi heartbeat kelmagan bo'lishi mumkin
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    age = time.time() - os.path.getmtime(HEARTBEAT_FILE)
    return age > HEARTBEAT_STALE_SECONDS


def start_bot():
    global _bot_process, _bot_started_at
    if _bot_process is not None and _bot_process.poll() is None:
        return  # allaqachon ishlab turibdi
    print("[bot ishga tushirilmoqda...]")
    try:
        os.remove(HEARTBEAT_FILE)  # eski (oldingi jarayondan qolgan) belgi chalg'itmasin
    except FileNotFoundError:
        pass
    _bot_process = subprocess.Popen(BOT_COMMAND)
    _bot_started_at = time.time()
    with open(BOT_PID_FILE, "w") as f:
        f.write(str(_bot_process.pid))


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
    try:
        os.remove(BOT_PID_FILE)
    except FileNotFoundError:
        pass


def cleanup_orphaned_bot():
    """Watchdog kutilmaganda qulab tushib, qayta ishga tushganda chaqiriladi.
    Oldingi ishga tushirilgan (endi bu jarayon egasiz qolgan) main.py bo'lsa,
    uni o'chiradi — aks holda ikkita main.py bir vaqtda ishlab, Telegram
    'Conflict' xatosiga olib keladi."""
    if not os.path.exists(BOT_PID_FILE):
        return
    try:
        with open(BOT_PID_FILE) as f:
            old_pid = int(f.read().strip())
        os.kill(old_pid, signal.SIGTERM)
        print(f"[tozalash] avvalgi egasiz bot jarayoni (PID {old_pid}) topildi va to'xtatildi.")
        time.sleep(2)
        try:
            os.kill(old_pid, signal.SIGKILL)  # hali tirik bo'lsa, majburan
        except ProcessLookupError:
            pass
    except (ValueError, ProcessLookupError, FileNotFoundError):
        pass  # jarayon allaqachon yo'q — muammo emas
    finally:
        try:
            os.remove(BOT_PID_FILE)
        except FileNotFoundError:
            pass


# ==================== ASOSIY DOIRA ====================
def main():
    if len(sys.argv) < 2:
        print("Ishlatish: python3 failover.py <node_nomi>   (masalan: hosting1)")
        sys.exit(1)

    node_label = sys.argv[1]
    node_id = f"{node_label}-{uuid.uuid4().hex[:6]}"
    print(f"[{node_id}] failover watchdog ishga tushdi.")

    cleanup_orphaned_bot()  # oldingi qulab tushgan watchdog'dan qolgan egasiz bot bo'lsa, tozalaydi

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
        try:
            lock_state = try_acquire_or_renew(node_id)

            if lock_state is None:
                # Upstash bilan bog'lanib bo'lmadi — joriy holatni o'zgartirmaymiz,
                # shunchaki keyingi tsiklda qayta urinamiz.
                print(f"[{node_id}] Upstash bilan bog'lanib bo'lmadi, joriy holat ({'FAOL' if was_active else 'standby'}) saqlanmoqda.")
                time.sleep(RENEW_INTERVAL if was_active else CHECK_INTERVAL)
                continue

            is_active = lock_state

            if is_active and not was_active:
                print(f"[{node_id}] ✅ FAOL bo'ldim.")
                # QOIDA #1: avval eng so'nggi nusxani tortib olamiz, FAQAT SHUNDAN
                # KEYIN botni ishga tushiramiz.
                restore_ok = litestream_restore()
                if not restore_ok:
                    notify_admin(f"⚠️ {node_label}: baza tiklashda xato (3 marta urinildi, hammasi muvaffaqiyatsiz)! Eski/mavjud nusxa bilan davom etilyapti — tekshiring.")
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
                elif is_bot_hung():
                    # Process "ishlab turibdi" deb ko'rinadi, lekin heartbeat yangilanmagan —
                    # ya'ni event loop qotib qolgan (hang). Process o'zi tugamaganligi uchun
                    # majburan o'ldirib, qaytadan ishga tushiramiz.
                    print(f"[{node_id}] bot osilib qolgan (heartbeat {HEARTBEAT_STALE_SECONDS}s dan ortiq yangilanmagan), majburan qayta ishga tushiraman.")
                    stop_bot()
                    start_bot()
                    notify_admin(f"⚠️ {node_label}: bot osilib qolgan edi (javob bermayotgan holatda), majburan qayta ishga tushirildi.")
                # Litestream ham xuddi shunday kuzatiladi — jim o'lib qolmasligi kerak
                if not is_litestream_replicating():
                    print(f"[{node_id}] litestream replikatsiyasi to'xtagan, qayta ishga tushiraman.")
                    notify_admin(f"⚠️ {node_label}: litestream replikatsiyasi kutilmaganda to'xtagan edi, qayta ishga tushirildi. Baza vaqtincha zaxiralanmagan bo'lishi mumkin.")
                    start_litestream_replicate()

            was_active = is_active
            time.sleep(RENEW_INTERVAL if is_active else CHECK_INTERVAL)

        except Exception as e:
            # Kutilmagan xato — butun watchdog jarayonini yiqitmasin, faqat shu
            # tsiklni o'tkazib yuborib, davom etsin. Bot va litestream jarayonlariga
            # tegilmaydi (holat o'zgarmaydi), shuning uchun ular ishlashda davom etadi.
            print(f"[{node_id}] KUTILMAGAN XATO (davom etilmoqda): {e}")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
