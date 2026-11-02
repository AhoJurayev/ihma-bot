# -*- coding: utf-8 -*-
"""
Shayxali MFY Telegram Mini App (TMA) — Backend Server va REST API
Flask asosidagi yengil, xavfsiz va to'liq integratsiyalashgan veb-server.

Xavfsizlik va funksional takomillashtirishlar:
1. Telegram WebApp initData HMAC-SHA256 avtorizatsiyasi va auth_date tekshiruvi.
2. Markazlashgan autentifikatsiya va avtorizatsiya dekoratorlari (@require_tma_auth, @require_admin).
3. Resurs egaligi tekshiruvi (Citizen A hech qachon Citizen B ma'lumotlarini ko'ra olmaydi).
4. Elektron navbat slotlari to'qnashuvi va poyga holatlarining oldini olish.
5. Xavfsiz HTTP sarlavhalari (CSP, X-Content-Type-Options, nosniff), qat'iy CORS va so'rovlar hajmi cheklovi.
6. Server-side Rate Limiting (DoS va AI resurslarini suiiste'mol qilishdan himoya).
"""

import io
import os
import re
import html
import time
import logging
import threading
from functools import wraps
from datetime import datetime
from urllib.parse import quote
from flask import Flask, Response, request, jsonify, send_from_directory, send_file
import qrcode
from qrcode.image.svg import SvgPathImage
from telebot import types
from waitress import serve

import database
import local_legal_advisor
from utils.text_normalizer import latin_to_cyrillic_uz, ensure_cyrillic
from utils.tma_auth import verify_telegram_init_data, parse_init_data

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WebAppServer")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.join(BASE_DIR, "webapp")

app = Flask(__name__, static_folder=WEBAPP_DIR, static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # 1 MB limit: API faqat matn qabul qiladi

# main.py tomonidan o'rnatiladigan bog'lanishlar
_bot_instance = None
_ai_backend = None
_lang_change_listener = None
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()

# Rate limiting xotirasi (IP / User ID bo'yicha)
_rate_limits = {}
_rate_lock = threading.Lock()
_RATE_LIMITS_MAX_KEYS = 10000
_RATE_LIMIT_MAX_WINDOW = 3600

ALLOWED_PRIORITIES = {"ODDIY", "ORTA", "SHOSHILINCH"}
MAX_CATEGORY_LENGTH = 100
RATEABLE_STATUSES = {"Hal etildi", "Rad etildi", "Yopildi", "Boshqa tashkilotga yuborildi"} | set(database.AUTO_ANSWER_STATUSES)

_PASSPORT_CYR_TO_LAT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Д": "D", "Е": "E", "Ф": "F", "Г": "G", "Ҳ": "H", "И": "I",
    "Ж": "J", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Қ": "Q", "Р": "R",
    "Т": "T", "У": "U", "Х": "X", "Й": "Y", "З": "Z",
})


def set_bot_instance(bot):
    """main.py dagi bot obyektini serverga ulash."""
    global _bot_instance
    _bot_instance = bot


def set_ai_backend(backend):
    """Mini App suhbati uchun javob funksiyasini ulash: backend(question, user_id, lang) -> dict."""
    global _ai_backend
    _ai_backend = backend


def set_lang_change_listener(listener):
    """Til o'zgarganda botning xotirasini yangilash: listener(user_id: int, lang: str)."""
    global _lang_change_listener
    _lang_change_listener = listener


def _json_body() -> dict:
    """So'rov tanasini lug'at sifatida qaytaradi; JSON noto'g'ri bo'lsa bo'sh lug'at."""
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def _client_ip() -> str:
    """Mijoz IP manzili. Sarlavhaga faqat mahalliy cloudflared ulanishida ishoniladi, aks holda uni soxtalashtirish mumkin."""
    remote = request.remote_addr or "unknown"
    if remote in ("127.0.0.1", "::1"):
        return request.headers.get("CF-Connecting-IP", remote).strip() or remote
    return remote


def _parse_identity_document(raw: str):
    """Pasport (AA1234567) yoki 14 xonali JSHSHIR ni ajratadi. Qaytadi: (pasport, jshshir) yoki noto'g'ri bo'lsa None."""
    cleaned = re.sub(r"[\s\-_]", "", str(raw or "")).upper().translate(_PASSPORT_CYR_TO_LAT)
    if not cleaned:
        return "", ""
    if re.fullmatch(r"[A-Z]{2}\d{7}", cleaned):
        return cleaned, ""
    if re.fullmatch(r"\d{14}", cleaned):
        return "", cleaned
    return None


def get_bot_token() -> str:
    """Bot tokenini olish."""
    global TELEGRAM_BOT_TOKEN
    if not TELEGRAM_BOT_TOKEN:
        TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    return TELEGRAM_BOT_TOKEN


def to_new_uzbek_latin(text: str) -> str:
    """Барча лотинча матнларни расмий Кирилл алифбосига ўгиради."""
    return ensure_cyrillic(text)


def send_admin_alert(text, reply_markup=None):
    """Adminga bot orqali xabar yuborish yordamchisi."""
    if _bot_instance and ADMIN_ID:
        try:
            _bot_instance.send_message(
                int(ADMIN_ID),
                text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.warning(f"Adminga xabar yuborishda ogohlantirish: {e}")


# ==============================================================================
# XAVFSIZLIK: RATE LIMITING & SECURITY HEADERS & CORS
# ==============================================================================
def check_rate_limit(key: str, max_requests: int = 60, window_seconds: int = 60) -> bool:
    """Sliding window rate limiter."""
    now = time.time()
    with _rate_lock:
        timestamps = _rate_limits.get(key, [])
        # Eski vaqtlarni tozalash
        timestamps = [ts for ts in timestamps if now - ts < window_seconds]
        if len(timestamps) >= max_requests:
            _rate_limits[key] = timestamps
            return False
        timestamps.append(now)
        _rate_limits[key] = timestamps
        if len(_rate_limits) > _RATE_LIMITS_MAX_KEYS:
            stale = [k for k, v in _rate_limits.items() if not v or now - v[-1] >= _RATE_LIMIT_MAX_WINDOW]
            for k in stale:
                del _rate_limits[k]
        return True


@app.before_request
def apply_rate_limiting():
    """Barcha /api/ so'rovlariga tezlik cheklovini qo'llash."""
    if request.path.startswith("/api/"):
        if not check_rate_limit(f"ip:{_client_ip()}", max_requests=100, window_seconds=60):
            return jsonify({"status": "error", "message": "Juda ko'p so'rovlar yuborildi. Iltimos, bir oz kuting."}), 429


@app.after_request
def add_security_headers(response):
    """Qat'iy xavfsizlik va keshga qarshi sarlavhalar."""
    # Mini App o'z domenidan ochiladi va avtorizatsiya sarlavha orqali o'tadi (cookie emas),
    # shuning uchun boshqa domenlardan faqat Telegram va WEB_APP_URL ga ruxsat beriladi.
    origin = request.headers.get("Origin", "")
    if origin == "null":
        # Telegram Webview ichidagi mahalliy sahifalar uchun
        response.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and (
        re.fullmatch(r"https://([a-z0-9-]+\.)*telegram\.org", origin)
        or (WEB_APP_URL and origin == WEB_APP_URL.rstrip("/"))
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"

    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization,X-Telegram-Init-Data"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
        "default-src 'self' 'unsafe-inline' https://telegram.org https://*.telegram.org data: blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:;"
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ==============================================================================
# XAVFSIZLIK: TELEGRAM WEBAPP INITDATA AUTENTIFIKATSIYA VA AVTORIZATSIYA
# ==============================================================================
def extract_and_verify_auth() -> tuple:
    """
    So'rovdan Telegram initData ma'lumotini ajratib oladi va tekshiradi.
    Qaytadi: (is_authenticated, user_dict, error_message)
    """
    # 1. Headerlardan qidirish
    init_data_raw = request.headers.get("X-Telegram-Init-Data") or request.headers.get("Authorization") or ""
    if init_data_raw.lower().startswith("bearer "):
        init_data_raw = init_data_raw[7:].strip()
    elif init_data_raw.lower().startswith("tma "):
        init_data_raw = init_data_raw[4:].strip()

    # Pytest / Test rejimi uchun bypass: faqat kod ichidan yoqiladi, muhit o'zgaruvchisi bilan yoqilmaydi
    if app.config.get("TESTING"):
        test_uid = request.headers.get("X-Test-User-Id")
        if test_uid:
            return True, {
                "id": int(test_uid),
                "first_name": "Test Citizen",
                "username": "test_user",
                "is_admin": str(test_uid) == str(ADMIN_ID)
            }, "Test Auth OK"

    token = get_bot_token()
    if not token:
        # Bot tokeni hali yuklanmagan bo'lsa
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not init_data_raw:
        return False, None, "Telegram Mini App autentifikatsiyasi (initData) talab qilinadi"

    ok, user_data, msg = verify_telegram_init_data(init_data_raw, token)
    if not ok:
        return False, None, msg

    user_data["is_admin"] = str(user_data.get("id")) == str(ADMIN_ID)
    return True, user_data, "Muvaffaqiyatli"


def require_tma_auth(f):
    """Mini App API endpointlari uchun Telegram initData majburiy tekshiruvi dekoratori."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "OPTIONS":
            return jsonify({"status": "ok"}), 200

        is_auth, user_data, err = extract_and_verify_auth()
        if not is_auth:
            database.log_audit_event("ANONYMOUS", "UNAUTHORIZED_API_ACCESS", request.path, err, "FAILED")
            return jsonify({"status": "error", "auth_error": True, "message": f"Avtorizatsiyadan o'tilmagan: {err}"}), 401

        request.tma_user = user_data
        request.authenticated_user_id = str(user_data["id"])
        return f(*args, **kwargs)
    return decorated_function


def require_admin(f):
    """Faqat administrator uchun mo'ljallangan endpointlar dekoratori."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "OPTIONS":
            return jsonify({"status": "ok"}), 200

        is_auth, user_data, err = extract_and_verify_auth()
        if not is_auth:
            return jsonify({"status": "error", "message": f"Avtorizatsiyadan o'tilmagan: {err}"}), 401

        if not user_data.get("is_admin") and str(user_data.get("id")) != str(ADMIN_ID):
            database.log_audit_event(str(user_data.get("id")), "UNAUTHORIZED_ADMIN_ACCESS", request.path, "Faqat admin uchun", "FAILED")
            return jsonify({"status": "error", "message": "Ushbu amal faqat administrator uchun ruxsat etilgan"}), 403

        request.tma_user = user_data
        request.authenticated_user_id = str(user_data["id"])
        return f(*args, **kwargs)
    return decorated_function


# ==============================================================================
# 1. STATIK SAHIFA VA ASSETLAR
# ==============================================================================
@app.route("/")
def index():
    return send_from_directory(WEBAPP_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    # Directory traversal himoyasi
    safe_path = os.path.normpath(path)
    if ".." in safe_path or safe_path.startswith("/") or safe_path.startswith("\\"):
        return jsonify({"status": "error", "message": "Noto'g'ri fayl yo'li"}), 400
    return send_from_directory(WEBAPP_DIR, safe_path)


# ==============================================================================
# 2. FUQARO PROFILI VA STATUS API (RESURS EGALIGI HIMOYA QILINGAN)
# ==============================================================================
@app.route("/api/citizen", methods=["GET"])
@require_tma_auth
def get_citizen():
    """
    Fuqaro profili:
    Faqat autentifikatsiyadan o'tgan fuqaroning o'z ma'lumotlari qaytariladi!
    Citizen A hech qachon Citizen B ning profilini yoki arizalarini o'qiy olmaydi.
    """
    user_id = request.authenticated_user_id
    # Agar admin bo'lsa va maxsus query parameter orqali boshqa fuqaroni ko'rmoqchi bo'lsa
    if request.tma_user.get("is_admin"):
        target_param = request.args.get("telegram_id")
        if target_param:
            user_id = str(target_param).strip()

    citizen = database.get_citizen_by_tg_id(user_id)
    appeals_raw = database.get_citizen_appeals(user_id, limit=20)
    ticket_raw = database.get_citizen_active_navbat(user_id)

    appeals = []
    for a in appeals_raw:
        appeals.append({
            "id": a.get("Murojaat_ID"),
            "category": a.get("Turi", "Umumiy"),
            "text": a.get("Savol", ""),
            "status": a.get("Status", "Yangi"),
            "priority": a.get("Muhimlik", "ODDIY"),
            "created_at": a.get("Sana", ""),
            "rating": a.get("Baho"),
            "admin_response": a.get("Admin_Izohi", ""),
            "ai_response": a.get("AI_Javobi", "")
        })

    active_ticket = None
    if ticket_raw:
        active_ticket = {
            "ticket_number": ticket_raw.get("Navbat_ID"),
            "date": ticket_raw.get("Qabul_Kuni"),
            "time_slot": ticket_raw.get("Qabul_Soati"),
            "fio": ticket_raw.get("FIO"),
            "token": ticket_raw.get("token", "")
        }

    status_str = citizen.get("Status", "Boshlang'ich") if citizen else "Boshlang'ich"
    is_verified = bool(citizen and citizen.get("Status") == "Tasdiqlangan")
    user_lang = database.get_user_lang(user_id)

    try:
        mih_val = int(database.get_setting("mih_amount", "669000"))
    except Exception:
        mih_val = 669000
    queue_open = database.get_setting("queue_open", "1") == "1"
    queue_closed_reason = database.get_setting("queue_closed_reason", "")

    return jsonify({
        "status": "ok",
        "citizen": {
            "telegram_id": user_id,
            "fio": citizen.get("FIO") if citizen else (request.tma_user.get("first_name", "")),
            "phone": citizen.get("Telefon") if citizen else "",
            "address": citizen.get("Kocha_Manzil") if citizen else "Қарши шаҳар, Шайх-Али МФЙ",
            "status": status_str,
            "is_verified": is_verified,
            "lang": user_lang,
            "is_admin": request.tma_user.get("is_admin", False)
        },
        "settings": {
            "mih_amount": mih_val,
            "queue_open": queue_open,
            "queue_closed_reason": queue_closed_reason,
            "queue_days": database.get_setting("queue_days", "Dushanba - Juma"),
            "queue_hours": database.get_setting("queue_hours", "09:00 - 12:00, 14:00 - 17:00")
        },
        "appeals": appeals,
        "active_ticket": active_ticket
    })


@app.route("/api/settings", methods=["GET"])
def get_system_settings_api():
    """Tizim sozlamalari (MIH va elektron navbat) ommaviy o'qish API si."""
    try:
        mih_val = int(database.get_setting("mih_amount", "669000"))
    except Exception:
        mih_val = 669000
    queue_open = database.get_setting("queue_open", "1") == "1"
    queue_closed_reason = database.get_setting("queue_closed_reason", "")

    return jsonify({
        "status": "ok",
        "mih_amount": mih_val,
        "queue_open": queue_open,
        "queue_closed_reason": queue_closed_reason,
        "queue_days": database.get_setting("queue_days", "Dushanba - Juma"),
        "queue_hours": database.get_setting("queue_hours", "09:00 - 12:00, 14:00 - 17:00")
    })


@app.route("/api/set_lang", methods=["POST"])
@require_tma_auth
def set_lang_api():
    """Foydalanuvchi tilini saqlash (faqat autentifikatsiyalangan fuqaroning o'zi uchun)."""
    data = _json_body()
    lang = str(data.get("lang", "")).strip()
    telegram_id = request.authenticated_user_id

    if not lang or lang not in ["uz_cyr", "uz_lat", "ru"]:
        return jsonify({"status": "error", "message": "Noto'g'ri til tanlandi"}), 400

    database.set_user_lang(telegram_id, lang)
    if _lang_change_listener:
        _lang_change_listener(int(telegram_id), lang)

    return jsonify({"status": "ok", "lang": lang})


# ==============================================================================
# 3. SHAXSNI TEZKOR TASDIQLASH (O'RQ-547 NO MEDIA)
# ==============================================================================
@app.route("/api/verify", methods=["POST"])
@require_tma_auth
def verify_citizen():
    """Shaxsni tasdiqlash so'rovi (ID autentifikatsiyalangan sessiyadan olinadi)."""
    data = _json_body()
    telegram_id = request.authenticated_user_id
    fio = str(data.get("fio", "")).strip()
    phone = str(data.get("phone", "")).strip()
    doc = str(data.get("passport_or_jshshir", "")).strip()
    address = str(data.get("address", "")).strip()

    if not fio or not phone:
        return jsonify({"status": "error", "message": "F.I.Sh. va telefon to'liq kiritilishi kerak"}), 400

    if not 3 <= len(fio) <= 120 or len(address) > 200:
        return jsonify({"status": "error", "message": "Ф.И.Ш. ёки манзил узунлиги нотўғри"}), 400

    if not re.fullmatch(r"\+?[\d\s()\-]{9,20}", phone) or not 9 <= len(re.sub(r"\D", "", phone)) <= 15:
        return jsonify({"status": "error", "message": "Телефон рақами нотўғри киритилган"}), 400

    parsed_doc = _parse_identity_document(doc)
    if parsed_doc is None:
        return jsonify({"status": "error", "message": "Паспорт (AA1234567) ёки 14 хонали ЖШШИР нотўғри киритилган"}), 400
    pasport, jshshir = parsed_doc

    # Tasdiqlangan fuqaro o'z maqomini "Kutmoqda" ga qaytarib qo'ymasligi kerak
    current = database.get_citizen_by_tg_id(telegram_id)
    if current and current.get("Status") == "Tasdiqlangan":
        return jsonify({"status": "ok", "already_verified": True, "message": "Шахсингиз аввал тасдиқланган."})

    if not check_rate_limit(f"verify:{telegram_id}", max_requests=5, window_seconds=3600):
        return jsonify({"status": "error", "message": "Жуда кўп уриниш. Илтимос, кейинроқ қайта уриниб кўринг."}), 429

    is_duplicate, _ = database.find_duplicate_citizen(telegram_id, telefon=phone, pasport=pasport, jshshir=jshshir)
    if is_duplicate:
        database.log_audit_event(telegram_id, "CITIZEN_DUPLICATE_ATTEMPT", telegram_id, "Mini App", "FAILED")
        return jsonify({
            "status": "error",
            "message": "Ушбу телефон ёки ҳужжат бошқа фойдаланувчида рўйхатдан ўтган. Ижтимоий ходимга мурожаат қилинг."
        }), 409

    success = database.save_or_update_citizen(
        user_id=telegram_id,
        fio=fio,
        telefon=phone,
        pasport_seriya=pasport,
        jshshir=jshshir,
        kocha_manzil=address,
        status="Kutmoqda",
        til=database.get_user_lang(telegram_id)
    )

    if success:
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Тасдиқлаш", callback_data=f"adm_appr_cit_{telegram_id}"),
            types.InlineKeyboardButton("❌ Рад этиш", callback_data=f"adm_rejc_cit_{telegram_id}")
        )
        safe_fio = html.escape(fio)
        safe_phone = html.escape(phone)
        safe_doc = html.escape(doc or 'Киритилмади')
        safe_address = html.escape(address or 'Шайх-Али МФЙ')

        alert_text = (
            f"📋 <b>Mini App орқали идентификация сўрови тушди:</b>\n\n"
            f"👤 <b>Ф.И.Ш:</b> {safe_fio}\n"
            f"📞 <b>Телефон:</b> {safe_phone}\n"
            f"📄 <b>Ҳужжат:</b> {safe_doc}\n"
            f"📍 <b>Манзил:</b> {safe_address}\n"
            f"🆔 <b>TG ID:</b> <code>{telegram_id}</code>\n"
            f"⏳ <i>Статус: Тасдиқлаш кутилмоқда (Админ текшируви)</i>\n\n"
            f"<i>Маълумотларни текширинг ва қарор қабул қилинг:</i>"
        )
        send_admin_alert(alert_text, reply_markup=markup)
        return jsonify({"status": "ok", "message": "Маълумотлар админга юборилди. Тасдиқланиши кутилмоқда."})

    return jsonify({"status": "error", "message": "Базага сақлашда хатолик"}), 500


# ==============================================================================
# 4. RASMIY MUROJAAT YUBORISH API (HIMOYA QILINGAN)
# ==============================================================================
@app.route("/api/appeal", methods=["POST"])
@require_tma_auth
def submit_appeal():
    """Rasmiy murojaat yuborish (Egalik qat'iy tekshiriladi)."""
    data = _json_body()
    telegram_id = request.authenticated_user_id
    category = str(data.get("category", "Umumiy")).strip()[:MAX_CATEGORY_LENGTH] or "Umumiy"
    text = str(data.get("text", "")).strip()
    priority = str(data.get("priority", "ODDIY")).strip().upper()
    if priority not in ALLOWED_PRIORITIES:
        priority = "ODDIY"

    if not text:
        return jsonify({"status": "error", "message": "Мурожаат матни бўш бўлиши мумкин эмас"}), 400

    if len(text) > 4000:
        return jsonify({"status": "error", "message": "Мурожаат матни жуда узун (максимал 4000 белги)"}), 400

    if not check_rate_limit(f"appeal:{telegram_id}", max_requests=10, window_seconds=3600):
        return jsonify({"status": "error", "message": "Жуда кўп мурожаат юборилди. Илтимос, кейинроқ уриниб кўринг."}), 429

    # 1. Dastlabki tahlil (Mahalliy 0-token tekshiruvi)
    handled_locally, turi, muhimlik, ai_javob = local_legal_advisor.try_local_answer(text, telegram_id)
    if not handled_locally or not ai_javob:
        ai_javob = (
            "Мурожаат қабул қилинди. Ушбу масала бўйича Шайх-Али МФЙ ижтимоий ходими "
            "(А. Жўраев) томонидан тезкор ўрганиш ишлари олиб борилади."
        )

    # 2. Bazaga saqlash
    murojaat_id = database.save_murojaat(
        user_id=telegram_id,
        savol=text,
        ai_javobi=re.sub(r"<[^>]+>", "", ai_javob),
        turi=category,
        muhimlik=priority,
        status="Yangi",
    )

    # 3. Adminga xabarnoma chiqarish
    citizen = database.get_citizen_by_tg_id(telegram_id) or {}
    is_verified = bool(
        citizen
        and str(citizen.get("Status", "")).strip() == "Tasdiqlangan"
        and citizen.get("FIO")
        and str(citizen.get("FIO")).strip() not in ["Noma'lum", "Nomalum", "Hurmatli fuqaro", "Fuqaro", ""]
    )

    safe_text = html.escape(text)
    safe_fio = html.escape(citizen.get('FIO') or request.tma_user.get('first_name') or 'Фуқаро')
    safe_phone = html.escape(citizen.get('Telefon') or 'Кўрсатилмаган')
    safe_cat = html.escape(category)

    if not is_verified:
        alert_text = (
            f"📩 <b>Mini App орқали мурожаат (Идентификациядан ўтмаган фуқаро)</b>\n\n"
            f"🔢 <b>Рақами:</b> #{murojaat_id}\n"
            f"🆔 <b>TG ID:</b> <code>{telegram_id}</code>\n"
            f"⚠️ <b>Ҳолати:</b> Идентификациядан ўтмаган фуқаро мурожаати\n"
            f"📂 <b>Йўналиш:</b> {safe_cat}\n"
            f"🚨 <b>Муҳимлик:</b> {priority}\n\n"
            f"📝 <b>Матн:</b>\n<i>{safe_text}</i>"
        )
    else:
        alert_text = (
            f"📩 <b>Mini App орқали янги расмий мурожаат!</b>\n\n"
            f"🔢 <b>Рақами:</b> #{murojaat_id}\n"
            f"👤 <b>Фуқаро:</b> {safe_fio} (✅ Тасдиқланган)\n"
            f"📞 <b>Телефон:</b> {safe_phone}\n"
            f"📂 <b>Йўналиш:</b> {safe_cat}\n"
            f"🚨 <b>Муҳимлик:</b> {priority}\n\n"
            f"📝 <b>Матн:</b>\n<i>{safe_text}</i>"
        )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✍️ Fuqaroga javob yozish", callback_data=f"mstat_reply_{murojaat_id}"),
        types.InlineKeyboardButton("🏢 Tashkilotga yo'naltirildi", callback_data=f"mstat_org_{murojaat_id}"),
    )
    markup.add(
        types.InlineKeyboardButton("✅ Qanoatlantirildi", callback_data=f"mstat_ok_{murojaat_id}"),
        types.InlineKeyboardButton("❌ Rad etildi", callback_data=f"mstat_rad_{murojaat_id}"),
    )
    markup.add(
        types.InlineKeyboardButton("📄 Dalolatnoma (.docx)", callback_data=f"mstat_doc_{murojaat_id}"),
    )
    send_admin_alert(alert_text, reply_markup=markup)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    return jsonify({
        "status": "ok",
        "appeal": {
            "id": murojaat_id,
            "category": category,
            "text": text,
            "status": "Yangi",
            "priority": priority,
            "created_at": created_at,
            "rating": None
        }
    })


# ==============================================================================
# 5. ELEKTRON NAVBAT (BOOKING, BEKOR QILISH VA SLOT BO'SHATISH)
# ==============================================================================
@app.route("/api/queue/slots", methods=["GET"])
@require_tma_auth
def get_queue_slots():
    """Berilgan sanadagi band vaqtlar (fuqaro ma'lumotisiz)."""
    date_str = str(request.args.get("date", "")).strip()
    if not database.parse_appointment_date(date_str):
        return jsonify({"status": "error", "message": "Сана нотўғри кўрсатилган"}), 400
    return jsonify({"status": "ok", "slots": database.QUEUE_SLOTS, "booked": database.get_booked_slots(date_str)})


@app.route("/api/queue", methods=["POST"])
@require_tma_auth
def submit_queue():
    """Elektron navbat band qilish (Poyga holati va takrorlanishdan to'liq himoyalangan)."""
    data = _json_body()
    telegram_id = request.authenticated_user_id
    date_str = str(data.get("date", "")).strip()
    time_slot = str(data.get("time_slot", "")).strip()

    if not date_str or not time_slot:
        return jsonify({"status": "error", "message": "Сана ва вақт киритилиши шарт"}), 400

    # Elektron navbat qabuli holatini tekshirish
    if database.get_setting("queue_open", "1") != "1":
        closed_reason = database.get_setting("queue_closed_reason", "").strip()
        msg = closed_reason or "Ижтимоий ходим маҳаллада хонадонма-хонадон ўрганишда бўлганлиги сабабли бугунги қабул вақтинча тўхтатилган."
        return jsonify({"status": "error", "message": f"🔴 {msg}"}), 400

    citizen = database.get_citizen_by_tg_id(telegram_id) or {}
    fio = citizen.get("FIO") or request.tma_user.get("first_name", "Фуқаро")
    phone = citizen.get("Telefon") or ""
    kocha = citizen.get("Kocha_Manzil", "Шайх-Али МФЙ")

    try:
        navbat_id = database.save_navbat(
            telegram_id=telegram_id,
            fio=fio,
            telefon=phone,
            kocha=kocha,
            qabul_kuni=date_str,
            qabul_soati=time_slot
        )
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        logger.error(f"Navbat saqlashda xatolik: {e}")
        return jsonify({"status": "error", "message": "Навбат сақлашда кутилмаган хатолик юз берди"}), 500

    # QR kod ma'lumotlari uchun unikal token olish
    ticket_data = database.get_citizen_active_navbat(telegram_id) or {}
    token = ticket_data.get("token", "")
    # Bazadagi tekshirilgan yagona format ko'rsatiladi
    date_str = ticket_data.get("Qabul_Kuni") or date_str
    time_slot = ticket_data.get("Qabul_Soati") or time_slot

    safe_fio = html.escape(fio)
    alert_text = (
        f"📅 <b>Mini App орқали янги қабул навбати банд қилинди!</b>\n\n"
        f"🎫 <b>Навбат талони:</b> #{navbat_id}\n"
        f"👤 <b>Фуқаро:</b> {safe_fio}\n"
        f"📞 <b>Телефон:</b> {html.escape(phone or 'Кўрсатилмаган')}\n"
        f"🗓 <b>Қабул санаси:</b> {date_str}\n"
        f"⏰ <b>Қабул вақти:</b> {time_slot}\n"
        f"📍 <b>Идора:</b> Шайх-Али МФЙ биноси"
    )
    send_admin_alert(alert_text)

    return jsonify({
        "status": "ok",
        "ticket": {
            "ticket_number": navbat_id,
            "date": date_str,
            "time_slot": time_slot,
            "fio": fio,
            "token": token
        }
    })


@app.route("/api/queue/cancel", methods=["POST"])
@require_tma_auth
def cancel_queue():
    """Fuqaro yoki admin tomonidan navbatni bekor qilish va slotni bo'shatish."""
    data = _json_body()
    ticket_number = str(data.get("ticket_number", "")).strip()
    reason = str(data.get("reason", "Fuqaro tomonidan bekor qilindi")).strip()[:300]
    user_id = request.authenticated_user_id
    is_admin = bool(request.tma_user.get("is_admin"))

    if not ticket_number:
        return jsonify({"status": "error", "message": "Навбат рақами (ticket_number) талаб қилинади"}), 400

    try:
        database.cancel_navbat(ticket_number, user_id=user_id, is_admin=is_admin, reason=reason)
        return jsonify({"status": "ok", "message": "Навбат муваффақиятли бекор қилинди ва вақт слоти бўшатилди."})
    except PermissionError as pe:
        return jsonify({"status": "error", "message": str(pe)}), 403
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 404
    except Exception as e:
        logger.error(f"Navbatni bekor qilishda xatolik: {e}")
        return jsonify({"status": "error", "message": "Тизим хатолиги"}), 500


@app.route("/api/queue/verify_qr", methods=["GET", "POST"])
def verify_queue_qr():
    """QR kod ichidagi unikal token orqali navbatni serverda tekshirish."""
    token = request.args.get("token") or (request.get_json(silent=True) or {}).get("token")
    if not token:
        return jsonify({"status": "error", "message": "Token kiritilmadi"}), 400

    result = database.verify_appointment_qr_token(str(token))
    # Telefon kamerasi QR ni brauzerda ochadi: xodim JSON emas, o'qiladigan sahifa ko'radi
    if request.method == "GET" and "text/html" in request.headers.get("Accept", ""):
        return _render_qr_verification_page(result)
    return jsonify({"status": "ok", "verification": result})


def _render_qr_verification_page(result: dict):
    """Talon tekshiruvi natijasi (fuqaroning shaxsiy ma'lumotisiz)."""
    if result.get("valid") and result.get("is_active"):
        title, color = "✅ Талон ҳақиқий ва фаол", "#16a34a"
    elif result.get("valid"):
        title, color = "⚠️ Талон фаол эмас", "#d97706"
    else:
        title, color = "❌ Талон топилмади", "#dc2626"
    rows = "".join(
        f"<p><b>{label}:</b> {html.escape(str(result.get(key) or ''))}</p>"
        for label, key in [("Рақами", "ticket_number"), ("Сана", "date"), ("Вақт", "time_slot"), ("Ҳолати", "status")]
        if result.get(key)
    )
    page = (
        '<!doctype html><html lang="uz"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Навбат талони</title></head>'
        '<body style="font-family: system-ui, sans-serif; padding: 24px; font-size: 18px;">'
        f'<h2 style="color: {color};">{title}</h2>{rows}</body></html>'
    )
    return Response(page, mimetype="text/html")


@app.route("/api/queue/qr", methods=["GET"])
@require_tma_auth
def get_queue_qr():
    """Fuqaroning faol taloni uchun QR kod (SVG). Ichida faqat taxmin qilib bo'lmaydigan token bor."""
    ticket = database.get_citizen_active_navbat(request.authenticated_user_id)
    if not ticket or not ticket.get("token"):
        return jsonify({"status": "error", "message": "Фаол навбат топилмади"}), 404

    # Tunnel manzili o'zgarib turadi, shuning uchun QR so'rov kelgan manzildan yasaladi
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    verify_url = f"{scheme}://{request.host}/api/queue/verify_qr?token={quote(ticket['token'])}"
    buffer = io.BytesIO()
    qrcode.make(verify_url, image_factory=SvgPathImage, border=2).save(buffer)
    return Response(buffer.getvalue(), mimetype="image/svg+xml")


# ==============================================================================
# 6. CSAT FUQARO QANOATLANISH BAHOSI (EGALIK HIMOYA QILINGAN)
# ==============================================================================
@app.route("/api/rate", methods=["POST"])
@require_tma_auth
def submit_rate():
    """CSAT baholash (Faqat o'z arizasini baholay oladi)."""
    data = _json_body()
    appeal_id = str(data.get("appeal_id", "")).strip()
    telegram_id = request.authenticated_user_id

    if not appeal_id:
        return jsonify({"status": "error", "message": "appeal_id talab qilinadi"}), 400

    try:
        score = int(data.get("score"))
    except (TypeError, ValueError):
        score = 0
    if not 1 <= score <= 5:
        return jsonify({"status": "error", "message": "Баҳо 1 дан 5 гача бўлиши керак"}), 400

    # Egalik huquqi tekshiruvi: ushbu murojaat haqiqatan shu fuqaronikimi?
    murojaat = database.get_murojaat_by_id(appeal_id)
    if not murojaat:
        return jsonify({"status": "error", "message": "Мурожаат топилмади"}), 404

    if not request.tma_user.get("is_admin") and str(murojaat.get("Telegram_ID")) != str(telegram_id):
        database.log_audit_event(telegram_id, "UNAUTHORIZED_RATE_ATTEMPT", appeal_id, "Boshqa fuqaro murojaatini baholashga urinish", "FAILED")
        return jsonify({"status": "error", "message": "Сиз фақат ўзингизнинг мурожаатингизни баҳолай оласиз"}), 403

    if murojaat.get("Status") not in RATEABLE_STATUSES:
        return jsonify({"status": "error", "message": "Мурожаат кўриб чиқилгандан кейин баҳолаш мумкин"}), 400

    if murojaat.get("Baho") not in (None, ""):
        return jsonify({"status": "error", "message": "Ушбу мурожаат аввал баҳоланган"}), 409

    database.save_murojaat_rating(appeal_id, score, actor=telegram_id)
    stars = "⭐" * score
    alert_text = (
        f"⭐ <b>Фуқаро хизмат сифатини баҳолади! (CSAT)</b>\n\n"
        f"🔢 <b>Мурожаат:</b> #{appeal_id}\n"
        f"🌟 <b>Баҳо:</b> {stars} ({score}/5 балл)\n"
        f"🆔 <b>TG ID:</b> <code>{telegram_id}</code>"
    )
    send_admin_alert(alert_text)
    return jsonify({"status": "ok", "message": "Баҳо сақланди"})


# ==============================================================================
# 7. AI HUQUQIY MASLAHATCHI CHAT API
# ==============================================================================
@app.route("/api/ai_chat", methods=["POST"])
@require_tma_auth
def ai_chat():
    """AI Huquqiy maslahatchi chat API si."""
    data = _json_body()
    message = str(data.get("message", "")).strip()
    user_id = request.authenticated_user_id

    if not message:
        return jsonify({"status": "error", "message": "Савол матни бўш"}), 400

    if len(message) > 3000:
        return jsonify({"status": "error", "message": "Савол матни жуда узун"}), 400

    # AI kvotasini bitta foydalanuvchi tugatib qo'ymasligi uchun
    if not check_rate_limit(f"ai_chat:{user_id}", max_requests=10, window_seconds=60):
        return jsonify({"status": "error", "message": "Жуда кўп савол юборилди. Илтимос, бир дақиқадан сўнг қайта уриниб кўринг."}), 429

    # 1. Bot bilan bir xil javob oqimi (mahalliy baza, keyin hujjatga tayangan AI)
    try:
        if _ai_backend:
            result = _ai_backend(message, user_id, database.get_user_lang(user_id))
            if result.get("answer"):
                return jsonify({"status": "ok", "source": result.get("source", "ai"), "reply": result["answer"]})
        else:
            handled_locally, _, _, local_ans = local_legal_advisor.try_local_answer(message, user_id)
            if handled_locally and local_ans:
                return jsonify({"status": "ok", "source": "local", "reply": to_new_uzbek_latin(local_ans)})
    except Exception as ai_err:
        logger.warning(f"AI chaqirishda xatolik: {ai_err}")

    # 2. Zaxira shoshilinch javob
    fallback_reply = (
        "Ҳурматли фуқаро! Саволингиз Шайх-Али МФЙ ҳуқуқий базаси бўйича қабул қилинди. "
        "Ушбу масала юзасидан бепул ва тўлиқ қонуний маслаҳат олиш учун Шайх-Али МФЙ ижтимоий ходими "
        "(А. Жўраев: +998 91 454 53 51) билан боғланишингизни тавсия қиламиз."
    )
    return jsonify({
        "status": "ok",
        "source": "fallback",
        "reply": fallback_reply
    })


# ==============================================================================
# 8. MA'MURIY (ADMIN) ENDPOINTLAR
# ==============================================================================
@app.route("/api/admin/audit_logs", methods=["GET"])
@require_admin
def admin_audit_logs():
    """Faqat administrator uchun: tizim audit jurnali."""
    limit = request.args.get("limit", 50, type=int)
    logs = database.get_audit_logs(limit=max(1, min(limit, 200)))
    return jsonify({"status": "ok", "audit_logs": logs})


@app.route("/api/admin/export_excel", methods=["POST"])
@require_admin
def admin_export_excel():
    """Faqat administrator uchun: Excel eksporti (fayl yuboriladi, serverda nusxa qoldirilmaydi)."""
    try:
        path = database.export_all_to_excel(actor=request.authenticated_user_id)
        try:
            with open(path, "rb") as f:
                content = io.BytesIO(f.read())
        finally:
            os.remove(path)
        return send_file(
            content,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=os.path.basename(path),
        )
    except Exception as e:
        logger.error(f"Eksport xatosi: {e}")
        return jsonify({"status": "error", "message": "Eksportda xatolik"}), 500


# ==============================================================================
# 9. SERVERNI ISHGA TUSHIRISH
# ==============================================================================
def run_server(host="127.0.0.1", port=5001):
    """Flask serverini ishga tushirish."""
    logger.info(f"🌐 TMA WebApp Server faollashmoqda: http://{host}:{port}")
    serve(app, host=host, port=port, threads=8)


def start_server_in_background(host="127.0.0.1", port=5001, bot=None):
    """Serverni alohida orqa fonda (daemon thread) ishga tushiradi."""
    if bot:
        set_bot_instance(bot)
    t = threading.Thread(target=run_server, args=(host, port), daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    database.init_database()
    run_server(host=os.getenv("WEBAPP_HOST", "127.0.0.1"), port=int(os.getenv("PORT", 5001)))
