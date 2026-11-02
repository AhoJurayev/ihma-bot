from utils.pii_masker import mask_pii
from utils.text_normalizer import normalize_for_search, latin_to_cyrillic_uz, ensure_cyrillic
from utils.audio_transcriber import transcribe_audio_bytes
from utils.server_monitor import (
    get_system_metrics,
    format_server_status_html,
    get_recent_logs,
    clean_logs_file,
)
# -*- coding: utf-8 -*-
"""
Qarshi shahar "Shayx-Ali" MFY Ijtimoiy xodim (A. Jo'rayev) ning
IHMA Sun'iy Intellekt (Gemini AI) Yordamchi va Murojaatlar Boshqaruvi Telegram Boti.

O'rnatish uchun kerakli kutubxonalar:
    pip install pyTelegramBotAPI pandas openpyxl google-generativeai
"""

import os
import re
import html
import json
import time
import urllib.request
import threading
import logging
import builtins
from collections import Counter
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import telebot
from telebot import types
import google.generativeai as genai
from knowledge_base import (
    HUJJATLAR_DIR,
    build_knowledge_index,
    load_knowledge_index,
    search_knowledge_base,
    format_legal_grounding_prompt,
    get_knowledge_base_stats,
)
from local_legal_advisor import try_local_answer

# ==============================================================================
# 1. SOZLAMALAR (CONFIG) VA XAVFSIZLIK (ENVIRONMENT VARIABLES)
# ==============================================================================
def load_env_file(filepath=None):
    """
    Tashqi kutubxonalarsiz (python-dotenv talab qilmasdan) .env faylini xavfsiz o'qish.
    Agar .env mavjud bo'lmasa, tizimning mavjud os.environ o'zgaruvchilaridan foydalanadi.
    """
    if filepath is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.join(base_dir, ".env")
        if not os.path.exists(filepath):
            filepath = ".env"

    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
        except Exception as e:
            print(f"⚠️ .env faylini o'qishda ogohlantirish: {e}")

load_env_file()

# .env o'qilgandan keyin yuklanadi: baza yo'li IHMA_DATA_DIR ga bog'liq
import database
database.init_database()
import admin_ai_assistant

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

if not TOKEN or TOKEN == "xxxxx":
    raise ValueError("❌ XATOLIK: TELEGRAM_BOT_TOKEN .env faylida yoki muhit o'zgaruvchilarida topilmadi!")

if not ADMIN_ID or ADMIN_ID == "xxxxx":
    raise ValueError("❌ XATOLIK: ADMIN_ID .env faylida yoki muhit o'zgaruvchilarida topilmadi!")

# Barcha mavjud Gemini kalitlarini yig'ish (Multi-API key support)
GEMINI_API_KEYS = []
if GEMINI_API_KEY and GEMINI_API_KEY != "xxxxxxx":
    for k in GEMINI_API_KEY.split(","):
        k = k.strip()
        if k and k not in GEMINI_API_KEYS:
            GEMINI_API_KEYS.append(k)

for i in range(2, 6):
    extra_k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
    if extra_k and extra_k not in GEMINI_API_KEYS:
        GEMINI_API_KEYS.append(extra_k)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("ihma.bot")


def _setup_file_logging():
    """Barcha xabarlarni admin paneli o'qiydigan bot.log ga yozadi (5 MB dan 3 ta fayl)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return
    file_handler = RotatingFileHandler(
        os.path.join(BASE_DIR, "bot.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)


def print(*args, **kwargs):
    """Konsolga chiqarish bilan birga loglash: kod bo'ylab print ishlatilgan."""
    builtins.print(*args, **kwargs)
    logger.info(" ".join(str(a) for a in args))


class BotExceptionHandler(telebot.ExceptionHandler):
    """Handler xatosi polling ni to'xtatmasligi va logda qolishi uchun."""

    def handle(self, exception):
        logger.error("Handler xatosi: %s", exception, exc_info=exception)
        return True


# Bloklovchi AI so'rovlari boshqa fuqarolarni kuttirib qo'ymasligi uchun ishchi oqimlar soni oshirilgan
bot = telebot.TeleBot(TOKEN, num_threads=8, exception_handler=BotExceptionHandler())
WEB_APP_URL = os.getenv("WEB_APP_URL", "").strip()

if GEMINI_API_KEYS:
    genai.configure(api_key=GEMINI_API_KEYS[0])

OFERTA_FILE = os.path.join(BASE_DIR, "Shayxali_MFY_bot_oferta.pdf")

# AI so'rovlari uchun vaqt chegaralari (soniya)
AI_REQUEST_TIMEOUT = 45
AI_TOTAL_TIMEOUT = 120

# Minimal iste'mol xarajatlari (so'mda)
MINIMAL_ISTEMOL_XARAJATI = 669000

# Majburiy yakuniy AI ogohlantirish matni (Foydalanuvchi talabiga asosan butunlay tozalandi)
AI_DISCLAIMER = ""

# Fuqaroga savol yozishdan oldin chiqadigan qonuniy xavfsizlik ogohlantirishi
PRIVACY_WARNING_TEXT = (
    "🔒 <b>XAVFSIZLIK BO'YICHA OGOHLANTIRISH (O'RQ-547):</b>\n\n"
    "O'zbekiston Respublikasining «Shaxsga doir ma'lumotlar to'g'risida»gi Qonuniga muvofiq, "
    "savol yoki murojaat matnida <b>pasport seriyasi va raqami, JShShIR (PINFL), bank plastik "
    "karta raqamlari hamda SMS-kodlarni oshkor qilmang!</b>\n\n"
    "✍️ Savolingizni matn shaklida yozing yoki 🎤 <b>ovozli xabar (voice)</b> yuboring:"
)

# ==============================================================================
# 2. GEMINI AI MODELI VA PROFESSIONAL SYSTEM PROMPT
# ==============================================================================
generation_config = {
    "temperature": 0.2,  # Qonuniy aniqlik va gallyutsinatsiyani oldini olish uchun past qiymat
    "top_p": 0.90,
    "top_k": 40,
    "max_output_tokens": 2048,  # Kompleks empatik tahlil uchun kengaytirilgan hajm
}

SYSTEM_PROMPT = """
Сиз — Ўзбекистон Республикаси Ижтимоий ҳимоя миллий агентлигининг (ИҲМА) "Инсон" ижтимоий хизматлар маркази ҳамда Қашқадарё вилояти, Қарши шаҳар "Шайх-Али" (Шайхали) МФЙ ижтимоий ходими (А. Жўраев: +998 91 454 53 51) нинг расмий ва ақлли ёрдамчи AI агентисиз.

МУҲИМ ҚОИДА: Фойдаланувчининг саволини дастлаб чуқур таҳлил қилиб, жавоб услубини қатъий равишда қуйидаги 2 та ҳолатга қараб танланг:

==================================================
1-ҲОЛАТ: УМУМИЙ МАЪЛУМОТ, ТУШУНЧА ЁКИ ҲУҚУҚИЙ САВОЛЛАР
(Масалан: "IHMA nima?", "Қандай ёрдам турлари бор?", "Бола пули қандай ҳисобланади?", "Қаерда жойлашгансиз?")
==================================================
- ҚАТЪИЯН ТАҚИҚЛАНАДИ: "ID Мурожаат рақами", "1-Қадам, 2-Қадам", "Форс-мажор" ёки шартномавий мажбуриятлар бандлари каби ортиқча шаблонларни ишлатиш!
- ҚАНДАЙ ЖАВОБ БЕРИШ КЕРАК:
  * Дўстона, ўта тушунарли, оддий халқ тилида ва лўнда (максимал 2-3 та қисқа хатбоши).
  * Асосий моҳиятни пунктлар (bullet points: •) билан ажратиб кўрсатинг.
  * Агар қўшимча ёрдам керак бўлса, Шайх-Али МФЙ ижтимоий ходими А. Жўраев (+998 91 454 53 51) билан боғланиш мумкинлигини битта қисқа жумлада эслатиб ўтинг.
- ТИЗИМ ТЕГИ: Жавобнинг энг бошида [TURI: QONUNIY_MASLAHAT] ва [MUHIMLIK: ODDIY] деб ёзинг, сўнг "---" дан кейин соф жавобни беринг.

==================================================
2-ҲОЛАТ: АНИҚ ШАХСИЙ МУАММО, ШИКОЯТ ЁКИ АРИЗА
(Масалан: "Моддий ёрдам ололмаяпман", "Аравача керак", "Уйимда ёнғин бўлди", "Тазйиққа учрадим")
==================================================
- Фақат мана шу ҳолатдагина мурожаатни индивидуал кўриб чиқишга қабул қилиб, 4 босқичли амалий ечим харитасини тақдим этинг:
  📌 1-Қадам: Самимий мурожаат ва бирламчи далда.
  📌 2-Қадам: Зудлик билан кўриладиган чоралар (24-48 соат ичида: хавфсизлик, ҳимоя ордери ёки шошилинч кўмак).
  📌 3-Қадам: Босқичма-босқич ечимлар харитаси (Ҳужжатлар -> Тиббиёт/ТББ -> Таълим -> Моддий ёрдам).
  📌 4-Қадам: Масъул ижрочи ва амалий алоқа (Шайх-Али МФЙ ижтимоий ходими А. Жўраев: +998 91 454 53 51).
- ТИЗИМ ТЕГИ: Жавобнинг энг бошида [TURI: SHAXSIY_MUROJAAT] ва вазиятга қараб [MUHIMLIK: SHOSHILINCH] ёки [MUHIMLIK: ORTA] деб ёзинг.

==================================================
САВОЛГА МОС ЖАВОБ БЕРИШ ВА МАЗМУНИЙ ЧЕКЛОВЛАР:
==================================================
1. Фойдаланувчи сўрамаган нарсаларни (масалан, умумий саволга форс-мажор ҳолатлари, пуллик хизматлар шартномаси, тиббий шартномалар ёки юридик мажбуриятлар бандларини) жавобга асло қўшманг! Фақат берилган савол моҳиятини соф ва аниқ ёритинг.
2. Ҳар доим соф ЎЗБЕК КИРИЛЛ АЛИФБОСИДА (Ў, Қ, Ғ, Ҳ ҳарфлари билан) ёзинг. Лотин ҳарфларини аралаштирманг!
3. Форматлашда Telegram HTML тегларидан фойдаланинг: <b>қалин</b>, <i>оғма</i>, <code>код</code>. Асло Markdown (#, **) ишлатманг.
4. Қонуний кафолат берманг ("Сизга албатта берилади" эмас, "Қонуний мезонлар ва комиссия хулосасига асосан кўриб чиқилади" деб тушунтиринг).
5. ҚАТЪИЙ МОЛИЯВИЙ ВА ҲУҚУҚИЙ ҚОИДА (ФАҚАТ БХМ ВА МИҲ):
   - Қонунлар, қарорлар, нафақалар, моддий ёрдам ва бошқа тўловлар бўйича маълумот берганда ТАХМИНИЙ СЎМ СУММАСИНИ (масалан: "тахминан 500 000 сўм", "750 000 сўм атрофида", "1 миллион сўм берилади") АСЛО ЁЗМАНГ!
   - Барча тўлов, нафақа, жарима ва ёрдам миқдорларини ФАҚАТ ВА ФАҚАТ расмий қонунда белгиланган БХМ (Базавий ҳисоблаш миқдори) ёки МИҲ (Минимал истеъмол харажатлари) кўрсаткичларида (масалан: «БХМнинг 50 фоизи миқдорида», «БХМнинг 2 баравари миқдорида», «оила аъзосига тўғри келадиган бир ойлик даромад МИҲ мезонидан ошмаслиги лозим») кўрсатинг!
   - Сабаби: Сўм суммалари давлат қарорлари билан мунтазам ўзгариб туради, қонунчилик меъёри эса БХМ/МИҲ нисбатларида ўзгармас бўлиб қолади.
"""

ai_model = genai.GenerativeModel(
    model_name=GEMINI_MODEL_NAME,
    generation_config=generation_config,
    system_instruction=SYSTEM_PROMPT,
)


class SafeAIResponse:
    def __init__(self, text: str):
        self.text = text


def call_groq_api(prompt: str, system_prompt: str = "") -> SafeAIResponse:
    """
    Groq ultra-tezkor AI orqali so'rov yuborish (PII niqoblangan ҳолда va exponential backoff bilan).
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise ValueError("GROQ_API_KEY topilmadi!")

    # Shaxsiy ma'lumotlarni niqoblash (O'RQ-547 talabi)
    safe_prompt = mask_pii(prompt)
    groq_models = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
    sys_p = system_prompt or SYSTEM_PROMPT

    for model in groq_models:
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    },
                    data=json.dumps({
                        "model": model,
                        "messages": [
                            {"role": "system", "content": sys_p},
                            {"role": "user", "content": safe_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 2048,
                    }).encode("utf-8"),
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content and content.strip():
                            return SafeAIResponse(latin_to_cyrillic_uz(content))
            except Exception as e:
                time.sleep(0.5 * (attempt + 1))
                continue

    raise RuntimeError("Barcha Groq modellari xatolik berdi yoki ulanishda muammo.")


def call_ai_strict(contents):
    """
    1-bosqich: Google Gemini (GEMINI_MODEL_NAME va zaxira modellar) orqali so'rov yuborish.
    PII Masking (O'RQ-547) avtomatik qo'llaniladi.
    2-bosqich: Gemini tokeni/kvotasi tugasa avtomatik Groq zaxira kalitiga o'tadi.
    Barcha provayderlar ishlamasa RuntimeError ko'taradi.
    """
    last_gemini_err = None
    deadline = time.monotonic() + AI_TOTAL_TIMEOUT

    # Shaxsiy ma'lumotlarni niqoblash
    if isinstance(contents, str):
        safe_contents = mask_pii(contents)
    elif isinstance(contents, list):
        safe_contents = [mask_pii(c) if isinstance(c, str) else c for c in contents]
    else:
        safe_contents = contents

    gemini_models = [
        GEMINI_MODEL_NAME,
        "gemini-2.5-flash",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
    ]
    seen_m = set()
    uniq_models = [m for m in gemini_models if not (m in seen_m or seen_m.add(m))]

    active_keys = GEMINI_API_KEYS if GEMINI_API_KEYS else ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
    for key_idx, g_key in enumerate(active_keys):
        try:
            genai.configure(api_key=g_key)
        except Exception:
            pass

        for m_name in uniq_models:
            for retry in range(2):
                if time.monotonic() >= deadline:
                    break
                try:
                    model_inst = genai.GenerativeModel(
                        model_name=m_name,
                        generation_config=generation_config,
                        system_instruction=SYSTEM_PROMPT,
                    )
                    resp = model_inst.generate_content(safe_contents, request_options={"timeout": AI_REQUEST_TIMEOUT})
                    if hasattr(resp, "text") and resp.text:
                        resp = SafeAIResponse(latin_to_cyrillic_uz(resp.text))
                    return resp
                except Exception as e:
                    err_str = str(e).lower()
                    last_gemini_err = e
                    if any(x in err_str for x in ["429", "quota", "resource_exhausted", "limit"]):
                        break
                    time.sleep(0.5 * (retry + 1))
                    continue

    # Zaxira Groq API ga o'tish
    groq_err = None
    if isinstance(contents, str):
        try:
            return call_groq_api(contents, system_prompt=SYSTEM_PROMPT)
        except Exception as e:
            groq_err = e

    raise RuntimeError(f"AI provayderlari javob bermadi (Gemini: {last_gemini_err}; Groq: {groq_err})")


def call_gemini_safe(contents):
    """call_ai_strict bilan bir xil, lekin barcha provayderlar ishlamasa xavfsiz huquqiy tushuntirish qaytaradi."""
    try:
        return call_ai_strict(contents)
    except Exception as e:
        print("AI so'rovi bajarilmadi:", e)

    fallback_text = (
        "Ҳурматли фуқаро! Сиз сўраган масала бўйича қонуний асослар ва меъёрий ҳужжатларни аниқлаштириш талаб этилади. "
        "Сунъий интеллект тизимида расмий қарор қабул қилиш ваколати мавжуд эмас. "
        "Шайх-Али МФЙ ижтимоий ходими (А. Жўраев: +998 91 454 53 51) қабулига ёзилишингизни ёки расмий мурожаат қолдиришингизни тавсия этамиз."
    )
    return SafeAIResponse(fallback_text)


# ==============================================================================
# 3. TEZKOR SAVOLLAR (FAQ) VA MANZILLAR BAZASI (API'SIZ SONIYALARDA JAVOB)
# ==============================================================================
FAQ_ANSWERS = {
    "faq_bola_puli": (
        "👶 <b>Bolalar nafaqasi («Bola puli») uchun qanday hujjatlar kerak va tartibi qanday?</b>\n\n"
        "📌 <b>Huquqiy asos:</b> Vazirlar Mahkamasining 654-son qarori.\n\n"
        "1️⃣ <b>Ariza topshirish:</b> Hozirgi kunda ariza <b>my.gov.uz</b> portali, Davlat xizmatlari markazi (DXM) yoki mahalla <b>Ijtimoiy xodimi</b> orqali elektron shaklda yuboriladi.\n"
        "2️⃣ <b>Kerakli ma'lumotlar:</b>\n"
        "• Ariza beruvchi va oila a'zolarining pasporti (ID-kartasi) hamda JShShIR raqamlari;\n"
        "• Bolalarning tug'ilganlik haqidagi guvohnomalari;\n"
        "• Nikoh guvohnomasi (yoki ajrim/vafot etganlik haqida ma'lumot);\n"
        "• <i>Qo'shimcha qog'oz ma'lumotnomalar (ish haqi, mulk, avtomobil) talab etilmaydi — «Ijtimoiy himoya yagona reestri» tizimi ularni vazirliklar bazasidan avtomatik tekshiradi.</i>\n"
        "3️⃣ <b>Asosiy shartlar:</b>\n"
        "• Oilaning har bir a'zosiga to'g'ri keladigan o'rtacha oylik daromad minimal iste'mol xarajatlaridan oshmasligi;\n"
        "• Mehnatga layoqatli oila a'zolarining rasmiy band bo'lishi (yoki bandlik organida ro'yxatda turishi);\n"
        "• Oilada 2 va undan ortiq ko'chmas mulk yoki yangi (oxirgi 7-12 yilda ishlab chiqarilgan soz) yengil avtomobil bo'lmasligi."
        + AI_DISCLAIMER
    ),
    "faq_moddiy_yordam": (
        "🤝 <b>Moddiy yordam kimlarga va qanday tartibda beriladi?</b>\n\n"
        "📌 <b>Huquqiy asos:</b> Vazirlar Mahkamasining 654-son hamda 2024-yil 23-iyuldagi 442-son qarorlari.\n\n"
        "1️⃣ <b>Kam ta'minlangan oilalarga oylik moddiy yordam (VM-654):</b>\n"
        "• Tizim orqali 6 oy muddatga tayinlanadi (oila daromadi va mulkiy mezonlar elektron tekshiriladi).\n\n"
        "2️⃣ <b>«Saxovat va ko'mak» jamg'armasi hisobidan yordam (VM-442):</b>\n"
        "• «Kambag'allik reestri»ga (yoki Ijtimoiy reestrga) kiritilgan hamda og'ir hayotiy vaziyatga tushib qolgan oilalarga mahalla ijtimoiy xodimi va «mahalla beshligi» o'rganishi asosida ko'rsatiladi;\n"
        "• Davolanish xarajatlari naqd pulda emas, balki <b>yo'llanma (vaucher)</b> asosida bevosita tibbiyot muassasasiga o'tkazib beriladi.\n\n"
        "📍 Individual holatingizni o'rganish uchun Shayxali MFY ijtimoiy xodimiga murojaat qilishingiz mumkin."
        + AI_DISCLAIMER
    ),
    "faq_nogironlik": (
        "♿ <b>Nogironlikni belgilash va reabilitatsiya vositalarini olish tartibi</b>\n\n"
        "📌 <b>Huquqiy asos:</b> O'RQ-641-son Qonun, Vazirlar Mahkamasining 539-son va 411-son qarorlari.\n\n"
        "1️⃣ <b>Nogironlik guruhini belgilash:</b>\n"
        "• Fuqaro hududiy oilaviy poliklinikaga murojaat qiladi. Shifokorlar tibbiy hujjatlarni elektron tizim orqali <b>TIEK (Tibbiy-ijtimoiy ekspert komissiyasi)</b> ga yuboradi;\n"
        "• Og'ir yotib qolgan bemorlar mahalla ijtimoiy xodimi ko'magida uyda yoki sirtdan ko'rikdan o'tkazilishi mumkin.\n\n"
        "2️⃣ <b>Protez-ortopediya va reabilitatsiya vositalari (nogironlik aravachasi, eshitish moslamasi, hassa va b.):</b>\n"
        "• Elektron <b>Vaucher (sertifikat)</b> tizimi orqali taqdim etiladi. Fuqaro o'zi xohlagan ishlab chiqaruvchidan vositani tanlab olishi mumkin.\n"
        "• Ariza berishda Shayxali MFY ijtimoiy xodimi yoki Qarshi shahar «Inson» markazi bevosita amaliy yordam ko'rsatadi."
        + AI_DISCLAIMER
    ),
    "faq_qonunchilik": (
        "📜 <b>Ijtimoiy himoya sohasidagi yangi qonunchilik ma'lumotlari</b>\n\n"
        "1️⃣ <b>«Inson» ijtimoiy xizmatlar markazlari va mahalla ijtimoiy xodimi (PF-82, PQ-176):</b>\n"
        "• Har bir mahallada professional ijtimoiy xodim faoliyati yo'lga qo'yildi. Endilikda 70 dan ortiq ijtimoiy xizmat va yordamlar bevosita mahallaning o'zida ko'rsatiladi.\n\n"
        "2️⃣ <b>«Kambag'allikdan farovonlik sari» dasturi va Reestr (PF-37, VM-442):</b>\n"
        "• Ehtiyojmand oilalar mahalla beshligi va ijtimoiy xodim tomonidan kompleks o'rganilib, individual xizmatlar rejasi tuziladi;\n"
        "• Davolanish, dori-darmon, kiyim-kechak va zarur ehtiyojlar uchun «Saxovat va ko'mak» jamg'armasidan shaffof tartibda ko'mak ajratiladi.\n\n"
        "3️⃣ <b>Ijtimoiy xodim bilan to'g'ridan-to'g'ri aloqa:</b>\n"
        "• Shayxali MFY ijtimoiy xodimi (A. Jo'rayev) telefon raqami: <b>+998 91 454 53 51</b>."
        + AI_DISCLAIMER
    ),
}

MANZILLAR_TEXT = (
    "📍 <b>KERAKLI TASHKILOTLAR MANZILLARI VA BOG'LANISH RAQAMLARI:</b>\n\n"
    "🏛 <b>1. «Shayx-Ali» (Shayxali) MFY binosi va Ijtimoiy xodim:</b>\n"
    "• <b>Ijtimoiy xodim:</b> Jo'rayev A.\n"
    "• <b>Telefon:</b> <code>+998 91 454 53 51</code>\n"
    "• <b>MFY raisi:</b> Kodirov Sh.\n"
    "• <b>Manzil:</b> Qarshi shahri, Shayx-Ali MFY idorasi\n"
    "• <b>Qabul kunlari:</b> Dushanba – Juma (09:00 dan 18:00 gacha)\n\n"
    "🏢 <b>2. Qarshi shahar «Inson» ijtimoiy xizmatlar markazi:</b>\n"
    "• <b>Manzil:</b> Qarshi shahri (shahar «Inson» markazi binosi)\n"
    "• <b>Ish vaqti:</b> Dushanba – Juma (09:00 – 18:00, tushlik: 13:00 – 14:00)\n\n"
    "🏥 <b>3. Tibbiy-ijtimoiy ekspert komissiyasi (TIEK) va DXM:</b>\n"
    "• <b>Davlat xizmatlari markazi (DXM):</b> Qarshi shahar DXM binosi\n"
    "• <b>Onlayn portal:</b> https://my.gov.uz va https://ihma.uz\n\n"
    "☎️ <b>4. To'g'ridan-to'g'ri aloqa:</b>\n"
    "• <b>Shayxali MFY ijtimoiy xodimi (A. Jo'rayev):</b> <code>+998 91 454 53 51</code>"
)

# ==============================================================================
# 4. EXCEL BAZA FUNKSIYALARI, VALIDATSIYA VA DUBLIKATLARNI CHEKLASH
# ==============================================================================
FUQAROLAR_COLUMNS = [
    "Telegram_ID",
    "FIO",
    "Telefon",
    "Pasport_Seriya",
    "JSHSHIR",
    "Pasport_JSHSHIR",
    "Kocha_Manzil",
    "Geolokatsiya",
    "Manzil_Geolokatsiya",
    "Status",
    "Til",
    "Royxatdan_Otgan_Sana",
]

MUROJAAT_COLUMNS = [
    "Murojaat_ID",
    "Sana",
    "Oy_Yil",
    "Telegram_ID",
    "FIO",
    "Telefon",
    "Pasport_JSHSHIR",
    "Kocha_Manzil",
    "Savol",
    "AI_Javobi",
    "Turi",
    "Muhimlik",
    "Status",
    "Admin_Izohi",
    "Eslatma_Yuborildi",
]

NAVBAT_COLUMNS = [
    "Navbat_ID",
    "Yaratilgan_Vaqt",
    "Telegram_ID",
    "FIO",
    "Telefon",
    "Kocha_Manzil",
    "Qabul_Kuni",
    "Qabul_Soati",
    "Status",
]


# Vaqtinchalik xotira (sessiya holatlari)
user_data = {}
admin_state = {}
calc_state = {}
user_lang_cache = {}  # 'uz_lat', 'uz_cyr', 'ru'

CYR_TO_LAT_PASSPORT = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Д": "D", "Е": "E", "Ф": "F",
    "Г": "G", "Ҳ": "H", "И": "I", "Ж": "J", "К": "K", "Л": "L",
    "М": "M", "Н": "N", "О": "O", "П": "P", "Қ": "Q", "Р": "R",
    "Т": "T", "У": "U", "Х": "X", "Й": "Y", "З": "Z",
})


def esc(val) -> str:
    """HTML parse_mode da maxsus belgilarni (<, >, &) xavfsiz kodlash (Telegram HTML uchun)."""
    if val is None:
        return ""
    s = str(val)
    s = s.replace("&#x27;", "'").replace("&#39;", "'").replace("&apos;", "'").replace("&quot;", '"')
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def safe_delete_message(chat_id, message_id):
    """Foydalanuvchi yuborgan shaxsiy ma'lumotli xabarni chatdan darhol o'chirish."""
    if not message_id:
        return
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# ==============================================================================
# KO'P TILLILIK: YANGI O'ZBEK LOTIN / КИРИЛЛ / РУССКИЙ KONVERTATSIYASI
# ==============================================================================
CYR_TO_LAT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ё": "yo", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ж": "J", "З": "Z",
    "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "X",
    "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sh", "Ъ": "'", "Ь": "", "Э": "E", "Ю": "Yu",
    "Я": "Ya", "Ё": "Yo", "Ў": "O'", "Қ": "Q", "Ғ": "G'", "Ҳ": "H",
}

VOWELS_CYR = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ\u0430\u0435\u0451\u0438\u043e\u0443\u044d\u044e\u044f\u045e\u0410\u0415\u0401\u0418\u041e\u0423\u042d\u042e\u042f\u040e")


def to_new_uzbek_latin(text: str) -> str:
    """Барча лотинча матнларни расмий Кирилл алифбосига ўгиради."""
    return latin_to_cyrillic_uz(text)

def _legacy_to_new_uzbek_latin(text: str) -> str:
    """Стандарт Ўзбек Лотин алифбосига ўгириш (туркча ҳарфларсиз)."""
    return cyrillic_to_latin_uz(text)


def cyrillic_to_latin_uz(text: str) -> str:
    """
    O'zbek kirill yozuvidagi matnni rasmiy Yangi O'zbek Lotin alifbosiga to'liq
    va imlo me'yorlari asosida o'giradi (HTML teglar va havolalarni saqlaydi).
    """
    if not text:
        return ""
    parts = re.split(r"(<[^>]+>)", text)
    out = []
    for p in parts:
        if (p.startswith("<") and p.endswith(">")) or any(u in p for u in ["http://", "https://", "my.gov.uz"]):
            out.append(p)
            continue
        res = []
        for i, c in enumerate(p):
            prev_c = p[i - 1] if i > 0 else " "
            if c in ("\u0415", "Е"):
                res.append("Ye" if (i == 0 or not prev_c.isalpha() or prev_c in VOWELS_CYR) else "E")
            elif c in ("\u0435", "е"):
                res.append("ye" if (i == 0 or not prev_c.isalpha() or prev_c in VOWELS_CYR) else "e")
            else:
                res.append(CYR_TO_LAT_MAP.get(c, c))
        out.append("".join(res))
    return "".join(out)


def get_user_lang(user_id) -> str:
    if user_id in user_lang_cache:
        lang = user_lang_cache[user_id]
    else:
        lang = database.get_user_lang(user_id)
        user_lang_cache[user_id] = lang
    if lang == "ru":
        return "ru"
    return "uz_cyr"


def set_user_lang(user_id, lang_code: str):
    user_lang_cache[user_id] = lang_code
    database.set_user_lang(user_id, lang_code)


def localize_text(user_id, text_uz: str, text_ru: str = None) -> str:
    """Матнни фойдаланувчи тилига (Кирилл ёки Рус) мослаб қайтаради."""
    lang = get_user_lang(user_id)
    if lang == "ru" and text_ru:
        return text_ru
    return latin_to_cyrillic_uz(text_uz)


def validate_passport_serial(raw_text: str):
    """Majburiy 2 ta harf va 7 ta raqam (Masalan: AA1234567)."""
    cleaned = re.sub(r"[\s\-_]", "", str(raw_text or "")).upper().translate(CYR_TO_LAT_PASSPORT)
    if re.fullmatch(r"[A-Z]{2}\d{7}", cleaned):
        return cleaned
    return None


def validate_jshshir(raw_text: str):
    """Majburiy 14 ta raqam (Masalan: 31201901234567)."""
    cleaned = re.sub(r"[\s\-_]", "", str(raw_text or ""))
    if re.fullmatch(r"\d{14}", cleaned):
        return cleaned
    return None


def extract_passport_and_jshshir(raw_text: str):
    upper_text = str(raw_text or "").upper().translate(CYR_TO_LAT_PASSPORT)
    p_match = re.search(r"\b([A-Z]{2})\s*(\d{7})\b", upper_text)
    j_match = re.search(r"\b(\d{14})\b", upper_text)
    pasport = f"{p_match.group(1)}{p_match.group(2)}" if p_match else None
    jshshir = j_match.group(1) if j_match else None
    return pasport, jshshir


def normalize_phone(phone_str: str) -> str:
    """Telefon raqamni faqat raqamlardan iborat oxirgi 9 xonasiga keltiradi (dublikat tekshirish uchun)."""
    digits = re.sub(r"\D", "", str(phone_str or ""))
    return digits[-9:] if len(digits) >= 9 else digits


def normalize_doc(doc_str: str) -> str:
    """Pasport va JSHSHIR matnini bo'shliqlarsiz katta harflarga keltiradi (dublikat tekshirish uchun)."""
    return re.sub(r"[\s\-_,.;:]", "", str(doc_str or "")).upper()


def get_citizen_by_tg_id(user_id):
    """Telegram ID orqali fuqaro ma'lumotlarini SQLite bazasidan olish."""
    return database.get_citizen_by_tg_id(user_id)


def is_citizen_verified(user_id) -> bool:
    """Fuqaroning shaxsi rasmiy tasdiqlanganligini tekshirish."""
    return database.is_citizen_verified(user_id)


def check_duplicate_citizen(user_id, telefon=None, pasport=None, jshshir=None, pasport_jshshir=None):
    """
    Telefon raqam, Pasport seriya-raqami yoki 14 xonali JSHSHIR bazada oldin
    kiritilganligini tekshiradi. Dublikat bo'lsa (True, mavjud_qator) qaytaradi.
    """
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fuqarolar")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    norm_tel = normalize_phone(telefon) if telefon else ""
    norm_pasp = normalize_doc(pasport) if pasport else ""
    norm_jsh = normalize_doc(jshshir) if jshshir else ""
    norm_comb = normalize_doc(pasport_jshshir) if pasport_jshshir else ""

    for r in rows:
        if str(r.get("Telegram_ID", "")) == str(user_id):
            continue
        ex_tel = normalize_phone(r.get("Telefon", ""))
        ex_pasp = normalize_doc(r.get("Pasport_Seriya", ""))
        ex_jsh = normalize_doc(r.get("JSHSHIR", ""))
        ex_comb = normalize_doc(r.get("Pasport_JSHSHIR", ""))

        if norm_tel and ex_tel and norm_tel == ex_tel:
            return True, r
        if norm_pasp and (norm_pasp == ex_pasp or (len(norm_pasp) == 9 and norm_pasp in ex_comb)):
            return True, r
        if norm_jsh and (norm_jsh == ex_jsh or (len(norm_jsh) == 14 and norm_jsh in ex_comb)):
            return True, r
        if norm_comb and ex_comb and norm_comb == ex_comb:
            return True, r

    return False, None


def save_or_update_citizen(user_id, fio, telefon, pasport_seriya="", jshshir="", kocha_manzil="", geolokatsiya="", status="Tasdiqlangan"):
    """
    Fuqaroni SQLite bazasiga saqlaydi va Excel ga sinxronlaydi.
    """
    lang_val = user_lang_cache.get(user_id, "uz_lat")
    return database.save_or_update_citizen(
        user_id=user_id,
        fio=fio,
        telefon=telefon,
        pasport_seriya=pasport_seriya,
        jshshir=jshshir,
        kocha_manzil=kocha_manzil,
        geolokatsiya=geolokatsiya,
        status=status,
        til=lang_val,
    )


def update_excel_status(user_id, status):
    """Fuqaroning tasdiqlanish statusini yangilash."""
    database.update_citizen_status(user_id, status)


def save_murojaat(user_id, savol, ai_javobi, turi, muhimlik, status, admin_izohi=""):
    """Murojaatni SQLite bazasiga yozadi va unikal Murojaat_ID qaytaradi."""
    return database.save_murojaat(user_id, savol, ai_javobi, turi, muhimlik, status, admin_izohi)


def update_murojaat_status(murojaat_id, yangi_status, admin_izohi=None):
    """Murojaat statusini yangilaydi va tegishli murojaat qatorini qaytaradi."""
    return database.update_murojaat_status(murojaat_id, yangi_status, admin_izohi)


def get_murojaat_by_id(murojaat_id):
    """Murojaat_ID bo'yicha murojaat ma'lumotlarini olish."""
    return database.get_murojaat_by_id(murojaat_id)


# ==============================================================================
# 5. XAVFSIZLIK: SHAXSIY MA'LUMOTLARNI REGEX BILAN TOZALASH VA HTML FORMATLASH
# ==============================================================================
def tozalash_regex(matn: str) -> str:
    """
    Gemini AI ga yuborishdan oldin matndagi Pasport, JShShIR, Plastik karta
    va Telefon raqamlarni avtomatik yashiradi.
    """
    if not matn:
        return ""
    # 16 xonali plastik karta raqamlari (8600, 9860, 4000, 5614 va b.)
    matn = re.sub(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b", "[KARTA YASHIRILDI]", matn)
    # 14 xonali JSHSHIR (PINFL)
    matn = re.sub(r"\b(?:\d[\s\-]*){14}\b", "[JSHSHIR YASHIRILDI]", matn)
    # Pasport seriyasi va raqami (Masalan: AA 1234567, AD1234567, KA 1234567)
    matn = re.sub(r"(?i)\b[a-zа-яё]{2}\s*\d{7}\b", "[PASPORT YASHIRILDI]", matn)
    # Telefon raqamlar (+998901234567, 90 123 45 67 va b.)
    matn = re.sub(
        r"(?:\+?998[\s\-]?)?(?:\(?\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2})\b",
        "[TELEFON YASHIRILDI]",
        matn,
    )
    return matn


def markdown_to_telegram_html(text: str) -> str:
    """
    Markdown (headers, bold, italic, bullet points, horizontal dividers)
    belgilarini xavfsiz va chiroyli Telegram HTML formatiga o'tkazadi.
    Barcha xom '**', '#', '---' belgilari to'liq tozalanishini kafolatlaydi.
    """
    if not text:
        return ""
    s = str(text)
    # 1. Gorizontal ajratgich chiziqlar (---, ___, ***)
    s = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "──────────────────────────", s, flags=re.MULTILINE)

    # 2. **bold** va __bold__
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)

    # 3. Sarlavhalar (#, ##, ###, ####)
    def _header_sub(m):
        hashes = m.group(1)
        title = m.group(2).strip()
        title = re.sub(r"^<b>(.*?)</b>$", r"\1", title)
        if len(hashes) <= 2:
            return f"\n📌 <b>{title}</b>\n"
        elif len(hashes) == 3:
            return f"\n🔹 <b>{title}</b>\n"
        else:
            return f"\n▫️ <b>{title}</b>\n"

    s = re.sub(r"^[ \t]*(#{1,6})[ \t]+(.*?)$", _header_sub, s, flags=re.MULTILINE)

    # 4. Ro'yxat punktlari (* punkt yoki - punkt)
    s = re.sub(r"^[ \t]*[\*\-][ \t]+", "• ", s, flags=re.MULTILINE)

    # 5. Italic (*kursiv* yoki _kursiv_)
    s = re.sub(r"(?<!\w)\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", s)
    s = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", s)

    # 6. `kod` -> <code>kod</code>
    s = re.sub(r"`(.*?)`", r"<code>\1</code>", s)

    # 7. Qolib ketgan xom belgilarni tozalash
    s = s.replace("<b><b>", "<b>").replace("</b></b>", "</b>")
    s = s.replace("**", "")
    s = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", s, flags=re.MULTILINE)

    # 8. Ortiqcha bo'sh qatorlarni qisqartirish
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return latin_to_cyrillic_uz(s)


def sanitize_telegram_html(text: str) -> str:
    """
    Matndagi ruxsat etilgan Telegram HTML teglarini (<b>, <i>, <u>, <s>, <code>, <pre>,
    <blockquote>, <blockquote expandable="">) saqlab qolgan holda boshqa barcha < va > belgilarini xavfsiz kodlaydi.
    """
    if not text:
        return ""
    allowed_pattern = re.compile(
        r"(</?(?:b|strong|i|em|u|ins|s|strike|del|code|pre|blockquote)(?:\s+expandable)?\s*>)",
        flags=re.IGNORECASE,
    )
    parts = allowed_pattern.split(text)
    out = []
    for p in parts:
        if allowed_pattern.fullmatch(p):
            out.append(p)
        else:
            clean_p = p.replace("&#x27;", "'").replace("&#39;", "'").replace("&apos;", "'").replace("&quot;", '"')
            out.append(clean_p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(out)


def parse_ai_output(raw_text: str, user_question: str = ""):
    turi = "QONUNIY_MASLAHAT"
    muhimlik = "ODDIY"

    turi_match = re.search(r"\[(?:TURI|ТУРИ):\s*([A-Za-zА-Яа-яЎўҚқҒғҲҳ_]+)\]", raw_text, re.IGNORECASE)
    if turi_match:
        matched_val = turi_match.group(1).strip().upper()
        if any(k in matched_val for k in ["ШАХСИЙ", "SHAXSIY"]):
            turi = "SHAXSIY_MUROJAAT"
        else:
            turi = "QONUNIY_MASLAHAT"

    muhim_match = re.search(r"\[(?:MUHIMLIK|МУҲИМЛИК):\s*([A-Za-zА-Яа-яЎўҚқҒғҲҳ_]+)\]", raw_text, re.IGNORECASE)
    if muhim_match:
        matched_muhim = muhim_match.group(1).strip().upper()
        if any(k in matched_muhim for k in ["ШОШИЛИНЧ", "SHOSHILINCH"]):
            muhimlik = "SHOSHILINCH"
        else:
            muhimlik = "ODDIY"

    # Keraksiz sarlavhalar va qoliplarni butunlay tozalash
    clean_text = re.sub(r"\[(?:TURI|ТУРИ):[^\]]+\]", "", raw_text, flags=re.IGNORECASE)
    clean_text = re.sub(r"\[(?:MUHIMLIK|МУҲИМЛИК):[^\]]+\]", "", clean_text, flags=re.IGNORECASE)
    # Gorizontal ajratgich chiziqlarni (---, ──────────────────────────, === va h.k.) tozalash
    clean_text = re.sub(r"^[ \t]*[-─—=━*]{3,}[ \t]*\n?", "", clean_text.strip(), flags=re.MULTILINE).strip()
    clean_text = re.sub(r"^[ \t]*[-─—=━*]{3,}[ \t]*\n?", "", clean_text, flags=re.MULTILINE).strip()

    # Markdown (**) belgilarni HTML (<b>) ga o'girish va xavfsiz HTML qilish
    clean_text = markdown_to_telegram_html(clean_text)
    clean_text = sanitize_telegram_html(clean_text)

    q_lower = (user_question or "").lower()
    shaxsiy_kalitlar = [
        "qachon tushadi", "pulim tushmadi", "arizam nima bo'ldi", "arizam holati",
        "rad etildi", "chiqmadimi", "ijtimoiy xodim", "bog'lab bering", "shikoyat",
        "uyimga kelib", "когда поступит", "моя заявка", "соцработник",
    ]
    shoshilinch_kalitlar = [
        "og'ir kasal", "operatsiya", "shoshilinch", "nonimiz yo'q", "och qoldik",
        "yordam bering", "yotib qolgan", "zo'ravonlik", "qarovsiz", "reanimatsiya", "срочно",
    ]

    if any(k in q_lower for k in shaxsiy_kalitlar):
        turi = "SHAXSIY_MUROJAAT"
    if any(k in q_lower for k in shoshilinch_kalitlar):
        muhimlik = "SHOSHILINCH"

    return turi, muhimlik, clean_text


def get_analysis_progress_message(question: str, user_id: int) -> str:
    """
    Fuqaro savol berganda, tahlil jarayoni ketayotganini ko'rsatuvchi interaktiv,
    empatiyaga ega va mavzuga mos oraliq xabar matni.
    """
    lang = get_user_lang(user_id)
    q_lower = (question or "").lower()

    # 1. Mehnat va ish munosabatlari
    if any(k in q_lower for k in ["ish", "mehnat", "oylik", "maosh", "ish haqi", "ishdan bo'shat", "ta'til", "труд", "работа", "зарплат", "увольнен"]):
        if lang == "uz_cyr":
            return (
                "⏳ <b>Саволингизни қабул қилдим.</b>\n"
                "Ҳозир ҳолатингизни аниқ таҳлил қилиб, мутахассислар фикрини ҳам олиб, жавобни шу ерга ёзаман. Тайёр бўлиши билан юбораман, бироз кутинг.\n\n"
                "🔍 <i>Савол бўйича Меҳнат кодексининг тегишли моддалари ва қонунчилик меъёрларини текшираяпман, қисқа вақтда аниқ жавоб ёзаман...</i>"
            )
        elif lang == "ru":
            return (
                "⏳ <b>Ваш вопрос принят.</b>\n"
                "Сейчас провожу детальный анализ ситуации с учётом мнения специалистов. Ответ направлю сюда, пожалуйста, подождите.\n\n"
                "🔍 <i>Проверяю соответствующие статьи Трудового кодекса и нормативные акты...</i>"
            )
        else:
            return (
                "⏳ <b>Savolingizni qabul qildim.</b>\n"
                "Hozir holatingizni aniq tahlil qilib, mutaxassislar fikrini ham olib, javobni shu yerga yozaman. Tayyor bo'lishi bilan yuboraman, biroz kuting.\n\n"
                "🔍 <i>Savol bo'yicha Mehnat kodeksining tegishli moddalari va qonunchilik me'yorlarini tekshiryapman, qisqa vaqtda aniq javob yozaman...</i>"
            )

    # 2. Bola puli / Nafaqa / Ijtimoiy reestr / Moddiy yordam
    elif any(k in q_lower for k in ["bola puli", "nafaqa", "moddiy yordam", "reestr", "reyestr", "kambag'al", "kam ta'min", "пособи", "реестр", "материал"]):
        if lang == "uz_cyr":
            return (
                "⏳ <b>Саволингизни қабул қилдим.</b>\n"
                "Ҳозир ҳолатингизни аниқ таҳлил қилиб, мутахассислар фикрини ҳам олиб, жавобни шу ерга ёзаман. Тайёр бўлиши билан юбораман, бироз кутинг.\n\n"
                "🔍 <i>Савол бўйича «Ижтимоий реестр» тизими ва Вазирлар Маҳкамасининг 654-сон ҳамда 62-сон қарорлари мезонларини текшираяпман...</i>"
            )
        elif lang == "ru":
            return (
                "⏳ <b>Ваш вопрос принят.</b>\n"
                "Сейчас провожу детальный анализ ситуации с учётом мнения специалистов. Ответ направлю сюда, подождите немного.\n\n"
                "🔍 <i>Анализирую критерии «Единого социального реестра» и постановлений Кабинета Министров № 654 и № 62...</i>"
            )
        else:
            return (
                "⏳ <b>Savolingizni qabul qildim.</b>\n"
                "Hozir holatingizni aniq tahlil qilib, mutaxassislar fikrini ham olib, javobni shu yerga yozaman. Tayyor bo'lishi bilan yuboraman, biroz kuting.\n\n"
                "🔍 <i>Savol bo'yicha «Ijtimoiy reestr» tizimi va Vazirlar Mahkamasining 654-son hamda 62-son qarorlari mezonlarini tekshiryapman...</i>"
            )

    # 3. Nogironlik / TBB / TIB / Aravacha / Reabilitatsiya
    elif any(k in q_lower for k in ["nogiron", "tbb", "tib", "aravacha", "protez", "vaucher", "operatsiya", "davolanish", "инвалид", "коляск"]):
        if lang == "uz_cyr":
            return (
                "⏳ <b>Саволингизни қабул қилдим.</b>\n"
                "Ҳозир ҳолатингизни аниқ таҳлил қилиб, мутахассислар фикрини ҳам олиб, жавобни шу ерга ёзаман. Тайёр бўлиши билан юбораман, бироз кутинг.\n\n"
                "🔍 <i>Савол бўйича ТББ/ТИБ хулосалари, ногиронлик нафақаси ва бепул реабилитация воситаларини (ваучер) бериш тартибини текшираяпман...</i>"
            )
        elif lang == "ru":
            return (
                "⏳ <b>Ваш вопрос принят.</b>\n"
                "Сейчас провожу анализ ситуации и согласование с нормативными актами. Ответ будет отправлен сюда, подождите немного.\n\n"
                "🔍 <i>Проверяю регламент врачебно-экспертной комиссии (ВЭК/ТББ) и выдачи бесплатных средств реабилитации (ваучер)...</i>"
            )
        else:
            return (
                "⏳ <b>Savolingizni qabul qildim.</b>\n"
                "Hozir holatingizni aniq tahlil qilib, mutaxassislar fikrini ham olib, javobni shu yerga yozaman. Tayyor bo'lishi bilan yuboraman, biroz kuting.\n\n"
                "🔍 <i>Savol bo'yicha TBB/TIB xulosalari, nogironlik nafaqasi va bepul reabilitatsiya vositalarini (vaucher) berish tartibini tekshiryapman...</i>"
            )

    # 4. Himoya orderi / Tazyiq / Zo'ravonlik / Aliment
    elif any(k in q_lower for k in ["himoya orderi", "tazyiq", "zo'ravonlik", "kaltak", "urdi", "aliment", "ajrim", "насили", "охранн", "алимент"]):
        if lang == "uz_cyr":
            return (
                "⏳ <b>Саволингизни қабул қилдим.</b>\n"
                "Ҳозир ҳолатингизни аниқ таҳлил қилиб, мутахассислар фикрини ҳам олиб, жавобни шу ерга ёзаман. Тайёр бўлиши билан юбораман, бироз кутинг.\n\n"
                "🔍 <i>Ҳолат бўйича зудлик билан кўриладиган чоралар (Ҳимоя ордери) ва МИБ орқали алимент ундириш тартибини таҳлил қилмоқдаман...</i>"
            )
        elif lang == "ru":
            return (
                "⏳ <b>Ваш вопрос принят.</b>\n"
                "Сейчас провожу срочный анализ вашей ситуации. Ответ будет предоставлен незамедлительно, пожалуйста, подождите.\n\n"
                "🔍 <i>Анализирую меры срочной правовой защиты (Охранный ордер) и порядок взыскания алиментов через БПИ...</i>"
            )
        else:
            return (
                "⏳ <b>Savolingizni qabul qildim.</b>\n"
                "Hozir holatingizni aniq tahlil qilib, mutaxassislar fikrini ham olib, javobni shu yerga yozaman. Tayyor bo'lishi bilan yuboraman, biroz kuting.\n\n"
                "🔍 <i>Holat bo'yicha zudlik bilan ko'riladigan choralar (Himoya orderi) va MIB orqali aliment undirish tartibini tahlil qilmoqdaman...</i>"
            )

    # 5. Umumiy holat (General)
    else:
        if lang == "uz_cyr":
            return (
                "⏳ <b>Саволингизни қабул қилдим.</b>\n"
                "Ҳозир ҳолатингизни аниқ таҳлил қилиб, мутахассислар фикрини ҳам олиб, жавобни шу ерга ёзаман. Тайёр бўлиши билан юбораман, бироз кутинг.\n\n"
                "🔍 <i>Савол бўйича қонунчилик ҳужжатлари ва норматив базани текшираяпман, қисқа вақтда аниқ жавоб ёзаман...</i>"
            )
        elif lang == "ru":
            return (
                "⏳ <b>Ваш вопрос принят.</b>\n"
                "Сейчас подробно анализирую вашу ситуацию с учётом законодательства и мнения специалистов. Ответ подготовлю в ближайшее время, подождите немного.\n\n"
                "🔍 <i>Проверяю нормативно-правовую базу и стандарты социальной защиты...</i>"
            )
        else:
            return (
                "⏳ <b>Savolingizni qabul qildim.</b>\n"
                "Hozir holatingizni aniq tahlil qilib, mutaxassislar fikrini ham olib, javobni shu yerga yozaman. Tayyor bo'lishi bilan yuboraman, biroz kuting.\n\n"
                "🔍 <i>Savol bo'yicha qonunchilik hujjatlari va normativ bazani tekshiryapman, qisqa vaqtda aniq javob yozaman...</i>"
            )


# ==============================================================================
# 5-A. TELEGRAM XABAR CHEGARASI (4096 BELGI) UCHUN SMART CHUNKER VA SPLITTER
# ==============================================================================
def split_text_smart(text: str, max_len: int = 3600) -> list:
    """
    Uzun matnni Telegram xabar chegarasiga (4096 belgi) moslab mantiqiy qismlarga
    (paragraflar, qatorlar, jumlalar) xavfsiz bo'lib beradi.
    """
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_len:
        split_pos = -1
        # 1. Ikki qator tashlash (\n\n) - Paragraflar bo'yicha
        p_pos = remaining.rfind("\n\n", 0, max_len)
        if p_pos != -1 and p_pos >= max_len // 3:
            split_pos = p_pos + 2
        else:
            # 2. Bitta qator tashlash (\n)
            n_pos = remaining.rfind("\n", 0, max_len)
            if n_pos != -1 and n_pos >= max_len // 3:
                split_pos = n_pos + 1
            else:
                # 3. Gap oxiri (. ! ?)
                for punct in (". ", "! ", "? "):
                    s_pos = remaining.rfind(punct, 0, max_len)
                    if s_pos != -1 and s_pos >= max_len // 3:
                        split_pos = s_pos + len(punct)
                        break
                if split_pos == -1:
                    # 4. Bo'sh joy (probel)
                    sp_pos = remaining.rfind(" ", 0, max_len)
                    if sp_pos != -1 and sp_pos >= max_len // 3:
                        split_pos = sp_pos + 1
                    else:
                        # 5. Qat'iy chegara
                        split_pos = max_len

        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def balance_html_tags(chunk: str, open_tags: list = None) -> tuple:
    """
    Telegram HTML teglarini chunk ichida to'g'ri yopish va keyingi chunk uchun
    ochiq qolgan teglarni xavfsiz uzatish.
    """
    prefix = "".join(open_tags) if open_tags else ""
    full_chunk = prefix + chunk

    tag_regex = re.compile(r"<\s*(/)?\s*([a-zA-Z0-9]+)([^>]*)>")
    stack = []

    for m in tag_regex.finditer(full_chunk):
        is_closing = bool(m.group(1))
        tag_name = m.group(2).lower()
        full_tag = m.group(0)

        if full_tag.endswith("/>"):
            continue

        if not is_closing:
            stack.append((tag_name, full_tag))
        else:
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx][0] == tag_name:
                    stack.pop(idx)
                    break

    closing_suffix = "".join(f"</{tag_name}>" for tag_name, _ in reversed(stack))
    next_tags = [full_tag for _, full_tag in stack]
    return full_chunk + closing_suffix, next_tags


def send_split_message(
    chat_id,
    text: str,
    reply_to_message_id=None,
    reply_markup=None,
    parse_mode="HTML",
    max_chunk_len: int = 3600,
):
    """
    Uzun xabarlarni Telegram API chegarasidan (4096 belgi) oshib ketmasdan,
    xavfsiz va chiroyli tarzda bo'lib ketma-ket yuboruvchi asosiy funksiya.
    """
    if not text:
        return None

    raw_chunks = split_text_smart(text, max_len=max_chunk_len)
    if not raw_chunks:
        return None

    last_idx = len(raw_chunks) - 1
    sent_messages = []
    carried_tags = []

    for idx, raw_chunk in enumerate(raw_chunks):
        is_first = (idx == 0)
        is_last = (idx == last_idx)
        current_markup = reply_markup if is_last else None
        current_reply_to = reply_to_message_id if is_first else None

        if parse_mode == "HTML":
            chunk_text, carried_tags = balance_html_tags(raw_chunk, carried_tags)
        else:
            chunk_text = raw_chunk

        # 1-urinish: HTML formatda yuborish
        msg = None
        try:
            msg = bot.send_message(
                chat_id,
                chunk_text,
                reply_to_message_id=current_reply_to,
                reply_markup=current_markup,
                parse_mode=parse_mode,
                allow_sending_without_reply=True,
            )
        except Exception:
            # HTML parse yoki format xatoligi yuz bersa, teglarni tozalab matn ko'rinishida yuborish
            plain_chunk = re.sub(r"<[^>]+>", "", chunk_text)
            try:
                msg = bot.send_message(
                    chat_id,
                    plain_chunk,
                    reply_to_message_id=current_reply_to,
                    reply_markup=current_markup,
                    allow_sending_without_reply=True,
                )
            except Exception:
                try:
                    msg = bot.send_message(
                        chat_id,
                        plain_chunk,
                        reply_markup=current_markup,
                    )
                except Exception as final_e:
                    print(f"Xabarni yuborishda yakuniy xatolik (chunk {idx}): {final_e}")

        if msg:
            sent_messages.append(msg)

        if not is_last:
            time.sleep(0.3)

    return sent_messages[0] if sent_messages else None


# ==============================================================================
# 6. KLAVIATURALAR (FOYDALANUVCHI VA ADMIN PANEL MENYULARI)
# ==============================================================================
def get_user_main_menu(user_id=None):
    lang = get_user_lang(user_id) if user_id else "uz_cyr"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    if lang == "ru":
        markup.add(
            types.KeyboardButton("📝 Задать вопрос / Обращение"),
            types.KeyboardButton("🔍 Статус обращения"),
            types.KeyboardButton("👨‍💼 Связь с соцработником"),
            types.KeyboardButton("🔤 Til / Язык"),
        )
    else:
        markup.add(
            types.KeyboardButton("📝 Савол йўллаш / Мурожаат қилиш"),
            types.KeyboardButton("🔍 Мурожаатим ҳолати"),
            types.KeyboardButton("👨‍💼 Ижтимоий ходим билан боғланиш"),
            types.KeyboardButton("🔤 Til / Язык"),
        )
    return markup


def get_admin_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("⚙️ Бошқарув панели"),
        types.KeyboardButton("🧠 AI Ёрдамчи"),
        types.KeyboardButton("⚙️ Тизим созламалари"),
        types.KeyboardButton("📊 Статистика"),
        types.KeyboardButton("🔍 Фуқарони қидириш"),
        types.KeyboardButton("📥 Excel базани юклаш"),
        types.KeyboardButton("📱 Мини Аппни очиш"),
    )
    return markup


def get_faq_inline_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👶 Bola puli uchun qanday hujjatlar kerak?", callback_data="faq_bola_puli"),
        types.InlineKeyboardButton("🤝 Moddiy yordam kimlarga beriladi?", callback_data="faq_moddiy_yordam"),
        types.InlineKeyboardButton("♿ Nogironlik va reabilitatsiya vositalari", callback_data="faq_nogironlik"),
        types.InlineKeyboardButton("📜 Yangi qonunchilik ma'lumotlari", callback_data="faq_qonunchilik"),
    )
    return markup


def get_admin_panel_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🧠 AI Ёрдамчи (Муаммо ечими)", callback_data="adm_ai_consultant"),
        types.InlineKeyboardButton("📚 Ижтимоий AI билимлари", callback_data="adm_social_kb_menu"),
        types.InlineKeyboardButton("⚙️ Тизим ва Сервер созламалари", callback_data="adm_settings_menu"),
        types.InlineKeyboardButton("📊 Сервер мониторинги (/status)", callback_data="adm_server_status"),
        types.InlineKeyboardButton("📜 Тизим логлари (/logs)", callback_data="adm_system_logs"),
        types.InlineKeyboardButton("📊 Умумий статистика ва ҳолат", callback_data="adm_stats"),
        types.InlineKeyboardButton("🔍 Фуқарони базадан тезкор қидириш (/qidiruv)", callback_data="adm_search_user"),
        types.InlineKeyboardButton("🚨 Кутаётган ва шошилинч мурожаатлар", callback_data="adm_pending"),
        types.InlineKeyboardButton("⏰ Муддати ўтаётган мурожаатлар (24+ соат)", callback_data="adm_overdue"),
        types.InlineKeyboardButton("📢 Оммавий хабарнома (Рассилка — Барчага)", callback_data="adm_broadcast_all"),
        types.InlineKeyboardButton("🏘 Ҳудуд/Кўча бўйича Рассилка", callback_data="adm_broadcast_area"),
        types.InlineKeyboardButton("📈 Жорий ой AI ҳисоботи (/xisobot)", callback_data="adm_ai_report_now"),
        types.InlineKeyboardButton("📥 Excel базаларни юклаб олиш", callback_data="adm_download_excel"),
    )
    return markup


def is_admin(user_id) -> bool:
    return str(user_id) == str(ADMIN_ID)


# Ijtimoiy xodim AI-konsultanti va Maxsus AI Bilimlar bazasi routerini ulash
admin_ai_assistant.register_admin_ai_handlers(bot, is_admin, get_admin_panel_menu, admin_state)


# ==============================================================================
# 6-B. XAVFSIZLIK: ANTI-SPAM (RATE LIMITER) VA QADAMLARNI BEKOR QILISH YORDAMCHILARI
# ==============================================================================
USER_RATE_LIMIT = {}  # {user_id: [timestamp1, timestamp2, ...]}


def is_rate_limited(user_id: int, max_requests: int = 3, window_seconds: int = 60) -> tuple:
    """
    Foydalanuvchi limitdan oshganligini tekshiradi (is_limited, qolgan_kutish_soniyasi).
    Admin (A. Jo'rayev) uchun hech qanday cheklov qo'llanilmaydi.
    """
    if is_admin(user_id):
        return False, 0
    now = time.time()
    history = USER_RATE_LIMIT.get(user_id, [])
    history = [t for t in history if now - t < window_seconds]
    USER_RATE_LIMIT[user_id] = history
    if len(history) >= max_requests:
        wait_time = int(window_seconds - (now - history[0])) + 1
        return True, max(1, wait_time)
    history.append(now)
    USER_RATE_LIMIT[user_id] = history
    return False, 0


def is_cancel_message(message) -> bool:
    """Foydalanuvchi jarayonni bekor qilish tugmasi yoki buyrug'ini yuborganini tekshirish."""
    txt = (getattr(message, "text", "") or "").strip().lower()
    return txt in [
        "🔙 бекор қилиш",
        "бекор қилиш",
        "🔙 bekor qiliş",
        "🔙 bekor qilish",
        "🔙 asosiy menyu",
        "bekor qiliş",
        "bekor qilish",
        "/cancel",
        "/start",
        "отмена",
        "главное меню",
        "❌ bekor qiliş",
        "❌ bekor qilish",
        "❌ бекор қилиш",
    ]


def get_cancel_reply_keyboard():
    """Qadamli jarayonlar uchun qulay bekor qilish tugmasi."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Бекор қилиш"))
    return markup


# ==============================================================================
# 7. IKKI BOSQICHLI TIZIM (OCHIQ KIRISH), SODDALASHTIRILGAN TASDIQLASH VA MAXFIYLIK
# ==============================================================================
@bot.message_handler(commands=["start"])
def send_welcome(message):
    """
    1-bosqich: Ochiq kirish — barcha fuqarolar uchun darhol ochiq.
    Admin (/start) bosganda to'liq Boshqaruv Tizimi (Admin Paneli) to'liq ochiladi.
    """
    user_id = message.from_user.id

    # AGAR ADMIN /start BOSSA — TO'LIQ BOSHQARUV TIZIMI VA ADMIN PANELINI CHIQARISH!
    if is_admin(user_id):
        if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
            try:
                tma_admin_url = f"{WEB_APP_URL}?user_id={user_id}&lang=uz_cyr"
                bot.set_chat_menu_button(
                    message.chat.id,
                    types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=tma_admin_url))
                )
            except Exception:
                pass

        admin_text = (
            "👨‍💻 <b>ШАЙХ-АЛИ МФЙ ИЖТИМОИЙ ХОДИМИ — ТЎЛИҚ АДМИН БОШҚАРУВ ТИЗИМИ</b>\n\n"
            "🏛 <b>Ҳурматли А. Жўраев</b>, тизимга хуш келибсиз!\n"
            "Қуйидаги бошқарув панели орқали барча бўлимлардан тўлиқ фойдаланишингиз мумкин:\n\n"
            "• 🧠 <b>AI Ёрдамчи (Муаммо ечими):</b> Ижтимоий хизматлар ва далолатнома генератори\n"
            "• 📚 <b>Ижтимоий AI билимлари:</b> Ҳуқуқий база (RAG ombori)\n"
            "• ⚙️ <b>Тизим созламалари:</b> МИҲ ва қабул графиги (<code>/sozlamalar</code>)\n"
            "• 🔍 <b>Фуқарони қидириш:</b> <code>/qidiruv Исм ёки Кўча</code>\n"
            "• 📈 <b>AI таҳлилий ҳисобот:</b> <code>/xisobot 10-2026</code>"
        )
        bot.send_message(
            message.chat.id,
            admin_text,
            reply_markup=get_admin_panel_menu(),
            parse_mode="HTML",
        )
        bot.send_message(
            message.chat.id,
            "👇 <b>Администратор бошқарув тугмалари:</b>",
            reply_markup=get_admin_reply_keyboard(),
            parse_mode="HTML",
        )
        return

    # ODDIY FUQARO UCHUN SALOMLASHISH VA MINI APP TUGMASI
    citizen = get_citizen_by_tg_id(user_id)
    raw_name = citizen.get("FIO") if citizen else (message.from_user.first_name or "Ҳурматли фуқаро")
    name_clean = latin_to_cyrillic_uz(str(raw_name).replace("&#x27;", "'"))
    name_clean = name_clean.replace("Жораев", "Жўраев").replace("Жо'раев", "Жўраев").replace("Жо&#x27;раев", "Жўраев")

    welcome_text = (
        f"Ассалому алайкум, <b>{esc(name_clean)}</b>!\n\n"
        "🏛 <b>Қарши шаҳар «Шайх-Али» МФЙ Ижтимоий ходими (А. Жўраев)</b> расмий ақлли ассистент ботига хуш келибсиз.\n\n"
        "📱 <b>Телеграм Мини Апп (TMA):</b>\n"
        "Барча хизматларимиз, жумладан 🧮 <b>Нафақа калькулятори</b>, 📅 <b>Қабулга онлайн ёзилиш</b>, 📍 <b>Манзиллар</b> ва 📋 <b>Тезкор саволлар</b> замонавий дастур кўринишида тўлиқ Мини Апп га жойлаштирилди!\n\n"
        "📌 <b>Бот орқали қуйидаги хизматлардан бепул фойдаланишингиз мумкин:</b>\n"
        "• 🤖 <b>AI Ҳуқуқий маслаҳат</b> — саволингизни ёзинг, расмий норматив ҳужжатлар асосида жавоб олинг;\n"
        "• 👨‍💼 <b>Ижтимоий ходимга расмий мурожаат</b> йўллаш;\n"
        "• 🔍 <b>Мурожаатим ҳолати</b>ни кузатиш;\n"
        "• 📱 <b>Мини Апп</b> хизматларидан қулай фойдаланиш.\n\n"
        "<i>Керакли хизматни танлаш учун пастдаги менюдан фойдаланинг ёки Мини Аппни очинг:</i>"
    )

    inline_markup = types.InlineKeyboardMarkup()
    if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
        u_lang = get_user_lang(user_id)
        tma_user_url = f"{WEB_APP_URL}?user_id={user_id}&lang={u_lang}" if ("?" not in WEB_APP_URL) else f"{WEB_APP_URL}&user_id={user_id}&lang={u_lang}"
        inline_markup.add(types.InlineKeyboardButton("📱 Мини Аппни очиш (TMA)", web_app=types.WebAppInfo(url=tma_user_url)))
        try:
            bot.set_chat_menu_button(
                message.chat.id,
                types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=tma_user_url))
            )
        except Exception:
            pass

    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=inline_markup,
        parse_mode="HTML",
    )
    bot.send_message(
        message.chat.id,
        localize_text(user_id, "👇 Асосий хизматлар менюси:", "👇 Главное меню:"),
        reply_markup=get_user_main_menu(user_id),
    )


def prompt_citizen_verification(chat_id, user_id, reason="murojaat"):
    """
    Ikki bosqichli tizim: Fuqaro faqat ijtimoiy xodimga rasmiy murojaat yo'llamoqchi
    yoki qabulga yozilmoqchi bo'lgandagina shaxsni tasdiqlash so'raladi.
    Hech qanday rasm yoki video so'ralmaydi (O'RQ-547 minimallashtirish tamoyili).
    """
    citizen = get_citizen_by_tg_id(user_id)
    if citizen and citizen.get("Status") == "Kutmoqda":
        bot.send_message(
            chat_id,
            "⏳ <b>Hurmatli fuqaro!</b>\n\n"
            "Sizning shaxsingizni tasdiqlash arizangiz Shayxali MFY ijtimoiy xodimi (Admin) ko'rib chiqish jarayonida.\n"
            "Admin tekshirib tasdiqlashi bilan sizga xabar beriladi va barcha xizmatlar to'liq ochiladi.",
            parse_mode="HTML",
            reply_markup=get_user_main_menu(user_id),
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📝 Shaxsni tasdiqlash (4 ta oddiy qadam)", callback_data="start_fast_verify"),
        types.InlineKeyboardButton("🔙 Asosiy menyu", callback_data="cancel_verify"),
    )

    sabab_text = "ijtimoiy xodimga rasmiy murojaat yo'llash" if reason == "murojaat" else "qabulga onlayn yozilish"

    prompt_text = (
        f"ℹ️ <b>Hurmatli fuqaro!</b>\n\n"
        f"Shayxali MFY {sabab_text} uchun shaxsingizni tasdiqlashingiz lozim.\n\n"
        "🔒 <b>Jarayon juda tez va sodda (atigi 4 ta ma'lumot):</b>\n"
        "1️⃣ To'liq ism-sharifingiz (F.I.Sh.)\n"
        "2️⃣ Telefon raqamingiz (tugma orqali ulashish yoki yozish)\n"
        "3️⃣ Pasport seriya-raqami yoki 14 xonali JShShIR\n"
        "4️⃣ Shayxali MFY dagi yashash manzilingiz (ko'cha va uy)\n\n"
        "🛡 <i>O'zbekiston Respublikasi O'RQ-547 Qonuni talablariga ko'ra, sizdan xonadon rasmi yoki video TALAB ETILMAYDI. Barcha ma'lumotlaringiz maxfiy va xavfsiz saqlanadi.</i>"
    )
    bot.send_message(
        chat_id,
        localize_text(user_id, prompt_text),
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data in ["start_fast_verify", "rozi_boldi"])
def handle_fast_verify_start(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    safe_delete_message(chat_id, call.message.message_id)

    user_data[user_id] = {
        "status": "verifying_fio",
        "last_bot_msg_id": None,
    }

    cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "1️⃣ <b>To'liq ism-sharifingizni (F.I.Sh.) kiriting:</b>\n"
            "<i>(Masalan: Eshmatov Toshmat Aliyevich)</i>\n\n"
            "🔒 <i>Yuborgan ma'lumotingiz maxfiylik uchun chatdan avtomatik o'chiriladi.</i>",
            "1️⃣ <b>Введите ваше полное Ф.И.О.:</b>\n"
            "<i>(Например: Эшматов Тошмат Алиевич)</i>",
        ),
        reply_markup=cancel_markup,
        parse_mode="HTML",
    )
    user_data[user_id]["last_bot_msg_id"] = msg.message_id
    bot.register_next_step_handler(msg, process_fast_fio_step)


@bot.callback_query_handler(func=lambda call: call.data == "cancel_verify")
def handle_cancel_verify(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    safe_delete_message(chat_id, call.message.message_id)
    user_data.pop(user_id, None)
    bot.send_message(
        chat_id,
        localize_text(user_id, "❌ Tasdiqlash bekor qilindi.", "❌ Подтверждение отменено."),
        reply_markup=get_user_main_menu(user_id),
    )


def process_fast_fio_step(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if is_cancel_message(message):
        user_data.pop(user_id, None)
        bot.send_message(chat_id, "❌ Tasdiqlash bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return

    text = (message.text or "").strip()
    safe_delete_message(chat_id, message.message_id)
    old_bot_msg = user_data.get(user_id, {}).get("last_bot_msg_id")
    safe_delete_message(chat_id, old_bot_msg)

    cleaned_fio = re.sub(r"[^a-zA-Zа-яА-ЯёЁўЎғҒқҚҳҲ\s']", "", text)
    if len(cleaned_fio.split()) < 2:
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ Iltimos, ism va familiyangizni to'liq kiriting (kamida 2 ta so'z, masalan: <code>Karimov Sardor</code>):",
            reply_markup=cancel_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_fio_step)
        return

    user_data.setdefault(user_id, {})["fio"] = cleaned_fio
    user_data[user_id]["status"] = "verifying_phone"

    phone_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    phone_markup.add(types.KeyboardButton("📲 Telefon raqamni ulashish", request_contact=True))
    phone_markup.add(types.KeyboardButton("🔙 Bekor qilish"))

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "2️⃣ <b>Telefon raqamingizni yuboring:</b>\n\n"
            "Pastdagi <b>«📲 Telefon raqamni ulashish»</b> tugmasini bosing yoki raqamingizni qo'lda yozing (Masalan: <code>+998901234567</code>):",
            "2️⃣ <b>Отправьте ваш номер телефона:</b>\n\n"
            "Нажмите <b>«📲 Telefon raqamni ulashish»</b> или введите вручную:",
        ),
        reply_markup=phone_markup,
        parse_mode="HTML",
    )
    user_data[user_id]["last_bot_msg_id"] = msg.message_id
    bot.register_next_step_handler(msg, process_fast_phone_step)


def process_fast_phone_step(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if is_cancel_message(message):
        user_data.pop(user_id, None)
        bot.send_message(chat_id, "❌ Tasdiqlash bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return

    safe_delete_message(chat_id, message.message_id)
    old_bot_msg = user_data.get(user_id, {}).get("last_bot_msg_id")
    safe_delete_message(chat_id, old_bot_msg)

    phone_val = None
    if message.contact:
        phone_val = message.contact.phone_number
    elif message.text:
        phone_val = message.text.strip()

    digits = re.sub(r"\D", "", str(phone_val or ""))
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 12 and digits.startswith("998"):
        pass
    else:
        phone_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        phone_markup.add(types.KeyboardButton("📲 Telefon raqamni ulashish", request_contact=True))
        phone_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ Telefon raqami noto'g'ri kiritildi. Iltimos, pastdagi tugmani bosing yoki <code>+998901234567</code> formatida yozing:",
            reply_markup=phone_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_phone_step)
        return

    formatted_phone = f"+{digits}"
    is_dup, _ = check_duplicate_citizen(user_id, telefon=formatted_phone)
    if is_dup:
        phone_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        phone_markup.add(types.KeyboardButton("📲 Telefon raqamni ulashish", request_contact=True))
        phone_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ <b>Bu telefon raqam boshqa fuqaro tomonidan ro'yxatga olingan!</b>\nIltimos, o'zingizning shaxsiy raqamingizni kiriting:",
            reply_markup=phone_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_phone_step)
        return

    user_data.setdefault(user_id, {})["telefon"] = formatted_phone
    user_data[user_id]["status"] = "verifying_passport"

    cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "3️⃣ <b>Pasport seriya-raqamingiz yoki 14 xonali JShShIR raqamingizni kiriting:</b>\n\n"
            "<i>(Masalan: <code>AA1234567</code> yoki <code>31201901234567</code>)</i>\n\n"
            "🔒 <i>Bu ma'lumot chatdan darhol o'chiriladi va begonalarga ko'rsatilmaydi.</i>",
            "3️⃣ <b>Введите серию-номер паспорта или 14-значный ПИНФЛ:</b>\n"
            "<i>(Например: <code>AA1234567</code> или <code>31201901234567</code>)</i>",
        ),
        reply_markup=cancel_markup,
        parse_mode="HTML",
    )
    user_data[user_id]["last_bot_msg_id"] = msg.message_id
    bot.register_next_step_handler(msg, process_fast_doc_step)


def process_fast_doc_step(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if is_cancel_message(message):
        user_data.pop(user_id, None)
        bot.send_message(chat_id, "❌ Tasdiqlash bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return

    text = (message.text or "").strip()
    safe_delete_message(chat_id, message.message_id)
    old_bot_msg = user_data.get(user_id, {}).get("last_bot_msg_id")
    safe_delete_message(chat_id, old_bot_msg)

    pasport, jshshir = extract_passport_and_jshshir(text)
    if not pasport and not jshshir:
        cleaned_digits = re.sub(r"\D", "", text)
        if len(cleaned_digits) == 14:
            jshshir = cleaned_digits
        else:
            cleaned_upper = text.upper().translate(CYR_TO_LAT_PASSPORT)
            cleaned_doc = re.sub(r"[\s\-_]", "", cleaned_upper)
            if re.fullmatch(r"[A-Z]{2}\d{7}", cleaned_doc):
                pasport = cleaned_doc

    if not pasport and not jshshir:
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ Pasport yoki JShShIR formati noto'g'ri kiritildi.\n"
            "Iltimos, <code>AA1234567</code> yoki 14 xonali <code>31201901234567</code> shaklida kiriting:",
            reply_markup=cancel_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_doc_step)
        return

    is_dup, _ = check_duplicate_citizen(user_id, pasport=pasport, jshshir=jshshir)
    if is_dup:
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ <b>Ushbu Pasport/JShShIR bo'yicha fuqaro allaqachon ro'yxatdan o'tgan!</b>\nIltimos, o'zingizning haqiqiy ma'lumotingizni kiriting:",
            reply_markup=cancel_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_doc_step)
        return

    user_data.setdefault(user_id, {})["pasport"] = pasport or ""
    user_data[user_id]["jshshir"] = jshshir or ""
    user_data[user_id]["status"] = "verifying_address"

    cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "4️⃣ <b>Shayxali MFY dagi yashash manzilingizni (ko'cha va uy raqami) kiriting:</b>\n\n"
            "<i>(Masalan: <code>Navbahor ko'chasi, 15-uy</code> yoki <code>Shayxali 2-tor ko'cha, 4-uy</code>)</i>",
            "4️⃣ <b>Введите ваш адрес в МСГ «Шайхали» (улица и номер дома):</b>\n"
            "<i>(Например: <code>ул. Навбахор, дом 15</code>)</i>",
        ),
        reply_markup=cancel_markup,
        parse_mode="HTML",
    )
    user_data[user_id]["last_bot_msg_id"] = msg.message_id
    bot.register_next_step_handler(msg, process_fast_address_step)


def process_fast_address_step(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if is_cancel_message(message):
        user_data.pop(user_id, None)
        bot.send_message(chat_id, "❌ Tasdiqlash bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return

    text = (message.text or "").strip()
    safe_delete_message(chat_id, message.message_id)
    old_bot_msg = user_data.get(user_id, {}).get("last_bot_msg_id")
    safe_delete_message(chat_id, old_bot_msg)

    if len(text) < 4:
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Bekor qilish"))
        msg = bot.send_message(
            chat_id,
            "⚠️ Iltimos, ko'cha nomi va uy raqamingizni to'liqroq yozing (Masalan: <code>Navbahor ko'chasi, 12-uy</code>):",
            reply_markup=cancel_markup,
            parse_mode="HTML",
        )
        user_data.setdefault(user_id, {})["last_bot_msg_id"] = msg.message_id
        bot.register_next_step_handler(msg, process_fast_address_step)
        return

    u = user_data.get(user_id, {})
    fio = u.get("fio", "")
    telefon = u.get("telefon", "")
    pasport = u.get("pasport", "")
    jshshir = u.get("jshshir", "")
    kocha_manzil = text

    # SQLite bazaga saqlash va Excel bilan sinxronlash (Status: Kutmoqda — faqat admin tasdiqlasa o'tadi)
    save_or_update_citizen(
        user_id=user_id,
        fio=fio,
        telefon=telefon,
        pasport_seriya=pasport,
        jshshir=jshshir,
        kocha_manzil=kocha_manzil,
        geolokatsiya="",
        status="Kutmoqda",
    )

    user_data.pop(user_id, None)

    pending_msg = (
        "⏳ <b>Arizangiz qabul qilindi!</b>\n\n"
        f"👤 <b>F.I.Sh:</b> {esc(fio)}\n"
        f"📞 <b>Telefon:</b> {esc(telefon)}\n"
        f"🏘 <b>Manzil:</b> {esc(kocha_manzil)}\n\n"
        "📋 <i>Shaxsingizni tasdiqlash so'rovi Shayxali MFY ijtimoiy xodimi (Admin)ga yuborildi. "
        "Ijtimoiy xodim ma'lumotlaringizni tekshirib tasdiqlaganidan so'ng sizga bildirishnoma yuboriladi va profilingiz to'liq faollashadi.</i>"
    )
    bot.send_message(
        chat_id,
        localize_text(user_id, pending_msg),
        reply_markup=get_user_main_menu(user_id),
        parse_mode="HTML",
    )

    # Shayxali MFY ijtimoiy xodimiga tekshirish va tasdiqlash uchun inline tugmali bildirishnoma
    try:
        doc_info = f"{pasport} / {jshshir}".strip(" /")
        u_handle = f"@{message.from_user.username}" if message.from_user.username else "yo'q"
        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        admin_markup.add(
            types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"adm_appr_cit_{user_id}"),
            types.InlineKeyboardButton("❌ Rad etish", callback_data=f"adm_rejc_cit_{user_id}"),
        )
        admin_text = (
            "📋 <b>YANGI FUQARO IDENTIFIKATSIYA SO'ROVI:</b>\n\n"
            f"👤 <b>F.I.Sh:</b> {esc(fio)}\n"
            f"📞 <b>Telefon:</b> {esc(telefon)}\n"
            f"🛂 <b>Pasport/JShShIR:</b> {esc(doc_info or 'Kiritilmadi')}\n"
            f"🏘 <b>Ko'cha/Manzil:</b> {esc(kocha_manzil)}\n"
            f"🆔 <b>Telegram ID:</b> <code>{user_id}</code> ({u_handle})\n"
            f"⏳ <b>Holati:</b> Tasdiqlash kutilmoqda\n\n"
            "<i>Iltimos, ma'lumotlarni tekshiring va tasdiqlang:</i>"
        )
        bot.send_message(ADMIN_ID, admin_text, reply_markup=admin_markup, parse_mode="HTML")
    except Exception as e:
        print("Adminga identifikatsiya xabarnomasi yuborishda xatolik:", e)


@bot.message_handler(content_types=["document"])
def handle_admin_document_upload(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.reply_to(message, "⚠️ Hujjat yuklash faqat Shayxali MFY ijtimoiy xodimi (Admin) uchun ochiq.")
        return

    # Ijtimoiy AI bilimlari bazasiga hujjat yuklash tekshiruvi
    if admin_ai_assistant.handle_admin_ai_message(bot, message, admin_state, is_admin, get_admin_panel_menu):
        return

    doc = message.document
    fname = doc.file_name or "hujjat.pdf"
    ext = os.path.splitext(fname)[1].lower()

    ALLOWED_EXTS = [
        ".pdf", ".doc", ".docx", ".txt", ".text", ".rtf", ".md",
        ".xlsx", ".xls", ".csv",
        ".png", ".jpg", ".jpeg", ".webp"
    ]

    if ext not in ALLOWED_EXTS:
        bot.reply_to(
            message,
            "❌ <b>Qabul qilinadigan huquqiy hujjat formatlari:</b>\n\n"
            "📄 <b>Matnli hujjatlar:</b> PDF, DOC, DOCX, RTF, TXT\n"
            "📊 <b>Jadvallar va mezonlar:</b> XLSX, XLS, CSV\n"
            "📸 <b>Skaner va fotosuratlar:</b> JPG, PNG, WEBP\n\n"
            "<i>Iltimos, ushbu formatlardan birida yuboring.</i>",
            parse_mode="HTML",
        )
        return

    # Bilimlar bazasi fuqarolarga beriladigan javoblarda ishlatiladi: fuqaro hujjati adashib kirib ketmasligi uchun
    # "Hujjat yuklash" tugmasisiz yuborilgan fayl faqat tasdiqdan keyin qabul qilinadi
    if admin_state.get(user_id, {}).get("waiting_for") != "legal_document":
        admin_state[user_id] = {"pending_kb_doc": {"file_id": doc.file_id, "file_name": fname}}
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Базага қўшиш", callback_data="kbdoc_yes"),
            types.InlineKeyboardButton("❌ Бекор қилиш", callback_data="kbdoc_no"),
        )
        bot.reply_to(
            message,
            f"📄 <b>«{esc(fname)}»</b> ҳужжатини ҳуқуқий билимлар базасига қўшайми?\n\n"
            "⚠️ <i>База матни фуқароларга бериладиган AI жавобларида ишлатилади. "
            "Шахсий маълумотли ҳужжатни қўшманг.</i>",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return

    wait_m = bot.reply_to(
        message,
        f"⏳ <b>«{esc(fname)}»</b> qabul qilinmoqda va chuqur huquqiy tahlil o'tkazilmoqda...",
        parse_mode="HTML",
    )
    _ingest_legal_document(message.chat.id, wait_m.message_id, user_id, doc.file_id, fname)


@bot.callback_query_handler(func=lambda call: call.data in ("kbdoc_yes", "kbdoc_no"))
def handle_kb_document_confirmation(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!", show_alert=True)
        return
    bot.answer_callback_query(call.id)

    pending = admin_state.get(user_id, {}).pop("pending_kb_doc", None)
    if call.data == "kbdoc_no" or not pending:
        text = "❌ Ҳужжат базага қўшилмади." if call.data == "kbdoc_no" else "⚠️ Сўров эскирган. Ҳужжатни қайта юборинг."
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
        return

    bot.edit_message_text(
        f"⏳ <b>«{esc(pending['file_name'])}»</b> qabul qilinmoqda va chuqur huquqiy tahlil o'tkazilmoqda...",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML",
    )
    _ingest_legal_document(call.message.chat.id, call.message.message_id, user_id, pending["file_id"], pending["file_name"])


def _ingest_legal_document(chat_id, wait_message_id, user_id, file_id, fname):
    """Hujjatni yuklab oladi, huquqiy bilimlar bazasiga qo'shadi va qayta indekslaydi."""
    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        # Fayl nomi foydalanuvchidan keladi: papkadan tashqariga yozilmasligi uchun faqat oxirgi qismi olinadi
        fname = os.path.basename(fname.replace("\\", "/")) or "hujjat.pdf"
        dest_path = os.path.join(HUJJATLAR_DIR, fname)
        with open(dest_path, "wb") as f_out:
            f_out.write(downloaded)

        # Bilimlar bazasini qayta indekslash
        idx = build_knowledge_index()

        doc_stat = next((d for d in idx.get("documents", []) if d["filename"] == fname), None)
        pages_cnt = doc_stat["pages"] if doc_stat else "Noma'lum"
        chunks_cnt = doc_stat["chunks"] if doc_stat else "Noma'lum"

        success_msg = (
            f"✅ <b>Hujjat muvaffaqiyatli qabul qilindi va bot malakasi oshirildi!</b>\n\n"
            f"📄 <b>Fayl:</b> <code>{esc(fname)}</code>\n"
            f"📑 <b>Sahifalar:</b> {pages_cnt} ta\n"
            f"⚖️ <b>Ajratilgan huquqiy moddalar/parchalar:</b> {chunks_cnt} ta\n"
            f"📚 <b>Jami bazadagi hujjatlar:</b> {idx['total_documents']} ta\n\n"
            f"<i>Endi fuqarolar murojaat qilganda bot bevosita mana shu qaror/buyruqdan moddani havola qilib, aniq va yolg'onsiz javob beradi.</i>"
        )
        bot.edit_message_text(success_msg, chat_id, wait_message_id, parse_mode="HTML")

        if user_id in admin_state and admin_state[user_id].get("waiting_for") == "legal_document":
            admin_state[user_id].pop("waiting_for", None)

    except Exception as e:
        print("Hujjat yuklashda xatolik:", e)
        bot.edit_message_text(
            f"⚠️ Hujjatni tahlil qilishda xatolik yuz berdi: {e}",
            chat_id,
            wait_message_id,
        )


@bot.message_handler(content_types=["photo", "video_note", "video"])
def handle_media(message):
    user_id = message.from_user.id

    # Ijtimoiy AI-konsultant keys tahlili uchun rasm yuborilganda
    if is_admin(user_id) and admin_ai_assistant.handle_admin_ai_message(bot, message, admin_state, is_admin, get_admin_panel_menu):
        return

    # 1. Admin tomonidan huquqiy hujjat fotosurati / skaneri yuborilganda
    if is_admin(user_id) and admin_state.get(user_id, {}).get("waiting_for") == "legal_document":
        if message.content_type == "photo":
            fname = f"hujjat_rasm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            wait_m = bot.reply_to(
                message,
                "⏳ <b>Hujjat surati qabul qilindi. AI Vision orqali to'liq matn tahlil qilinmoqda...</b>",
                parse_mode="HTML",
            )
            try:
                file_info = bot.get_file(message.photo[-1].file_id)
                downloaded = bot.download_file(file_info.file_path)
                dest_path = os.path.join(HUJJATLAR_DIR, fname)
                with open(dest_path, "wb") as f_out:
                    f_out.write(downloaded)

                # Bilimlar bazasini qayta indekslash
                idx = build_knowledge_index()
                doc_stat = next((d for d in idx.get("documents", []) if d["filename"] == fname), None)
                chunks_cnt = doc_stat["chunks"] if doc_stat else "Noma'lum"

                success_msg = (
                    f"✅ <b>Hujjat surati muvaffaqiyatli qabul qilindi va bot malakasi oshirildi!</b>\n\n"
                    f"📸 <b>Fayl:</b> <code>{esc(fname)}</code>\n"
                    f"⚖️ <b>Ajratilgan huquqiy moddalar/parchalar:</b> {chunks_cnt} ta\n"
                    f"📚 <b>Jami bazadagi hujjatlar:</b> {idx['total_documents']} ta\n\n"
                    f"<i>Endi fuqarolar murojaat qilganda bot ushbu rasm/skanerdagi moddalarga tayangan holda aniq javob beradi.</i>"
                )
                bot.edit_message_text(success_msg, message.chat.id, wait_m.message_id, parse_mode="HTML")
                admin_state[user_id].pop("waiting_for", None)
            except Exception as e:
                print("Hujjat rasmini yuklashda xatolik:", e)
                bot.edit_message_text(
                    f"⚠️ Rasm tahlilida xatolik yuz berdi: {e}",
                    message.chat.id,
                    wait_m.message_id,
                )
            return

    # 2. Fuqaro media (rasm/video) yuborganida
    if not is_admin(user_id):
        safe_delete_message(message.chat.id, message.message_id)
        bot.send_message(
            message.chat.id,
            "ℹ️ <b>Faylingiz qabul qilindi.</b>\n\n"
            "O'zbekiston Respublikasi «Shaxsga doir ma'lumotlar to'g'risida»gi Qonuni (O'RQ-547) "
            "talablariga muvofiq, fuqarolardan xonadon rasmlari yoki video talab etilmaydi.\n\n"
            "Iltimos, o'z savolingiz yoki murojaatingizni matn ko'rinishida yozib qoldiring.",
            reply_markup=get_user_main_menu(user_id),
            parse_mode="HTML",
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_qabul_") or call.data.startswith("admin_rad_"))
def handle_admin_decision(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Bunga huquqingiz yo'q!", show_alert=True)
        return

    action_type, target_user_id_str = call.data.rsplit("_", 1)
    target_user_id = int(target_user_id_str)

    if "qabul" in action_type:
        update_excel_status(target_user_id, "Tasdiqlangan")
        bot.edit_message_text(
            f"{esc(call.message.text)}\n\n✅ <b>HOLAT: QABUL QILINDI</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )
        try:
            bot.send_message(
                target_user_id,
                "🎉 <b>Tabriklaymiz! Sizning identifikatsiyangiz muvaffaqiyatli yakunlandi.</b>\n\n"
                "Endi botdan to'liq foydalanishingiz, ijtimoiy yordam va nafaqalar bo'yicha o'z savollaringizni "
                "bevosita pastdagi menyu orqali yuborishingiz mumkin.",
                reply_markup=get_user_main_menu(target_user_id),
                parse_mode="HTML",
            )
            if target_user_id in user_data:
                user_data[target_user_id]["status"] = "Tasdiqlangan"
        except Exception as e:
            print("Fuqaroga tasdiq xabarini yuborishda xatolik:", e)

    elif "rad" in action_type:
        update_excel_status(target_user_id, "Rad_etilgan")
        bot.edit_message_text(
            f"{esc(call.message.text)}\n\n❌ <b>HOLAT: RAD ETILDI</b>",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )
        try:
            bot.send_message(
                target_user_id,
                "⚠️ Kechirasiz, sizning identifikatsiyangiz rad etildi.\n\n"
                "Iltimos, botdan foydalanish uchun shaxsni tasdiqlovchi hujjatingiz bilan Shayxali MFY idorasiga "
                "(Ijtimoiy xodim A. Jo'rayev huzuriga) murojaat qiling yoki /start bosib ma'lumotlarni qaytadan to'g'ri yuboring.",
            )
        except Exception as e:
            print("Fuqaroga rad xabarini yuborishda xatolik:", e)


# ==============================================================================
# 8. TEZKOR SAVOLLAR (FAQ) HANDLERI
# ==============================================================================
@bot.callback_query_handler(func=lambda call: call.data in FAQ_ANSWERS)
def handle_faq_callback(call):
    user_id = call.from_user.id
    javob = localize_text(user_id, FAQ_ANSWERS.get(call.data, "Ma'lumot topilmadi."))
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, javob, parse_mode="HTML", reply_markup=get_user_main_menu(user_id))


# ==============================================================================
# 9. OVOZLI XABARLARNI QABUL QILISH (VOICE -> MATN + QONUNIY JAVOB)
# ==============================================================================
@bot.message_handler(content_types=["voice", "audio"])
def handle_voice_message(message):
    user_id = message.from_user.id

    # 1. Admin AI-консультантига овозли кейс юборган бўлса
    if is_admin(user_id) and admin_ai_assistant.handle_admin_ai_message(bot, message, admin_state, is_admin, get_admin_panel_menu):
        return

    citizen = get_citizen_by_tg_id(user_id)
    bot.send_chat_action(message.chat.id, "typing")
    wait_msg = bot.reply_to(
        message,
        localize_text(
            user_id,
            "🎤 Овозли хабарингиз қабул қилинди, матнга айлантирилиб, қонунчилик асосида таҳлил қилинмоқда...",
            "🎤 Ваше голосовое сообщение анализируется...",
        ),
    )

    try:
        file_id = message.voice.file_id if message.content_type == "voice" else message.audio.file_id
        file_info = bot.get_file(file_id)
        audio_bytes = bot.download_file(file_info.file_path)

        transkripsiya = transcribe_audio_bytes(audio_bytes, filename="voice.ogg")
        transkripsiya_cyr = latin_to_cyrillic_uz(transkripsiya)

        process_and_dispatch_question(
            message=message,
            citizen=citizen,
            original_question=f"[ОВОЗЛИ ХАБАР]: {transkripsiya_cyr}",
            progress_msg_id=wait_msg.message_id,
        )
    except Exception as e:
        print("Ovozli xabarni tahlil qilishda xatolik:", e)
        safe_delete_message(message.chat.id, wait_msg.message_id)
        bot.reply_to(
            message,
            localize_text(
                message.from_user.id,
                "⚠️ Овозли хабарни қайта ишлашда техник узилиш юз берди. Илтимос, саволингизни матн шаклида ёзиб юборинг.",
                "⚠️ Не удалось обработать голосовое сообщение. Пожалуйста, напишите вопрос текстом.",
            ),
        )


# ==============================================================================
# 10. ADMIN PANEL, FUQARO QIDIRUVI (/qidiruv) VA AVTOMATIK HISOBOT (/xisobot)
# ==============================================================================
@bot.message_handler(commands=["admin"])
def handle_admin_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Ushbu bo'lim faqat Shayxali MFY ijtimoiy xodimi (Admin) uchun mo'ljallangan.")
        return

    bot.send_message(
        message.chat.id,
        "👨‍💻 <b>SHAYXALI MFY IJTIMOIY XODIM — ADMIN BOSHQARUV PANELI</b>\n\n"
        "• Fuqaroni tezkor qidirish: <code>/qidiruv Ism yoki Ko'cha</code>\n"
        "• Oylik hisobot: <code>/xisobot 10-2026</code>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=get_admin_panel_menu(),
        parse_mode="HTML",
    )


@bot.message_handler(commands=["qidiruv", "search"])
def handle_qidiruv_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Bu buyruq faqat Admin uchun!")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        msg = bot.send_message(
            message.chat.id,
            "🔍 <b>Qidiruv uchun fuqaroning F.I.Sh., ko'cha nomi, telefon raqami yoki JShShIR/pasportini yozing:</b>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_admin_search_step)
        return

    execute_citizen_search(message.chat.id, parts[1].strip())


def process_admin_search_step(message):
    if not message.text or message.text.strip() == "/cancel":
        return
    execute_citizen_search(message.chat.id, message.text.strip())


def execute_citizen_search(chat_id, query: str):
    """Фуқаролар базасидан ФИО, Телефон, Паспорт/ЖШШИР ёки Кўча бўйича тезкор қидиради (Кирилл ва Лотин)."""
    q = query.strip()
    if not q:
        bot.send_message(chat_id, "🔍 Қидирув матнини киритинг.", parse_mode="HTML")
        return

    results = database.search_citizens(q, limit=10)

    if not results:
        bot.send_message(chat_id, f"🔍 <b>«{esc(q)}»</b> бўйича базадан фуқаро топилмади.", parse_mode="HTML")
        return

    for row in results:
        tg_id = str(row.get("Telegram_ID", ""))
        u_appeals = database.get_citizen_appeals(tg_id) if tg_id else []
        appeals_info = f"{len(u_appeals)} та мурожаат"
        if u_appeals:
            last_a = u_appeals[0]  # ro'yxat eng yangisidan boshlanadi
            appeals_info += f" (Охиргиси: {esc(last_a.get('Murojaat_ID'))} — {esc(last_a.get('Status'))})"

        fio_c = latin_to_cyrillic_uz(row.get('FIO', ''))
        addr_c = latin_to_cyrillic_uz(row.get('Kocha_Manzil') or row.get('Manzil_Geolokatsiya', ''))
        st_c = latin_to_cyrillic_uz(row.get('Status', ''))
        card = (
            f"👤 <b>{esc(fio_c)}</b>\n"
            f"🆔 <b>Telegram ID:</b> <code>{esc(tg_id)}</code>\n"
            f"📞 <b>Телефон:</b> {esc(row.get('Telefon', ''))}\n"
            f"🛂 <b>Паспорт/ЖШШИР:</b> {esc(row.get('Pasport_JSHSHIR', ''))}\n"
            f"🏘 <b>Кўча/Манзил:</b> {esc(addr_c)}\n"
            f"📍 <b>Геолокация:</b> {esc(row.get('Geolokatsiya', ''))}\n"
            f"📌 <b>Ҳолати:</b> {esc(st_c)}\n"
            f"📨 <b>Мурожаатлар тарихи:</b> {appeals_info}"
        )
        bot.send_message(chat_id, card, parse_mode="HTML")


@bot.message_handler(commands=["xisobot", "hisobot"])
def handle_xisobot_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Bu buyruq faqat Admin uchun!")
        return

    parts = (message.text or "").split()
    oy_yil = parts[1].strip() if len(parts) > 1 else datetime.now().strftime("%m-%Y")
    generate_monthly_ai_report(message.chat.id, oy_yil)


def generate_monthly_ai_report(chat_id, oy_yil: str):
    """
    Belgilangan oy (masalan: 10-2026) uchun murojaatlarni bazadan o'qiydi.
    XAVFSIZLIK: Fuqarolarning F.I.Sh. va shaxsiy ma'lumotlari Gemini AI ga YUBORILMAYDI!
    """
    month_appeals = database.get_month_appeals(oy_yil)
    if not month_appeals:
        bot.send_message(
            chat_id,
            f"📂 <b>{esc(oy_yil)}</b> davri uchun bazada hali murojaatlar mavjud emas.",
            parse_mode="HTML",
        )
        return

    db_stats = database.get_monthly_appeal_stats(oy_yil)
    total = db_stats.get("total", len(month_appeals))
    ijobiy = db_stats.get("ijobiy", 0)
    rad = db_stats.get("rad", 0)
    kutmoqda = db_stats.get("kutmoqda", 0)
    shoshilinch = db_stats.get("shoshilinch", 0)
    csat_avg = db_stats.get("csat_avg", 0.0)
    csat_count = db_stats.get("csat_count", 0)
    csat_display = f"{csat_avg} / 5.0 ({csat_count} ta baho)" if csat_count > 0 else "Hali baholar mavjud emas"

    # Eng ko'p murojaat qilgan fuqarolarni lokal Python hisoblaydi (AI ga yuborilmaydi)
    top_citizens = Counter(a.get("FIO") for a in month_appeals if a.get("FIO")).most_common(3)
    top_citizens_str = ", ".join([f"{k} ({v} marta)" for k, v in top_citizens])

    # Savollar ro'yxati (shaxsiy raqamlarsiz)
    savollar_namunasi = "\n".join(
        [f"- {tozalash_regex(str(a.get('Savol') or ''))[:120]}" for a in month_appeals[-40:]]
    )

    report_prompt = (
        f"Quyidagi anonim statistik ma'lumotlar asosida Shayxali MFY ijtimoiy xodimi uchun "
        f"{oy_yil} oyining rasmiy va tushunarli analitik hisobotini o'zbek tilida (lotin yozuvida) tayyorla:\n"
        f"- Jami murojaatlar soni: {total} ta\n"
        f"- Ijobiy hal etilgan / huquqiy tushuntirish berilgan: {ijobiy} ta\n"
        f"- Rad etilgan: {rad} ta\n"
        f"- Ko'rib chiqilmoqda / Tashkilotga yo'naltirilgan: {kutmoqda} ta\n"
        f"- Shoshilinch (🚨) murojaatlar: {shoshilinch} ta\n" \
        f"- Fuqarolar roziligi (CSAT reytingi): {csat_display}\n"
        f"- Kelib tushgan anonim murojaatlar mazmuni:\n{savollar_namunasi}\n\n"
        f"Hisobotni xuddi quyidagi uslubda chiroyli xulosa va tavsiyalar bilan yoz (tizim teglarisiz):\n"
        f"'{oy_yil} oyida jami {total} ta murojaat kelib tushdi. Shundan ... tasi ijobiy hal etildi...'"
    )

    try:
        wait_msg = bot.send_message(chat_id, f"📊 <b>{esc(oy_yil)}</b> oyi uchun analitik hisobot tayyorlanmoqda...", parse_mode="HTML")
        resp = call_gemini_safe(report_prompt)
        _, _, clean_report = parse_ai_output(resp.text or "")
        clean_report = clean_report.replace(AI_DISCLAIMER, "").strip()

        final_text = (
            f"📈 <b>SHAYXALI MFY — AVTOMATIK ANALITIK HISOBOT ({esc(oy_yil)})</b>\n\n"
            f"{clean_report}\n\n"
            f"⭐ <b>Fuqarolar roziligi (CSAT KPI):</b> {csat_display}\n"
            f"👥 <b>Eng ko'p murojaat qilgan fuqarolar (Lokal baza hisobi):</b> {esc(top_citizens_str)}"
        )
        if len(final_text) <= 4000:
            bot.edit_message_text(final_text, chat_id, wait_msg.message_id, parse_mode="HTML")
        else:
            safe_delete_message(chat_id, wait_msg.message_id)
            send_split_message(chat_id, final_text, parse_mode="HTML")
    except Exception as e:
        print("Hisobot yaratishda xatolik:", e)
        bot.send_message(
            chat_id,
            f"📊 <b>{esc(oy_yil)} OYI STATISTIKASI:</b>\n"
            f"• Jami murojaatlar: {total} ta\n"
            f"• Ijobiy hal etildi / AI javob berdi: {ijobiy} ta\n"
            f"• Rad etildi: {rad} ta\n"
            f"• Jarayonda (Kutmoqda): {kutmoqda} ta\n"
            f"• Shoshilinch murojaatlar: {shoshilinch} ta\n"
            f"• Eng faol murojaatchilar: {esc(top_citizens_str)}",
            parse_mode="HTML",
        )


# ==============================================================================
# DINAMIK SOZLAMALAR (SYSTEM SETTINGS) VA NAVBAT GRAFIGI
# ==============================================================================

@bot.message_handler(commands=["status"])
def handle_status_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔄 Янгилаш", callback_data="adm_server_status"),
        types.InlineKeyboardButton("⚙️ Созламалар", callback_data="adm_settings_menu"),
    )
    bot.send_message(message.chat.id, format_server_status_html(), reply_markup=markup, parse_mode="HTML")


@bot.message_handler(commands=["logs"])
def handle_logs_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return
    log_p = os.path.join(BASE_DIR, "bot.log")
    raw_logs = get_recent_logs(log_p, lines_count=20)
    if len(raw_logs) > 3800:
        raw_logs = raw_logs[-3800:]
    text = (
        "📜 <b>ОХИРГИ 20 ҚАТОР ФАОЛИЯТ ВА ХАТОЛИК ЛОГЛАРИ:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<pre><code>{html.escape(raw_logs)}</code></pre>"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🔄 Янгилаш", callback_data="adm_system_logs"),
        types.InlineKeyboardButton("⚙️ Созламалар", callback_data="adm_settings_menu"),
    )
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(commands=["restart"])
def handle_restart_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return
    text = (
        "⚠️ <b>ДИҚҚАТ: Қайта ишга тушириш (Restart)</b>\n\n"
        "Ростдан ҳам бот ва барча тизим хизматларини масофадан қайта ишга туширмоқчимисиз?"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Ҳа, қайта юклансин", callback_data="adm_restart_confirm_yes"),
        types.InlineKeyboardButton("❌ Бекор қилиш", callback_data="adm_settings_menu"),
    )
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(commands=["backup", "db_backup"])
def handle_backup_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return
    wait_m = bot.send_message(message.chat.id, "⏳ Маълумотлар базаси заҳираси тайёрланмоқда...")
    try:
        backup_p = database.backup_database()
        with open(backup_p, "rb") as f:
            bot.send_document(
                message.chat.id,
                f,
                caption=f"🗄️ <b>IHMA маълумотлар базаси заҳираси:</b>\n<code>{os.path.basename(backup_p)}</code>",
                parse_mode="HTML"
            )
        bot.delete_message(message.chat.id, wait_m.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Заҳира олишда хатолик: {e}", message.chat.id, wait_m.message_id)

@bot.message_handler(commands=["javob", "reply"])
def handle_reply_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(
            message,
            "✍️ <b>Мурожаатга жавоб ёзиш:</b>\n\n"
            "Илтимос, мурожаат рақамини кўрсатинг. Масалан:\n"
            "<code>/javob M-1027</code> ёки <code>/javob 1027</code>",
            parse_mode="HTML"
        )
        return

    raw_id = parts[1].strip()
    m_id = raw_id if raw_id.upper().startswith("M-") else f"M-{raw_id}"

    m_data = get_murojaat_by_id(m_id)
    if not m_data:
        bot.reply_to(message, f"❌ <b>#{m_id}</b> рақамли мурожаат топилмади.")
        return

    admin_state[message.from_user.id] = {"reply_murojaat_id": m_id}
    cit_name = m_data.get("FIO") or "Фуқаро"
    cit_phone = m_data.get("Telefon") or "Кўрсатилмаган"
    cit_tg = m_data.get("Telegram_ID") or ""
    savol_preview = m_data.get("Savol") or ""
    if len(savol_preview) > 300:
        savol_preview = savol_preview[:300] + "..."

    markup = get_murojaat_admin_buttons(m_id)
    msg = bot.send_message(
        message.chat.id,
        f"✍️ <b>#{m_id}</b> рақамли мурожаатга жавоб ёзиш:\n\n"
        f"👤 <b>Фуқаро:</b> {esc(cit_name)}\n"
        f"📞 <b>Телефон:</b> {esc(cit_phone)}\n"
        f"🆔 <b>TG ID:</b> <code>{cit_tg}</code>\n"
        f"📝 <b>Мурожаат матни:</b>\n<i>{esc(savol_preview)}</i>\n\n"
        f"<i>Илтимос, фуқарога юбориладиган расмий жавоб матнини ёзинг:</i>\n"
        f"<i>(Бекор қилиш учун /cancel)</i>",
        reply_markup=markup,
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, process_admin_direct_reply)


@bot.message_handler(commands=["sozlamalar", "settings"])
def handle_sozlamalar_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Бу бўлим фақат Админ учун!")
        return
    show_admin_settings_panel(message.chat.id)


def show_admin_settings_panel(chat_id, message_id=None):
    mih_val = database.get_setting("mih_amount", "669000")
    try:
        mih_int = int(re.sub(r"[^\d]", "", str(mih_val)))
        mih_formatted = f"{mih_int:,}".replace(",", " ")
    except Exception:
        mih_formatted = str(mih_val)

    m = get_system_metrics()
    tunnel_live = bool(WEB_APP_URL and is_tunnel_alive(WEB_APP_URL))
    tunnel_status = "🟢 Фаол" if tunnel_live else "🔴 Нофаол / Узилган"

    text = (
        "⚙️ <b>ТИЗИМ ВА СЕРВЕР СОЗЛАМАЛАРИ (Бошқарув маркази):</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>МИҲ суммаси:</b> <code>{mih_formatted} сўм</code>\n"
        f"🌐 <b>Mini App Tunneli:</b> {tunnel_status}\n"
        f"🖥 <b>Сервер юкламаси:</b> CPU: <code>{m['cpu_percent']}%</code> | RAM: <code>{m['ram_percent']}%</code>\n"
        f"⏱ <b>Бот иш вақти (Uptime):</b> <code>{m['bot_uptime']}</code>\n\n"
        "<i>Керакли бўлим ёки маълумот тугмасини танланг:</i>"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💰 МИҲ суммаси", callback_data="adm_set_mih"),
        types.InlineKeyboardButton("🌐 Mini App Tunnel", callback_data="adm_tunnel_info"),
    )
    markup.add(
        types.InlineKeyboardButton("📊 Сервер ҳолати (psutil)", callback_data="adm_server_status"),
        types.InlineKeyboardButton("📜 Тизим логлари (Logs)", callback_data="adm_system_logs"),
    )
    markup.add(
        types.InlineKeyboardButton("📅 Қабулни очиш / ёпиш", callback_data="adm_toggle_queue"),
        types.InlineKeyboardButton("🕒 Қабул соатлари", callback_data="adm_set_queue_hours"),
    )
    markup.add(
        types.InlineKeyboardButton("🤖 AI Диагностика", callback_data="adm_ai_diagnostics"),
        types.InlineKeyboardButton("🗄️ База заҳираси (.db)", callback_data="adm_db_backup"),
    )
    markup.add(
        types.InlineKeyboardButton("🧹 Кешни тозалаш", callback_data="adm_clean_cache"),
        types.InlineKeyboardButton("🔄 Қайта юклаш (Restart)", callback_data="adm_restart_prompt"),
    )
    markup.add(
        types.InlineKeyboardButton("🔙 Админ Панелига қайтиш", callback_data="adm_back_main"),
    )

    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                return
            pass
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def process_admin_set_mih_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ МИҲ ўзгартириш бекор қилинди.")
        return
    raw = re.sub(r"[^\d]", "", message.text.strip())
    if not raw or int(raw) < 100000:
        bot.send_message(message.chat.id, "⚠️ Нотўғри сумма киритилди. Амал бекор қилинди.")
        return
    new_val = int(raw)
    database.set_setting("mih_amount", str(new_val), "Минимал истеъмол харажатлари")
    bot.send_message(
        message.chat.id,
        f"✅ <b>МИҲ суммаси муваффақиятли янгиланди:</b> <code>{new_val:,} сўм</code>\n"
        "Mini App Нафақа калькулятори (ВМ-62) ушбу сумма асосида автоматик ҳисоблайди.",
        parse_mode="HTML"
    )
    show_admin_settings_panel(message.chat.id)


def process_admin_close_queue_reason_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Қабулни ёпиш бекор қилинди.")
        return
    reason = message.text.strip()
    if reason == "/skip":
        reason = "Ижтимоий ходим маҳаллада хонадонма-хонадон ўрганишда бўлганлиги сабабли бугунги қабул вақтинча тўхтатилган."
    database.set_setting("queue_open", "0", "Электрон навбат ҳолати")
    database.set_setting("queue_closed_reason", reason, "Қабул ёпилиш сабаби")
    bot.send_message(
        message.chat.id,
        f"🔴 <b>Бугунги қабул вақтинча ёпилди!</b>\n\n"
        f"Сабаб: <i>{esc(reason)}</i>\n"
        "Mini App'да фуқароларга бу ҳақда махсус огоҳлантириш чиқади.",
        parse_mode="HTML"
    )
    show_admin_settings_panel(message.chat.id)


def process_admin_set_queue_hours_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Қабул соатларини ўзгартириш бекор қилинди.")
        return
    new_hours = message.text.strip()
    database.set_setting("queue_hours", new_hours, "Қабул соатлари")
    bot.send_message(
        message.chat.id,
        f"✅ <b>Қабул соатлари янгиланди:</b> <code>{esc(new_hours)}</code>",
        parse_mode="HTML"
    )
    show_admin_settings_panel(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def handle_admin_panel_callbacks(call):
    global WEB_APP_URL
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Ruxsat yo'q!", show_alert=True)
        return

    action = call.data
    bot.answer_callback_query(call.id)

    # Fuqaro shaxsini tasdiqlash / rad etish
    if action.startswith("adm_appr_cit_"):
        target_uid = action.replace("adm_appr_cit_", "")
        database.update_citizen_status(target_uid, "Tasdiqlangan")
        try:
            bot.edit_message_text(
                esc(call.message.text or "") + "\n\n✅ <b>ADMIN TOMONIDAN TASDIQLANDI</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            bot.send_message(
                int(target_uid),
                "🎉 <b>Tabriklaymiz! Shaxsingiz Shayxali MFY ijtimoiy xodimi tomonidan muvaffaqiyatli tasdiqlandi.</b>\n\n"
                "Endi barcha xizmatlar, jumladan ijtimoiy xodimga bevosita rasmiy murojaat yuborish siz uchun to'liq faol!",
                parse_mode="HTML",
                reply_markup=get_user_main_menu(int(target_uid)),
            )
        except Exception as e:
            print("Fuqaroga tasdiqlash xabari yuborilmadi:", e)
        return

    elif action.startswith("adm_rejc_cit_"):
        target_uid = action.replace("adm_rejc_cit_", "")
        database.update_citizen_status(target_uid, "Rad etilgan")
        try:
            bot.edit_message_text(
                esc(call.message.text or "") + "\n\n❌ <b>ADMIN TOMONIDAN RAD ETILDI</b>",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            bot.send_message(
                int(target_uid),
                "⚠️ <b>Hurmatli fuqaro!</b>\n\n"
                "Kiritilgan ma'lumotlarda nomuvofiqlik aniqlangani sababli identifikatsiya so'rovingiz tasdiqlanmadi.\n"
                "Iltimos, ma'lumotlarni qaytadan to'g'ri kiriting yoki ijtimoiy xodim bilan bog'laning: +998 91 454 53 51",
                parse_mode="HTML",
                reply_markup=get_user_main_menu(int(target_uid)),
            )
        except Exception as e:
            print("Fuqaroga rad xabari yuborilmadi:", e)
        return

    if action == "adm_kb_menu":
        stats = get_knowledge_base_stats()
        kb_text = (
            "📚 <b>HUQUQIY BILIMLAR BAZASI VA MALAKA OSHIRISH (RAG TIZIMI)</b>\n\n"
            f"📁 <b>Bazadagi hujjatlar soni:</b> {stats['total_documents']} ta\n"
            f"📑 <b>Tahlil qilingan moddalar/parchalar:</b> {stats['total_chunks']} ta\n"
            f"🕒 <b>Oxirgi indekslangan vaqt:</b> {stats['updated_at']}\n\n"
            "⚖️ <i>Bot barcha savollarga faqat siz yuklagan rasmiy huquqiy hujjatlardan qidirib, "
            "aniq moddalar bilan javob beradi (yolg'on va to'qimalarsiz).</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📥 Yangi hujjat yuklash (PDF/DOC/DOCX/XLSX/Rasm)", callback_data="adm_kb_upload"),
            types.InlineKeyboardButton("🔄 Bazani to'liq qayta tahlil qilish (Malaka oshirish)", callback_data="adm_kb_reindex"),
            types.InlineKeyboardButton("📋 Yuklangan hujjatlar ro'yxati", callback_data="adm_kb_list"),
            types.InlineKeyboardButton("🔙 Admin Paneliga qaytish", callback_data="adm_back_main"),
        )
        try:
            bot.edit_message_text(kb_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, kb_text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_kb_upload":
        admin_state[call.from_user.id] = {"waiting_for": "legal_document"}
        bot.send_message(
            call.message.chat.id,
            "📥 <b>Huquqiy hujjat yoki rasm/skanerni chatga yuboring:</b>\n\n"
            "📄 <b>Qabul qilinadigan barcha formatlar:</b>\n"
            "• <b>Matnlar:</b> PDF, DOC, DOCX, RTF, TXT\n"
            "• <b>Jadvallar:</b> XLSX, XLS, CSV (mezonlar va ro'yxatlar)\n"
            "• <b>Surat/Skanerlar:</b> JPG, PNG, WEBP (qog'oz hujjat fotosurati)\n\n"
            "<i>Faylni hujjat (Document) yoki rasm (Photo) sifatida tashlang. "
            "Bot uni avtomatik o'qib, moddalarga ajratadi va malakasini oshiradi.</i>\n\n"
            "<i>(Bekor qilish uchun /cancel deb yozing)</i>",
            parse_mode="HTML",
        )

    elif action == "adm_kb_reindex":
        wait_m = bot.send_message(call.message.chat.id, "🔄 Hujjatlar qayta o'qilmoqda va bot malakasi oshirilmoqda...")
        idx = build_knowledge_index()
        bot.edit_message_text(
            f"✅ <b>Malaka oshirish muvaffaqiyatli yakunlandi!</b>\n\n"
            f"📁 <b>Jami hujjatlar:</b> {idx['total_documents']} ta\n"
            f"📑 <b>Indekslangan moddalar/parchalar:</b> {idx['total_chunks']} ta\n"
            f"🕒 <b>Sana:</b> {idx['updated_at']}\n\n"
            f"Bot endi fuqarolarning savollariga mana shu rasmiy hujjatlardan qidirib, aniq moddalar bilan javob beradi.",
            call.message.chat.id,
            wait_m.message_id,
            parse_mode="HTML",
        )

    elif action == "adm_kb_list":
        stats = get_knowledge_base_stats()
        docs = stats.get("documents", [])
        if not docs:
            bot.send_message(call.message.chat.id, "📭 Hozircha bazada yuklangan hujjatlar yo'q.")
            return

        lines = ["📋 <b>BAZADAGI RASMIY HUQUQIY HUJJATLAR RO'YXATI:</b>\n"]
        for i, d in enumerate(docs, 1):
            lines.append(
                f"<b>{i}. {esc(d['filename'])}</b>\n"
                f"   📄 Sahifalar: {d['pages']} ta | 📑 Parchalar: {d['chunks']} ta ({d['size_kb']} KB)"
            )
        send_split_message(call.message.chat.id, "\n\n".join(lines), parse_mode="HTML")

    elif action == "adm_back_main":
        bot.edit_message_text(
            "👨‍💻 <b>ШАЙХ-АЛИ МФЙ ИЖТИМОИЙ ХОДИМИ — АДМИН БОШҚАРУВ ПАНЕЛИ</b>\n\n"
            "• 🧠 AI Ёрдамчи: Ижтимоий хизматлар ва далолатнома генератори\n"
            "• 📚 Ижтимоий AI билимлари: Махсус RAG базаси\n"
            "• ⚙️ Тизим созламалари: МИҲ ва қабул графиги\n"
            "• 🔍 Фуқарони қидириш: <code>/qidiruv Исм ёки Кўча</code>\n"
            "• 📈 Ойлик AI ҳисобот: <code>/xisobot 10-2026</code>\n\n"
            "Керакли бўлимни танланг:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_admin_panel_menu(),
            parse_mode="HTML",
        )

    elif action == "adm_settings_menu":
        show_admin_settings_panel(call.message.chat.id, call.message.message_id)

    elif action == "adm_set_mih":
        msg = bot.send_message(
            call.message.chat.id,
            "💰 <b>Янги МИҲ (Минимал истеъмол харажатлари) суммасини сўмда киритинг:</b>\n"
            "<i>(Масалан: 669000 ёки 700000. Бекор қилиш учун /cancel)</i>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_admin_set_mih_step)

    elif action == "adm_toggle_queue":
        settings = database.get_all_settings()
        is_open = str(settings.get("queue_open", "1")) == "1"
        if is_open:
            msg = bot.send_message(
                call.message.chat.id,
                "🔴 <b>Қабулни вақтинча ёпиш сабабини ёзинг:</b>\n"
                "<i>(Масалан: Маҳаллада хонадонма-хонадон ўрганиш ёки фавқулодда йиғилиш)\n"
                "Ёки стандарт сабаб учун /skip деб ёзинг:</i>",
                parse_mode="HTML",
            )
            bot.register_next_step_handler(msg, process_admin_close_queue_reason_step)
        else:
            database.set_setting("queue_open", "1", "Электрон навбат ҳолати")
            database.set_setting("queue_closed_reason", "", "Қабул ёпилиш сабаби")
            bot.send_message(call.message.chat.id, "🟢 Қабул қайта очилди!")
            show_admin_settings_panel(call.message.chat.id, call.message.message_id)

    elif action == "adm_set_queue_hours":
        msg = bot.send_message(
            call.message.chat.id,
            "⏰ <b>Янги қабул вақтини киритинг:</b>\n"
            "<i>(Масалан: 09:00 - 13:00 ёки 14:00 - 18:00. Бекор қилиш учун /cancel)</i>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_admin_set_queue_hours_step)

    elif action == "adm_server_status":
        text = format_server_status_html()
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔄 Янгилаш", callback_data="adm_server_status"),
            types.InlineKeyboardButton("⬅️ Созламаларга қайтиш", callback_data="adm_settings_menu"),
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                try:
                    bot.answer_callback_query(call.id, "Ҳолат янги (ўзгаришсиз)")
                except Exception:
                    pass
            else:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_system_logs":
        log_p = os.path.join(BASE_DIR, "bot.log")
        raw_logs = get_recent_logs(log_p, lines_count=20)
        if len(raw_logs) > 3800:
            raw_logs = raw_logs[-3800:]
        text = (
            "📜 <b>ОХИРГИ 20 ҚАТОР ФАОЛИЯТ ВА ХАТОЛИК ЛОГЛАРИ:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<pre><code>{html.escape(raw_logs)}</code></pre>"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔄 Янгилаш", callback_data="adm_system_logs"),
            types.InlineKeyboardButton("🧹 Логни тозалаш", callback_data="adm_clean_cache"),
        )
        markup.add(
            types.InlineKeyboardButton("⬅️ Созламаларга қайтиш", callback_data="adm_settings_menu"),
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                try:
                    bot.answer_callback_query(call.id, "Логлар янги (ўзгаришсиз)")
                except Exception:
                    pass
            else:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_tunnel_info":
        is_live = bool(WEB_APP_URL and is_tunnel_alive(WEB_APP_URL))
        stat_emoji = "🟢 ФАОЛ (LIVE)" if is_live else "🔴 НОФАОЛ / УЗИЛГАН"
        current_url = WEB_APP_URL or "Ҳозирча ўрнатилмаган"
        text = (
            "🌐 <b>TELEGRAM MINI APP HTTPS TUNNEL ҲОЛАТИ:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 <b>Ҳолати:</b> {stat_emoji}\n"
            f"🔗 <b>Жорий URL:</b>\n<code>{current_url}</code>\n\n"
            f"⚙️ <b>Порт:</b> <code>5001 (Flask WebApp)</code>\n"
            f"🛡 <b>Провайдер:</b> <code>Cloudflare Quick Tunnel</code>\n\n"
            "<i>Агар Telegram'да Mini App очилмаса, пастдаги тугма орқали янги tunnel очишингиз мумкин.</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Янги Tunnel очиш ва улаш", callback_data="adm_tunnel_renew"),
            types.InlineKeyboardButton("⬅️ Созламаларга қайтиш", callback_data="adm_settings_menu"),
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_tunnel_renew":
        try:
            bot.answer_callback_query(call.id, "Янги tunnel очилмоқда...")
        except Exception:
            pass
        wait_m = bot.send_message(call.message.chat.id, "🔄 <b>Янги Cloudflare HTTPS tunnel яратилмоқда...</b>", parse_mode="HTML")
        tma_port = int(os.getenv("PORT", 5001))
        WEB_APP_URL = ""
        new_u = auto_ensure_tunnel(port=tma_port)
        try:
            bot.delete_message(call.message.chat.id, wait_m.message_id)
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            f"✅ <b>Янги Mini App tunneli муваффақиятли фаоллашди!</b>\n\n"
            f"🔗 <b>Янги URL:</b>\n<code>{new_u}</code>\n\n"
            "Telegram Меню тугмаси ҳам автоматик янгиланди.",
            parse_mode="HTML"
        )
        show_admin_settings_panel(call.message.chat.id)

    elif action == "adm_ai_diagnostics":
        model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-3.8-flash")
        start_ping = time.time()
        ping_res = "🟢 Тест муваффақиятли"
        latency_ms = 0
        try:
            keys = GEMINI_API_KEYS if GEMINI_API_KEYS else ([GEMINI_API_KEY] if GEMINI_API_KEY else [])
            if keys:
                genai.configure(api_key=keys[0])
            m_inst = genai.GenerativeModel(model_name)
            r = m_inst.generate_content("Ping")
            latency_ms = int((time.time() - start_ping) * 1000)
        except Exception as pe:
            ping_res = f"🔴 Хатолик: {pe}"
            latency_ms = int((time.time() - start_ping) * 1000)

        kb_stats = get_knowledge_base_stats()
        text = (
            "🤖 <b>AI AGENT (GEMINI) ҲОЛАТИ ВА ДИАГНОСТИКАСИ:</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🧠 <b>Асосий AI Модель:</b> <code>{model_name}</code>\n"
            f"⚡ <b>Тезлик (Latency):</b> <code>{latency_ms} ms</code>\n"
            f"📡 <b>Уланиш ҳолати:</b> {ping_res}\n"
            f"📚 <b>RAG Билимлар базаси:</b> <code>{kb_stats['total_documents']} та расмий ҳужжат ({kb_stats['total_chunks']} банд)</code>\n"
            f"🛡 <b>Захира AI:</b> <code>Groq (LLaMA-3 / Mixtral)</code>\n"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⚡ Қайта синаш", callback_data="adm_ai_diagnostics"),
            types.InlineKeyboardButton("⬅️ Созламаларга қайтиш", callback_data="adm_settings_menu"),
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_db_backup":
        try:
            bot.answer_callback_query(call.id, "Заҳира олинмоқда...")
        except Exception:
            pass
        wait_m = bot.send_message(call.message.chat.id, "⏳ Маълумотлар базасидан тўлиқ заҳира (.db) олинмоқда...")
        try:
            backup_p = database.backup_database()
            with open(backup_p, "rb") as f:
                bot.send_document(
                    call.message.chat.id,
                    f,
                    caption=f"🗄️ <b>IHMA маълумотлар базаси заҳираси:</b>\n<code>{os.path.basename(backup_p)}</code>",
                    parse_mode="HTML"
                )
            try:
                bot.delete_message(call.message.chat.id, wait_m.message_id)
            except Exception:
                pass
        except Exception as be:
            bot.edit_message_text(f"❌ Заҳира олишда хатолик: {be}", call.message.chat.id, wait_m.message_id)

    elif action == "adm_clean_cache":
        try:
            bot.answer_callback_query(call.id, "Логлар тозаланмоқда...")
        except Exception:
            pass
        log_p = os.path.join(BASE_DIR, "bot.log")
        res_msg = clean_logs_file(log_p, keep_lines=500)
        bot.send_message(
            call.message.chat.id,
            f"🧹 <b>КЕШ ВА ЛОГ ТОЗАЛАШ ҲИСОБОТИ:</b>\n\n{res_msg}",
            parse_mode="HTML"
        )
        show_admin_settings_panel(call.message.chat.id)

    elif action == "adm_restart_prompt":
        text = (
            "⚠️ <b>ДИҚҚАТ: Қайта ишга тушириш (Restart)</b>\n\n"
            "Ростдан ҳам бот ва барча тизим хизматларини масофадан қайта ишга туширмоқчимисиз?\n\n"
            "<i>(systemd сервиси 2-3 сонияда ботни автоматик қайта ёқади)</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Ҳа, қайта юклансин", callback_data="adm_restart_confirm_yes"),
            types.InlineKeyboardButton("❌ Бекор қилиш", callback_data="adm_settings_menu"),
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    elif action == "adm_restart_confirm_yes":
        try:
            bot.answer_callback_query(call.id, "Қайта ишга туширилмоқда...", show_alert=True)
        except Exception:
            pass
        bot.send_message(
            call.message.chat.id,
            "🔄 <b>Бот қайта ишга туширилмоқда...</b>\n"
            "<i>Илтимос, 3-5 сония кутинг. Бот янгиланиб қайта алоқага чиқади.</i>",
            parse_mode="HTML"
        )
        def _trigger_restart():
            import time, subprocess, os
            time.sleep(1)
            try:
                subprocess.run(["systemctl", "--user", "restart", "ihma-bot"], check=True)
            except Exception:
                os._exit(0)
        threading.Thread(target=_trigger_restart, daemon=True).start()

    elif action == "adm_stats":
        bot.send_message(call.message.chat.id, format_system_stats_html(), parse_mode="HTML")

    elif action == "adm_search_user":
        msg = bot.send_message(
            call.message.chat.id,
            "🔍 <b>Qidiruv uchun fuqaroning F.I.Sh., ko'cha nomi, telefon raqami yoki JShShIR/pasportini yozing:</b>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_admin_search_step)

    elif action == "adm_pending":
        pending = database.get_pending_appeals(limit=10)
        if not pending:
            bot.send_message(call.message.chat.id, "✅ Hozirda ko'rib chiqilmagan ochiq murojaatlar yo'q!")
            return

        for row in pending:
            m_id = row["Murojaat_ID"]
            badge = "🚨 SHOSHILINCH" if row["Muhimlik"] == "SHOSHILINCH" else "⏳ KUTMOQDA"
            kocha = row.get("Kocha_Manzil") or "Ko'rsatilmagan"
            raw_q = row.get("Savol") or ""
            q_prev = (raw_q[:1200] + "...") if len(raw_q) > 1200 else raw_q
            txt = (
                f"{badge} | <b>ID: {esc(m_id)}</b> ({esc(row['Sana'])})\n"
                f"👤 <b>Fuqaro:</b> {esc(row['FIO'])} ({esc(row['Telefon'])})\n"
                f"🛂 <b>Pasport/JSHSHIR:</b> {esc(row['Pasport_JSHSHIR'])}\n"
                f"🏘 <b>Manzil:</b> {esc(kocha)}\n"
                f"❓ <b>Murojaat:</b> {esc(q_prev)}\n"
                f"📌 <b>Holati:</b> {esc(row['Status'])}"
            )
            send_split_message(
                chat_id=call.message.chat.id,
                text=txt,
                reply_markup=get_murojaat_admin_buttons(m_id),
                parse_mode="HTML",
            )

    elif action == "adm_overdue":
        overdue_list = check_overdue_appeals(notify_admin=False)
        if not overdue_list:
            bot.send_message(call.message.chat.id, "✅ 24 soatdan oshgan javobsiz murojaatlar yo'q!")
        else:
            for item in overdue_list[:10]:
                m_id = item["Murojaat_ID"]
                txt = (
                    f"⏰ <b>MUDDATI O'TAYOTGAN MUROJAAT (24+ soat)</b>\n"
                    f"🆔 <b>ID:</b> {esc(m_id)} ({esc(item['Sana'])})\n"
                    f"👤 <b>Fuqaro:</b> {esc(item['FIO'])} ({esc(item['Telefon'])})\n"
                    f"❓ <b>Savol:</b> {esc(item['Savol'])}\n"
                    f"📌 <b>Holati:</b> {esc(item['Status'])}"
                )
                bot.send_message(
                    call.message.chat.id,
                    txt,
                    reply_markup=get_murojaat_admin_buttons(m_id),
                    parse_mode="HTML",
                )

    elif action == "adm_queues":
        active_q = database.get_active_navbatlar(limit=15)
        if not active_q:
            bot.send_message(call.message.chat.id, "📅 Hozirda qabulga yozilgan faol navbatlar yo'q.")
            return
        lines = ["📅 <b>QABULGA YOZILGAN FUQAROLAR RO'YXATI:</b>\n"]
        for r in active_q:
            lines.append(
                f"🎟 <b>{esc(r['Navbat_ID'])}</b> — <b>{esc(r['Qabul_Kuni'])} | {esc(r['Qabul_Soati'])}</b>\n"
                f"👤 {esc(r['FIO'])} ({esc(r['Telefon'])}) — {esc(r['Kocha_Manzil'])}"
            )
        send_split_message(call.message.chat.id, "\n\n".join(lines), parse_mode="HTML")

    elif action == "adm_broadcast_all":
        msg = bot.send_message(
            call.message.chat.id,
            "📢 <b>Barcha tasdiqlangan fuqarolarga yuboriladigan xabar matnini kiriting:</b>\n"
            "<i>(Bekor qilish uchun /cancel deb yozing)</i>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_broadcast_all_step)

    elif action == "adm_broadcast_area":
        kochalar = database.get_known_addresses(limit=8)
        kocha_namuna = ", ".join(kochalar) if kochalar else "Hozircha ko'chalar kiritilmagan"

        msg = bot.send_message(
            call.message.chat.id,
            "🏘 <b>Qaysi ko'cha yoki hudud aholisiga xabar yubormoqchisiz?</b>\n"
            f"📂 <i>Bazadagi manzillar namunasi: {esc(kocha_namuna)}</i>\n\n"
            "Hudud yoki ko'cha nomini yozing (Masalan: <code>Navoiy</code> yoki <code>Paxtazor</code>):",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_broadcast_area_name_step)

    elif action == "adm_ai_report_now":
        generate_monthly_ai_report(call.message.chat.id, datetime.now().strftime("%m-%Y"))

    elif action == "adm_download_excel":
        send_full_excel_report(call.message.chat.id)


def format_system_stats_html() -> str:
    """Admin paneli va tezkor tugma uchun yagona statistika matni (faqat SQLite dan)."""
    s = database.get_system_stats()
    return (
        "📊 <b>ТИЗИМНИНГ ЖОРИЙ СТАТИСТИКАСИ</b>\n\n"
        f"👥 <b>Рўйхатдан ўтган фуқаролар:</b> {s['fuqarolar_jami']} та\n"
        f"✅ <b>Тасдиқланган фуқаролар:</b> {s['tasdiqlangan']} та\n"
        f"⏳ <b>Тасдиқ кутаётганлар:</b> {s['tasdiq_kutayotgan']} та\n\n"
        f"📨 <b>Жами келиб тушган мурожаатлар:</b> {s['murojaatlar_jami']} та\n"
        f"🚨 <b>Очиқ шошилинч мурожаатлар:</b> {s['shoshilinch']} та\n"
        f"🕒 <b>Кўриб чиқилиши керак бўлган мурожаатлар:</b> {s['ochiq_murojaatlar']} та\n"
        f"📅 <b>Қабулга ёзилган фаол навбатлар:</b> {s['faol_navbatlar']} та"
    )


def send_full_excel_report(chat_id):
    """To'liq Excel hisobotini adminga yuboradi va serverdagi nusxasini o'chiradi (ichida shaxsiy ma'lumot bor)."""
    report_path = database.export_all_to_excel()
    if not report_path or not os.path.exists(report_path):
        bot.send_message(chat_id, "⚠️ Excel ҳисоботини шакллантириб бўлмади.")
        return
    try:
        with open(report_path, "rb") as f_obj:
            bot.send_document(
                chat_id,
                f_obj,
                caption="📊 <b>Shayx-Ali MFY to'liq Excel hisoboti</b>\n(Fuqarolar, Murojaatlar, Navbatlar va CSAT baholari)",
                parse_mode="HTML",
            )
    except Exception as e:
        print("Excel hisobotini yuborishda xatolik:", e)
        bot.send_message(chat_id, "⚠️ Файлни юборишда хатолик юз берди.")
    finally:
        try:
            os.remove(report_path)
        except OSError as e:
            print("Excel hisobot nusxasini o'chirib bo'lmadi:", e)


def process_broadcast_all_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Ommaviy xabarnoma bekor qilindi.")
        return

    send_broadcast_to_users(message.chat.id, message.text.strip(), area_filter=None)


def process_broadcast_area_name_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Ommaviy xabarnoma bekor qilindi.")
        return

    area_keyword = message.text.strip()
    admin_state[message.from_user.id] = {"broadcast_area": area_keyword}
    msg = bot.send_message(
        message.chat.id,
        f"✍️ Endi <b>«{esc(area_keyword)}»</b> hududi fuqarolariga yuboriladigan xabarnoma matnini kiriting:",
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, process_broadcast_area_text_step)


def process_broadcast_area_text_step(message):
    if not message.text or message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Ommaviy xabarnoma bekor qilindi.")
        return

    area_keyword = admin_state.get(message.from_user.id, {}).get("broadcast_area", "")
    send_broadcast_to_users(message.chat.id, message.text.strip(), area_filter=area_keyword)


def send_broadcast_to_users(admin_chat_id, text_body: str, area_filter=None):
    targets = database.get_verified_citizens(area_filter=area_filter)

    sent_count = 0
    failed_count = 0
    for row in targets:
        tg_id = row.get("Telegram_ID", "")
        if tg_id:
            try:
                bot.send_message(
                    int(tg_id),
                    f"📢 <b>SHAYXALI MFY E'LONI:</b>\n\n{esc(text_body)}",
                    parse_mode="HTML",
                )
                sent_count += 1
            except Exception as e:
                failed_count += 1
                print(f"E'lon {tg_id} ga yetmadi:", e)
            time.sleep(0.05)  # Telegram ommaviy xabar limiti: ~20-30 xabar/soniya

    failed_note = f"\n⚠️ Yetkazilmadi: <b>{failed_count}</b> nafar" if failed_count else ""
    bot.send_message(
        admin_chat_id,
        f"✅ Xabarnoma jami <b>{sent_count}</b> nafar fuqaroga muvaffaqiyatli yetkazildi!{failed_note}",
        parse_mode="HTML",
    )


# ==============================================================================
# 11. ADMINGA KELGAN MUROJAAT TUGMALARI VA STATUS BOSHQARUVI
# ==============================================================================
def get_murojaat_admin_buttons(murojaat_id: str):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_reply = types.InlineKeyboardButton("✍️ Fuqaroga javob yozish", callback_data=f"mstat_reply_{murojaat_id}")
    btn_org = types.InlineKeyboardButton("🏢 Tashkilotga yo'naltirildi", callback_data=f"mstat_org_{murojaat_id}")
    btn_ok = types.InlineKeyboardButton("✅ Qanoatlantirildi", callback_data=f"mstat_ok_{murojaat_id}")
    btn_rad = types.InlineKeyboardButton("❌ Rad etildi", callback_data=f"mstat_rad_{murojaat_id}")
    btn_doc = types.InlineKeyboardButton("📄 Dalolatnoma (.docx)", callback_data=f"mstat_doc_{murojaat_id}")
    markup.add(btn_reply)
    markup.add(btn_org, btn_ok, btn_rad)
    markup.add(btn_doc)
    return markup


@bot.callback_query_handler(func=lambda call: call.data.startswith("mstat_"))
def handle_murojaat_status_callbacks(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Faqat admin uchun!", show_alert=True)
        return

    _, action, murojaat_id = call.data.split("_", 2)
    # Har bir callback ga faqat bir marta javob berish mumkin
    bot.answer_callback_query(call.id, "📄 Dalolatnoma tayyorlanmoqda..." if action == "doc" else None)

    if action == "doc":
        docx_path = database.generate_dalolatnoma_docx(murojaat_id)
        if docx_path and os.path.exists(docx_path):
            try:
                with open(docx_path, "rb") as f_doc:
                    bot.send_document(
                        call.message.chat.id,
                        f_doc,
                        caption=f"📄 <b>Shayx-Ali MFY rasmiy dalolatnomasi</b>\n(Murojaat № {esc(murojaat_id)})",
                        parse_mode="HTML",
                    )
            except Exception as e:
                bot.send_message(call.message.chat.id, f"⚠️ Hujjat yuborishda xatolik: {e}")
        else:
            bot.send_message(call.message.chat.id, "⚠️ Murojaat topilmadi yoki dalolatnoma yaratib bo'lmadi.")
        return

    if action == "reply":
        admin_state[call.from_user.id] = {"reply_murojaat_id": murojaat_id}
        msg = bot.send_message(
            call.message.chat.id,
            f"✍️ <b>{esc(murojaat_id)}</b> raqamli murojaat egasiga yuboriladigan rasmiy javob matnini yozing:",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, process_admin_direct_reply)
        return

    status_map = {
        "org": ("Tegishli tashkilotga yo'naltirilgan", "🏢 Sizning murojaatingiz ko'rib chiqish uchun tegishli tashkilotga yo'naltirildi."),
        "ok": ("Arizangiz qanoatlantirilgan", "✅ Sizning murojaatingiz Shayxali MFY ijtimoiy xodimi tomonidan ijobiy hal etildi (qanoatlantirildi)."),
        "rad": ("Rad etilgan", "❌ Sizning murojaatingiz o'rganib chiqildi va qonunchilik mezonlariga ko'ra rad etildi."),
    }

    if action in status_map:
        new_status, user_notif = status_map[action]
        updated_row = update_murojaat_status(murojaat_id, new_status)
        if updated_row:
            try:
                bot.edit_message_text(
                    f"{esc(call.message.text)}\n\n📌 <b>YANGI HOLAT ({esc(murojaat_id)}): {esc(new_status)}</b>",
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="HTML",
                )
            except Exception:
                pass

            try:
                target_uid = int(updated_row["Telegram_ID"])
                bot.send_message(
                    target_uid,
                    localize_text(
                        target_uid,
                        f"🔔 <b>Murojaat holati yangilandi (ID: {esc(murojaat_id)})</b>\n\n{esc(user_notif)}",
                    ),
                    parse_mode="HTML",
                )

                # CSAT 5-yulduzli baholash
                if action == "ok":
                    csat_markup = types.InlineKeyboardMarkup(row_width=5)
                    csat_markup.row(
                        types.InlineKeyboardButton("⭐ 1", callback_data=f"csat_{murojaat_id}_1"),
                        types.InlineKeyboardButton("⭐ 2", callback_data=f"csat_{murojaat_id}_2"),
                        types.InlineKeyboardButton("⭐ 3", callback_data=f"csat_{murojaat_id}_3"),
                        types.InlineKeyboardButton("⭐ 4", callback_data=f"csat_{murojaat_id}_4"),
                        types.InlineKeyboardButton("⭐ 5", callback_data=f"csat_{murojaat_id}_5"),
                    )
                    bot.send_message(
                        target_uid,
                        localize_text(
                            target_uid,
                            f"⭐ <b>Ijtimoiy xodim xizmati sifatini baholang!</b>\n\n"
                            f"Hurmatli fuqaro, sizning <b>{esc(murojaat_id)}</b> raqamli murojaatingiz ko'rib chiqildi va ijobiy hal etildi.\n\n"
                            "Shayxali MFY ijtimoiy xodimi xizmat sifatini 1 dan 5 gacha baholashingizni so'raymiz:",
                            f"⭐ <b>Оцените качество обслуживания соцработника!</b>\n\n"
                            f"Ваше обращение <b>{esc(murojaat_id)}</b> успешно разрешено.\n\n"
                            "Пожалуйста, оцените работу соцработника от 1 до 5 звёзд:",
                        ),
                        reply_markup=csat_markup,
                        parse_mode="HTML",
                    )
            except Exception as e:
                print("Fuqaroga status xabarini yuborishda xatolik:", e)


def process_admin_direct_reply(message):
    if message.text and message.text.strip() == "/cancel":
        bot.send_message(message.chat.id, "❌ Жавоб ёзиш бекор қилинди.")
        admin_state.pop(message.from_user.id, None)
        return

    murojaat_id = admin_state.get(message.from_user.id, {}).get("reply_murojaat_id")
    if not murojaat_id or not message.text:
        return

    javob_matni = message.text.strip()
    # Javob murojaatni yopmaydi (xodim hujjat so'rashi mumkin): yakuniy qarorni tugma bilan belgilaydi
    current = get_murojaat_by_id(murojaat_id) or {}
    new_status = current.get("Status") if current.get("Status") in ["Hal etildi", "Rad etildi", "Yopildi"] else "O'rganilmoqda"
    updated_row = update_murojaat_status(murojaat_id, new_status, admin_izohi=javob_matni)
    if updated_row:
        try:
            target_uid = int(updated_row["Telegram_ID"])
            cit_fio = updated_row.get("FIO") or "Фуқаро"
            reply_text = (
                f"👨‍💼 <b>Шайх-Али МФЙ ижтимоий ходими (А. Жўраев) жавоби:</b>\n\n"
                f"{esc(javob_matni)}\n\n"
                f"📌 <i>Мурожаат рақами: #{esc(murojaat_id)}</i>"
            )
            send_split_message(
                chat_id=target_uid,
                text=reply_text,
                parse_mode="HTML",
            )
            bot.send_message(
                message.chat.id,
                f"✅ Жавобингиз фуқарога ({esc(cit_fio)}) юборилди ва базага сақланди (ID: #{esc(murojaat_id)}).\n"
                f"📌 Ҳолати: <b>{esc(new_status)}</b>. Якуний қарор бўлса, қуйидаги тугмани босинг:",
                reply_markup=get_murojaat_admin_buttons(murojaat_id),
                parse_mode="HTML",
            )
        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ Фуқарога юборишда хатолик: {e}")
        admin_state.pop(message.from_user.id, None)
@bot.callback_query_handler(func=lambda call: call.data.startswith("csat_"))
def handle_csat_callback(call):
    parts = call.data.split("_")
    if len(parts) >= 3:
        murojaat_id = parts[1]
        try:
            score = int(parts[2])
        except ValueError:
            score = 0
        appeal = database.get_murojaat_by_id(murojaat_id)
        if not 1 <= score <= 5 or not appeal or str(appeal.get("Telegram_ID")) != str(call.from_user.id):
            bot.answer_callback_query(call.id, "⚠️ Baholash imkoni yo'q.", show_alert=True)
            return
        database.save_murojaat_rating(murojaat_id, score)
        bot.answer_callback_query(call.id, f"Bahoyingiz qabul qilindi: {score} ⭐")
        stars_str = "⭐" * score
        bot.edit_message_text(
            localize_text(
                call.from_user.id,
                f"🙏 <b>Katta rahmat!</b>\n\nSiz bergan baho: <b>{score} ta yulduz ({stars_str})</b>.\n"
                "Sizning fikringiz Shayxali MFY ijtimoiy xizmat sifatini oshirishga xizmat qiladi.",
                f"🙏 <b>Большое спасибо!</b>\n\nВаша оценка: <b>{score} зв. ({stars_str})</b>.\n"
                "Ваш отзыв помогает повышать качество социальных услуг.",
            ),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
        )



# ==============================================================================
# 12. FUQARO SAVOLLARINI TAHLIL QILISH VA ADMINGA YO'NALTIRISH (SMART PRIORITET)
# ==============================================================================
def generate_grounded_ai_output(question: str, lang: str) -> str:
    """
    Savolni hujjatlar bazasiga tayangan holda AI ga yuboradi va teglangan xom javobni qaytaradi.
    AI ishlamasa, savol ijtimoiy xodim navbatiga tushadigan (SHAXSIY_MUROJAAT) javob qaytadi.
    """
    toza_savol = tozalash_regex(question)
    # Fuqaro kirillda yozgan bo'lsa ham, qidiruv aniqligi uchun lotinga o'giramiz
    toza_savol_lat = cyrillic_to_latin_uz(toza_savol)
    top_legal_chunks = search_knowledge_base(toza_savol_lat, top_k=2)
    legal_context = format_legal_grounding_prompt(toza_savol, top_legal_chunks)

    if lang == "ru":
        lang_instruction = "\n[Tizim eslatmasi: Fuqaroga javobni RUS tilida yoz!]"
    else:
        lang_instruction = (
            "\n[Тизим эслатмаси: Фуқаро саволини қайси ёзувда (кирилл ёки лотин) берганидан қатъи назар, "
            "жавобни ФАҚАТ ЎЗБЕК КИРИЛЛ АЛИФБОСИДА (Ў, Қ, Ғ, Ҳ ҳарфлари билан), "
            "имло меъёрларига риоя қилган ҳолда ёз! Ҳеч қандай лотин ҳарфларини аралаштирма!]"
        )

    try:
        return call_ai_strict(toza_savol + legal_context + lang_instruction).text or ""
    except Exception as e:
        print("AI xatosi, zaxira javobga o'tilmoqda:", e)

    # AI javob bermadi: savol yo'qolmasligi uchun ijtimoiy xodim ko'rib chiqadigan murojaat bo'ladi
    if top_legal_chunks:
        c = top_legal_chunks[0]
        fb_text = (
            f"📜 <b>Rasmiy hujjatdan havola ({esc(c.get('filename'))}):</b>\n\n"
            f"{esc(c.get('content'))}\n\n"
            "<i>Savolingiz bo'yicha amaliy yordam olish uchun ijtimoiy xodimga (+998 91 454 53 51) murojaat qiling.</i>"
        )
    else:
        fb_text = (
            "📨 <b>Мурожаатингиз қабул қилинди!</b>\n"
            "Ушбу масала бўйича Шайх-Али МФЙ ижтимоий ходими (А. Жўраев) сиз билан тез орада боғланади.\n"
            "📞 Телефон: <b>+998 91 454 53 51</b>"
        )
    return f"[TURI: SHAXSIY_MUROJAAT]\n[MUHIMLIK: ODDIY]\n---\n{fb_text}"


def answer_citizen_question(question: str, user_id, lang: str) -> dict:
    """Mini App suhbati uchun bot bilan bir xil javob oqimi: avval mahalliy baza, keyin hujjatga tayangan AI."""
    handled, turi, muhimlik, answer = try_local_answer(question, user_id)
    source = "local"
    if not handled:
        source = "ai"
        turi, muhimlik, answer = parse_ai_output(generate_grounded_ai_output(question, lang), question)
    if lang != "ru":
        answer = latin_to_cyrillic_uz(answer)
    return {"turi": turi, "muhimlik": muhimlik, "answer": answer, "source": source}


def process_and_dispatch_question(message, citizen: dict, original_question: str, ai_raw_output: str = None, force_personal: bool = False, progress_msg_id: int = None):
    """
    Fuqaro savolini tahlil qiladi.
    1-bosqich: Mahalliy Python qonuniy maslahatchisi (Token Saver) orqali 0 ta token sarflab javob berish.
    2-bosqich: Murakkab, noaniq yoki qiyin vaziyatlardagina AI (Gemini) ga minimal token sarflab murojaat qilish.
    XAVFSIZLIK: Fuqaroning shaxsiy ma'lumotlari AI ga YUBORILMAYDI!
    """
    user_id = message.from_user.id
    lang = get_user_lang(user_id)
    is_local_handled = False

    if ai_raw_output is None and not force_personal:
        handled_locally, loc_turi, loc_muhimlik, loc_ans = try_local_answer(original_question, user_id)
        if handled_locally:
            is_local_handled = True
            turi = loc_turi
            muhimlik = loc_muhimlik
            ai_javobi = loc_ans
            ai_raw_output = f"[TURI: {turi}]\n[MUHIMLIK: {muhimlik}]\n---\n{loc_ans}"

    if ai_raw_output is None:
        ai_raw_output = generate_grounded_ai_output(original_question, lang)

    if not is_local_handled:
        turi, muhimlik, ai_javobi = parse_ai_output(ai_raw_output, original_question)
        if lang != "ru":
            ai_javobi = latin_to_cyrillic_uz(ai_javobi)

    if force_personal:
        turi = "SHAXSIY_MUROJAAT"

    # Eslatma: ai_javobi parse_ai_output() ichida allaqachon xavfsiz Telegram HTML va
    # <blockquote expandable=""> ko'rinishiga keltirilgan!
    if turi == "SHAXSIY_MUROJAAT":
        status_excel = "Kutmoqda"
        kirish_qismi = (
            "📨 <b>Мурожаатингиз қабул қилинди!</b>\n"
            "Ижтимоий ходим (А. Жўраев) ҳолатни индивидуал ўрганиб, сизга тез орада маълумот беради.\n\n"
            "📋 <b>Дастлабки ҳуқуқий маълумот:</b>\n"
        )
        fuqaroga_javob = kirish_qismi + ai_javobi
    else:
        status_excel = "Mahalliy baza orqali javob berildi" if is_local_handled else "AI orqali javob berildi"
        fuqaroga_javob = ai_javobi

    # 1. Excel bazaga yozish
    murojaat_id = save_murojaat(
        user_id=user_id,
        savol=original_question,
        ai_javobi=re.sub(r"<[^>]+>", "", ai_javobi),
        turi=turi,
        muhimlik=muhimlik,
        status=status_excel,
    )

    # Tahlil jarayoni yakunlangani sababli oraliq progress xabarini tozalash
    if progress_msg_id:
        safe_delete_message(message.chat.id, progress_msg_id)

    # 2. Fuqaroga javob qaytarish (Standart sarlavha: 🤖 AI Yordamchi:)
    header_ai = "🤖 <b>AI Yordamchi:</b>"
    if turi == "SHAXSIY_MUROJAAT":
        if lang == "ru":
            reply_msg = f"{header_ai}\n\n🆔 <b>Номер обращения: {esc(murojaat_id)}</b>\n\n{fuqaroga_javob}"
        else:
            reply_msg = f"{header_ai}\n\n🆔 <b>Мурожаат рақами: {esc(murojaat_id)}</b>\n\n{latin_to_cyrillic_uz(fuqaroga_javob)}"
    else:
        # 1-ҲОЛАТ: УМУМИЙ МАЪЛУМОТ, ТУШУНЧА ЁКИ ҲУҚУҚИЙ САВОЛЛАР
        # Қатъиян "ID Мурожаат рақами", "1-Қадам, 2-Қадам" қўшилмайди!
        if lang == "ru":
            reply_msg = f"{header_ai}\n\n{fuqaroga_javob}"
        else:
            reply_msg = f"{header_ai}\n\n{latin_to_cyrillic_uz(fuqaroga_javob)}"
    send_split_message(
        chat_id=message.chat.id,
        text=reply_msg,
        reply_to_message_id=message.message_id,
        reply_markup=get_user_main_menu(user_id),
        parse_mode="HTML",
    )

    # 3. Adminga avtomatik bildirishnoma (Smart Prioritet va Identifikatsiya holati bilan)
    is_verified = bool(
        citizen
        and str(citizen.get("Status", "")).strip() == "Tasdiqlangan"
        and citizen.get("FIO")
        and str(citizen.get("FIO")).strip() not in ["Noma'lum", "Nomalum", "Hurmatli fuqaro", "Fuqaro", ""]
    )
    q_preview = original_question if len(original_question) <= 1500 else (original_question[:1500] + "\n... (savolning to'liq qismi bazada)")

    if not is_verified:
        # Identifikatsiyadan o'tmagan fuqaro murojaati (Ortiqcha "Nomalum" qatorlarisiz ixcham format)
        tg_user = message.from_user
        u_name = f"{tg_user.first_name or ''} {tg_user.last_name or ''}".strip() or "Noma'lum"
        u_username = f"@{tg_user.username}" if tg_user.username else "yo'q"
        shosh_belgi = "🚨 " if muhimlik == "SHOSHILINCH" else ""
        admin_notif = (
            f"📩 <b>{shosh_belgi}YANGI MUROJAAT (Identifikatsiyadan o'tmagan fuqaro)</b>\n\n"
            f"🆔 <b>Murojaat ID:</b> {esc(murojaat_id)}\n"
            f"👤 <b>Telegram:</b> {esc(u_name)} ({esc(u_username)})\n"
            f"🆔 <b>TG ID:</b> <code>{user_id}</code>\n"
            f"⚠️ <b>Holati:</b> Identifikatsiyadan o'tmagan fuqaro murojaati\n"
            f"⚡ <b>Muhimlik darajasi:</b> {esc(muhimlik)}\n"
            f"📌 <b>Ijro holati:</b> {esc(status_excel)}\n\n"
            f"❓ <b>Fuqaro savoli:</b>\n{esc(q_preview)}"
        )
    else:
        # Identifikatsiyadan o'tgan fuqaro murojaati
        if muhimlik == "SHOSHILINCH":
            header = "🚨🚨 <b>SHOSHILINCH MUROJAAT! (Birinchi navbatda ko'rib chiqing)</b> 🚨🚨"
        elif turi == "SHAXSIY_MUROJAAT":
            header = "📩 <b>YANGI SHAXSIY MUROJAAT (Ijtimoiy xodim o'rganishi kerak)</b>"
        else:
            header = "🤖 <b>YANGI SAVOL (AI orqali qonuniy tushuntirish berildi)</b>"

        doc_info = citizen.get("Pasport_JSHSHIR") or citizen.get("Pasport_Seriya") or ""
        kocha = citizen.get("Kocha_Manzil") or citizen.get("Manzil_Geolokatsiya") or "Shayxali MFY"
        cit_fio = citizen.get("FIO") or "Fuqaro"
        cit_phone = citizen.get("Telefon") or ""

        admin_notif = (
            f"{header}\n\n"
            f"🆔 <b>Murojaat ID:</b> {esc(murojaat_id)}\n"
            f"👤 <b>Fuqaro:</b> {esc(cit_fio)} (✅ Tasdiqlangan)\n"
        )
        if cit_phone and cit_phone not in ["Nomalum", "Noma'lum"]:
            admin_notif += f"📞 <b>Telefon:</b> {esc(cit_phone)}\n"
        if doc_info and doc_info not in ["Nomalum", "Noma'lum", "Kiritilmagan"]:
            admin_notif += f"🛂 <b>Pasport/JShShIR:</b> {esc(doc_info)}\n"
        admin_notif += (
            f"🏘 <b>Manzil:</b> {esc(kocha)}\n"
            f"⚡ <b>Muhimlik darajasi:</b> {esc(muhimlik)}\n"
            f"📌 <b>Ijro holati:</b> {esc(status_excel)}\n\n"
            f"❓ <b>Fuqaro savoli:</b>\n{esc(q_preview)}"
        )

    send_split_message(
        chat_id=ADMIN_ID,
        text=admin_notif,
        reply_markup=get_murojaat_admin_buttons(murojaat_id),
        parse_mode="HTML",
    )


# ==============================================================================
# 12-A. QO'SHIMCHA MODULLAR: TIL, ELEKTRON NAVBAT, SLA ESLATMA VA KALKULYATOR
# ==============================================================================

# --- 1) TIL VA ALIFBO TANLASH (Lotin / Кирилл / Русский) ---
def show_language_selection(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🇺🇿 Ўзбекча (Кирилл)", callback_data="setlang_uz_cyr"),
        types.InlineKeyboardButton("🇷🇺 Русский язык", callback_data="setlang_ru"),
    )
    bot.send_message(
        chat_id,
        "🔤 <b>Мулоқот тилини танланг / Выберите язык общения:</b>",
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("setlang_"))
def handle_set_language_callback(call):
    user_id = call.from_user.id
    lang_code = call.data.replace("setlang_", "")
    set_user_lang(user_id, lang_code)
    bot.answer_callback_query(call.id, "✅ Til ózgartirildi!")

    if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
        try:
            tma_user_url = f"{WEB_APP_URL}?user_id={user_id}&lang={lang_code}" if ("?" not in WEB_APP_URL) else f"{WEB_APP_URL}&user_id={user_id}&lang={lang_code}"
            bot.set_chat_menu_button(
                call.message.chat.id,
                types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=tma_user_url))
            )
        except Exception:
            pass

    msg_map = {
        "uz_lat": "✅ Muloqot tili: <b>Ózbekça (Yangi Lotin)</b> etib belgilandi.",
        "uz_cyr": "✅ Мулоқот тили: <b>Ўзбекча (Кирилл)</b> этиб белгиланди.",
        "ru": "✅ Язык общения изменён на: <b>Русский язык</b>.",
    }
    bot.send_message(
        call.message.chat.id,
        msg_map.get(lang_code, "✅ OK"),
        reply_markup=get_user_main_menu(user_id),
        parse_mode="HTML",
    )


# --- 2) QABULGA ONLAYN YOZILISH (ELEKTRON NAVBAT) ---
def show_queue_days_menu(chat_id, user_id):
    if str(database.get_setting("queue_open", "1")) != "1":
        reason = database.get_setting("queue_closed_reason", "") or ""
        bot.send_message(
            chat_id,
            localize_text(
                user_id,
                f"🔴 <b>Қабулга ёзилиш вақтинча ёпиқ.</b>\n\n{esc(reason)}",
                f"🔴 <b>Запись на приём временно закрыта.</b>\n\n{esc(reason)}",
            ),
            parse_mode="HTML",
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    today = datetime.now()
    added = 0
    for i in range(1, 10):
        d = today + timedelta(days=i)
        if d.weekday() < 5:  # Dushanba (0) - Juma (4)
            d_str = d.strftime("%d.%m.%Y")
            kun_nomi = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma"][d.weekday()]
            markup.add(types.InlineKeyboardButton(f"📅 {d_str} ({kun_nomi})", callback_data=f"qday_{d_str}"))
            added += 1
            if added >= 5:
                break

    bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "📅 <b>Shayxali MFY ijtimoiy xodimi (A. Jo'rayev) qabuliga onlayn yozilish</b>\n\n"
            "O'zingizga qulay qabul kunini tanlang:",
            "📅 <b>Онлайн-запись на приём к соцработнику махалли «Шайхали»</b>\n\n"
            "Выберите удобный день приёма:",
        ),
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("qday_"))
def handle_queue_day_select(call):
    user_id = call.from_user.id
    q_day = call.data.replace("qday_", "")
    bot.answer_callback_query(call.id)

    slots = ["09:00 - 10:00", "10:00 - 11:00", "11:00 - 12:00", "14:00 - 15:00", "15:00 - 16:00", "16:00 - 17:00"]
    booked = database.get_booked_slots(q_day)

    markup = types.InlineKeyboardMarkup(row_width=2)
    for s in slots:
        if database.normalize_time_slot(s) in booked:
            markup.add(types.InlineKeyboardButton(f"❌ {s} (Band)", callback_data="qslot_busy"))
        else:
            markup.add(types.InlineKeyboardButton(f"🕒 {s}", callback_data=f"qslot_{q_day}_{s}"))

    bot.edit_message_text(
        localize_text(
            user_id,
            f"📅 <b>Tanlangan sana: {esc(q_day)}</b>\nBo'sh qabul soatlaridan birini tanlang:",
            f"📅 <b>Выбранная дата: {esc(q_day)}</b>\nВыберите свободное время приёма:",
        ),
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("qslot_"))
def handle_queue_slot_select(call):
    user_id = call.from_user.id
    if call.data == "qslot_busy":
        bot.answer_callback_query(call.id, "⚠️ Bu vaqt band qilingan, boshqa soatni tanlang!", show_alert=True)
        return

    _, q_day, q_time = call.data.split("_", 2)
    citizen = get_citizen_by_tg_id(user_id) or {}

    if str(database.get_setting("queue_open", "1")) != "1":
        bot.answer_callback_query(call.id, "🔴 Qabulga yozilish vaqtincha yopiq.", show_alert=True)
        return

    # Bot va Mini App bitta navbat jadvalidan foydalanadi: band vaqtni baza atomik tekshiradi
    try:
        navbat_id = database.save_navbat(
            telegram_id=user_id,
            fio=citizen.get("FIO") or "Noma'lum",
            telefon=citizen.get("Telefon") or "Noma'lum",
            kocha=citizen.get("Kocha_Manzil") or "Noma'lum",
            qabul_kuni=q_day,
            qabul_soati=q_time,
        )
    except ValueError as e:
        bot.answer_callback_query(call.id, f"⚠️ {str(e)[:180]}", show_alert=True)
        return

    bot.answer_callback_query(call.id, "✅ Qabulga yozildingiz!")
    bot.edit_message_text(
        localize_text(
            user_id,
            f"✅ <b>Siz qabulga muvaffaqiyatli yozildingiz!</b>\n\n"
            f"🎟 <b>Navbat talon raqamingiz:</b> <code>{navbat_id}</code>\n"
            f"📅 <b>Sana:</b> {esc(q_day)}\n"
            f"🕒 <b>Vaqt:</b> {esc(q_time)}\n"
            f"📍 <b>Manzil:</b> Shayxali MFY binosi (Ijtimoiy xodim A. Jo'rayev xonasi)\n\n"
            f"<i>Iltimos, belgilangan vaqtdan 5 daqiqa oldin shaxsni tasdiqlovchi hujjatingiz bilan keling.</i>",
            f"✅ <b>Вы успешно записаны на приём!</b>\n\n"
            f"🎟 <b>Номер талона:</b> <code>{navbat_id}</code>\n"
            f"📅 <b>Дата:</b> {esc(q_day)}\n"
            f"🕒 <b>Время:</b> {esc(q_time)}\n"
            f"📍 <b>Адрес:</b> Здание МСГ «Шайхали» (кабинет соцработника А. Жураева)",
        ),
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML",
    )

    try:
        bot.send_message(
            ADMIN_ID,
            f"📅 <b>YANGI ELEKTRON NAVBAT ({navbat_id})</b>\n\n"
            f"👤 <b>Fuqaro:</b> {esc(citizen.get('FIO', 'Nomalum'))}\n"
            f"📞 <b>Telefon:</b> {esc(citizen.get('Telefon', 'Nomalum'))}\n"
            f"🏘 <b>Manzil:</b> {esc(citizen.get('Kocha_Manzil', 'Nomalum'))}\n"
            f"🗓 <b>Qabul vaqti:</b> {esc(q_day)} | {esc(q_time)}",
            parse_mode="HTML",
        )
    except Exception:
        pass


# --- 3) MUDDATI O'TAYOTGAN MUROJAATLAR ESLATMASI (SLA > 24 SOAT) ---
def check_overdue_appeals(notify_admin: bool = True):
    """24 soatdan beri ochiq turgan murojaatlarni topadi va Adminga eslatma yuboradi."""
    try:
        overdue_items = database.get_overdue_appeals(hours=24)
    except Exception as e:
        print("SLA tekshiruvida xatolik:", e)
        return []

    if notify_admin:
        for row in overdue_items:
            if row.get("Eslatma_Yuborildi") == "Ha":
                continue
            m_id = row.get("Murojaat_ID")
            try:
                bot.send_message(
                    ADMIN_ID,
                    f"⏰ <b>ESLATMA: Murojaatga 24 soatdan beri javob berilmadi!</b>\n\n"
                    f"🆔 <b>ID:</b> {esc(m_id)} ({esc(row.get('Sana'))})\n"
                    f"👤 <b>Fuqaro:</b> {esc(row.get('FIO'))} ({esc(row.get('Telefon'))})\n"
                    f"❓ <b>Savol:</b> {esc((row.get('Savol') or '')[:1500])}",
                    reply_markup=get_murojaat_admin_buttons(m_id),
                    parse_mode="HTML",
                )
                database.mark_appeal_reminder_sent(m_id)
            except Exception as e:
                print("SLA eslatmasini yuborishda xatolik:", e)
    return overdue_items


def sla_background_worker():
    """Har 1 soatda muddati o'tayotgan murojaatlarni avtomatik tekshirib turuvchi oqim."""
    while True:
        time.sleep(3600)
        check_overdue_appeals(notify_admin=True)


def backup_background_worker():
    """Bazaning kunlik zaxirasini oladi; eski zaxiralarni backup_database() o'zi tozalaydi."""
    while True:
        try:
            database.backup_if_due(max_age_hours=24)
        except Exception as e:
            print("Avtomatik zaxira olishda xatolik:", e)
        time.sleep(6 * 3600)


# --- 4) NAFAQA VA BOLA PULI KALKULYATORI (SHAXSIY MA'LUMOTSIZ VA AI'SIZ) ---
OGIR_VAZIYAT_VARIANTLARI = {
    "ogir_1": "I va (yoki) II guruh nogironligi bo'lgan shaxs yoxud bolalikdan nogironligi bo'lgan shaxs bor oila",
    "ogir_2": "Boquvchisini yo'qotgan yoki bolasini yolg'iz tarbiyalayotgan oila",
    "ogir_3": "O'zgalar parvarishiga muhtoj bo'lgan yolg'iz yashovchi hamda yolg'iz shaxs",
    "ogir_4": "Oila a'zosi muddatli harbiy xizmatda yoki jazoni ijro etish muassasasida bo'lgan oila",
    "ogir_5": "Oila a'zosi psixiatriya, narkologiya, sil kasalliklari dispanserida bo'lgan yoki onkologiya markazlarida ro'yxatda bo'lgan yoxud gematologiya, immunologiya, jigar, buyrak yetishmovchiligi kabi og'ir kasallikka chalingan oila a'zosi mavjud oila",
    "ogir_6": "Yong'in, baxtsiz hodisa, tabiiy yoki texnogen favqulodda vaziyatlardan jabrlangan oila",
    "ogir_0": "Yuqoridagilarning hech biri mavjud emas",
}


def start_nafaqa_calculator(chat_id, user_id):
    """
    Kalkulyatorni boshlash.
    XAVFSIZLIK: Hech qanday shaxsiy ma'lumot so'ralmaydi va Gemini AI ga yuborilmaydi.
    """
    calc_state[user_id] = {
        "oila_soni": 0,
        "jami_daromad": 0,
        "norasmiy_bandlar": 0,
        "avtolar": [],
        "buqa_sigir": 0,
        "yosh_qoramol": 0,
        "ot_tuya": 0,
        "chochqa": 0,
        "qoy_echki": 0,
        "katta_parranda": 0,
        "yosh_parranda": 0,
        "yer_sotix": 0.0,
        "noturar_joy": 0,
        "ogir_vaziyat": "",
    }

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "🧮 <b>NAFAQA VA MODDIY YORDAM EHTIMOLIY KALKULYATORI</b>\n\n"
            "🔒 <i>Eslatma: Ushbu bo'limda shaxsiy ma'lumotlar (ism, pasport, JShShIR) so'ralmaydi. "
            "Faqat raqamlar kiritiladi.</i>\n\n"
            "1️⃣ <b>Oilangiz a'zolarining umumiy sonini kiriting (faqat raqamda, masalan: <code>5</code>):</b>",
        ),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_family_size)


def parse_non_negative_int(text: str):
    cleaned = re.sub(r"[^\d]", "", str(text or ""))
    return int(cleaned) if cleaned.isdigit() else None


def calc_step_family_size(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    chat_id = message.chat.id
    val = parse_non_negative_int(message.text)
    if val is None or val <= 0 or val > 30:
        msg = bot.send_message(chat_id, "⚠️ Iltimos, oila a'zolari sonini to'g'ri raqamda kiriting (Masalan: <code>4</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_family_size)
        return

    calc_state[user_id]["oila_soni"] = val
    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "2️⃣ <b>Oilangizning barcha a'zolarining 1 oylik jami rasmiy daromadini (ish haqi, pensiya, stipendiya va b.) so'mda kiriting:</b>\n"
            "<i>(Faqat raqamda, masalan: <code>2000000</code> yoki daromad bo'lmasa <code>0</code>)</i>",
        ),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_income)


def calc_step_income(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    chat_id = message.chat.id
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(chat_id, "⚠️ Iltimos, oylik daromadni faqat raqamda kiriting (Masalan: <code>1500000</code> yoki <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_income)
        return

    calc_state[user_id]["jami_daromad"] = val

    bandlik_matni = (
        "3️⃣ <b>18 YOSHDAN KATTA MEHNATGA LAYOQATLI A'ZOLARNING RASMIY BANDLIGI:</b>\n\n"
        "Oilangizda 18 yoshdan katta mehnatga layoqatli, ammo <b>RASMIY ISHLAMAYDIGAN (norasmiy band / ishsiz)</b> a'zolar necha nafar?\n\n"
        "ℹ️ <b>Muhim istisno:</b> Quyidagi shaxslar uzrli (rasmiy bandga tenglashtirilgan) hisoblanadi, ularni bu songa QO'SHMANG:\n"
        "• Chet elda oliy ta'lim muassasasi talabasi <i>(o'qishning faqat kunduzgi shakli bo'lganida)</i>;\n"
        "• Chaqiriq bo'yicha harbiy xizmatni o'tashi sababli oilada bo'lmagan shaxs;\n"
        "• Harbiy ta'lim muassasasida ta'lim olishi sababli oilada bo'lmagan shaxslar;\n"
        "• O'zbekiston Respublikasi Mudofaa vazirligi, Ichki ishlar vazirligi, Favqulodda vaziyatlar vazirligi, Davlat xavfsizlik xizmati, O'zbekiston Respublikasi Prezidenti Davlat xavfsizlik xizmati, Milliy gvardiya, Iqtisodiyot va moliya vazirligi huzuridagi Bojxona qo'mitasi, Mudofaa vazirligi huzuridagi Mudofaa sanoati agentligi hamda ularning tizimidagi tashkilotlar xizmatchilari va xodimlari hamda pensionerlari;\n"
        "• Chet elda yoki O'zbekistonda jazoni ijro etish muassasasida bo'lganligi munosabati bilan oilada bo'lmagan shaxs;\n"
        "• 3 yoshgacha bola parvarishidagi onalar hamda I–II guruh nogironligi bo'lgan shaxslar.\n\n"
        "👉 Yuqoridagi istisnolardan tashqari, <b>uzrsiz rasmiy ishlamaydigan 18 yoshdan katta a'zolar sonini</b> faqat raqamda kiriting <i>(Masalan: barcha rasmiy ishlasa <code>0</code>, 1 kishi ishsiz bo'lsa <code>1</code>)</i>:"
    )
    msg = bot.send_message(chat_id, localize_text(user_id, bandlik_matni), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_unemployed)


def calc_step_unemployed(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    chat_id = message.chat.id
    val = parse_non_negative_int(message.text)
    if val is None or val > 20:
        msg = bot.send_message(chat_id, "⚠️ Iltimos, faqat raqamda kiriting (Masalan: <code>0</code> yoki <code>1</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_unemployed)
        return

    calc_state[user_id]["norasmiy_bandlar"] = val
    show_calc_vehicle_prompt(chat_id, user_id)


def show_calc_vehicle_prompt(chat_id, user_id):
    avto_list = calc_state.get(user_id, {}).get("avtolar", [])
    avto_info = ""
    if avto_list:
        avto_info = "\n<b>Qo'shilgan avtotransportlar:</b>\n" + "\n".join(
            [f"• {a['turi']} ({a['yili']}-yil)" for a in avto_list]
        ) + "\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("➕ Avtotransport qo'shish", callback_data="calc_add_car"),
        types.InlineKeyboardButton("➡️ Avtotransport yo'q / Keyingi qismga o'tish", callback_data="calc_next_livestock"),
    )

    text = (
        "4️⃣ <b>AVTOTRANSPORT QO'SHISH (Yuqori qism):</b>\n\n"
        "Arizachi va uning oila a'zolari nomiga rasmiylashtirilmagan, biroq <b>oilaning foydalanishida bo'lgan</b> "
        "(yoki o'z nomidagi) avtotransport vositalari haqida ma'lumot kiritiladi.\n"
        f"{avto_info}\n"
        "Avtotransport mavjud bo'lsa <b>«➕ Avtotransport qo'shish»</b> tugmasini bosing, "
        "mavjud bo'lmasa <b>«➡️ Keyingi qismga o'tish»</b> tugmasini bosing:"
    )
    bot.send_message(chat_id, localize_text(user_id, text), reply_markup=markup, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data in ["calc_add_car", "calc_next_livestock"])
def handle_calc_car_callbacks(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "calc_add_car":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🚗 Yengil avtotransport", callback_data="cartype_Yengil avtotransport"),
            types.InlineKeyboardButton("🚚 Yuk avtotransporti / Mikroavtobus", callback_data="cartype_Yuk avtotransporti"),
            types.InlineKeyboardButton("🚜 Qishloq xo'jaligi texnikasi", callback_data="cartype_Maxsus texnika"),
        )
        bot.edit_message_text(
            localize_text(user_id, "🚗 <b>Avtotransport turini tanlang:</b>"),
            chat_id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
    else:
        ask_livestock_step_1(chat_id, user_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cartype_"))
def handle_calc_cartype_select(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    car_type = call.data.replace("cartype_", "")
    calc_state.setdefault(user_id, {}).setdefault("avtolar", [])
    calc_state[user_id]["temp_car_type"] = car_type
    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            f"📅 <b>{esc(car_type)} ishlab chiqarilgan yilini kiriting (faqat 4 xonali raqamda, masalan: <code>2018</code>):</b>",
        ),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_car_year)


def calc_step_car_year(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    chat_id = message.chat.id
    val = parse_non_negative_int(message.text)
    current_year = datetime.now().year
    if val is None or val < 1950 or val > current_year + 1:
        msg = bot.send_message(chat_id, "⚠️ Ishlab chiqarilgan yilni 4 xonali son shaklida kiriting (Masalan: <code>2020</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_car_year)
        return

    c_type = calc_state.get(user_id, {}).get("temp_car_type", "Yengil avtotransport")
    calc_state.setdefault(user_id, {}).setdefault("avtolar", []).append({"turi": c_type, "yili": val})
    show_calc_vehicle_prompt(chat_id, user_id)


# --- Pastki qism: Chorva mollari, parrandalar, yer sotixi va noturar joylar ---
def ask_livestock_step_1(chat_id, user_id):
    """
    Kalkulyatorda 6 xil chorvani bittalab 0 yozib o'tirishning oldini olish:
    Avval umumiy chorva mavjudligi so'raladi. Yo'q bo'lsa, barchasi 0 qilinib, to'g'ri yer maydoniga o'tiladi.
    """
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Ha, chorva bor", callback_data="calc_chorva_ha"),
        types.InlineKeyboardButton("❌ Yo'q, chorva yo'q", callback_data="calc_chorva_yoq"),
    )
    markup.add(types.InlineKeyboardButton("🔙 Bekor qilish", callback_data="calc_cancel"))
    bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "5️⃣ <b>UY XO'JALIGINING MAVJUD CHORVA MOLLARI VA PARRANDALARI:</b>\n\n"
            "Uy xo'jaligingizda (oila a'zolaringiz nomida) qoramol, ot, qo'y, echki yoki parranda mavjudmi?\n\n"
            "<i>(Agar chorva bo'lmasa, «❌ Yo'q, chorva yo'q» tugmasini bosing — tizim barcha chorvalarni 0 deb hisoblab, to'g'ridan-to'g'ri yer maydoniga o'tadi)</i>",
            "5️⃣ <b>НАЛИЧИЕ СКОТА И ПТИЦЫ:</b>\n\n"
            "Имеется ли в вашем домохозяйстве скот или птица?\n\n"
            "<i>(Если нет, нажмите «❌ Yo'q, chorva yo'q»)</i>",
        ),
        reply_markup=markup,
        parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data in ["calc_chorva_ha", "calc_chorva_yoq", "calc_cancel"])
def handle_calc_livestock_choice(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "calc_cancel":
        calc_state.pop(user_id, None)
        safe_delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "❌ Kalkulyator hisob-kitobi bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return

    safe_delete_message(chat_id, call.message.message_id)

    if call.data == "calc_chorva_yoq":
        # Barcha chorvalarni 0 deb olamiz va to'g'ri yer maydoniga o'tamiz
        calc_state.setdefault(user_id, {})
        calc_state[user_id]["buqa_sigir"] = 0
        calc_state[user_id]["yosh_qoramol"] = 0
        calc_state[user_id]["ot_tuya"] = 0
        calc_state[user_id]["chochqa"] = 0
        calc_state[user_id]["qoy_echki"] = 0
        calc_state[user_id]["katta_parranda"] = 0
        calc_state[user_id]["yosh_parranda"] = 0
        ask_yer_sotix_step(chat_id, user_id)
    else:
        # Ha, chorva bor — so'rashni boshlaymiz
        msg = bot.send_message(
            chat_id,
            localize_text(
                user_id,
                "🐂 <b>Buqa va sigirlar sonini kiriting</b> (faqat raqamda, yo'q bo'lsa <code>0</code>):",
            ),
            reply_markup=get_cancel_reply_keyboard(),
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, calc_step_buqa_sigir)


def ask_yer_sotix_step(chat_id, user_id):
    msg = bot.send_message(
        chat_id,
        localize_text(
            user_id,
            "🌱 <b>Sug'oriladigan bog' va dehqon xo'jaligi yerlari maydonini kiriting (sotixda, faqat raqamda, masalan: <code>6</code> yoki <code>0</code>):</b>",
            "🌱 <b>Введите площадь орошаемых земель/сада (в сотках, например: <code>6</code> или <code>0</code>):</b>",
        ),
        reply_markup=get_cancel_reply_keyboard(),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_yer_sotix)


def calc_step_buqa_sigir(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code> yoki <code>2</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_buqa_sigir)
        return
    calc_state[user_id]["buqa_sigir"] = val
    msg = bot.send_message(message.chat.id, localize_text(user_id, "🐮 <b>Yosh qoramollar sonini kiriting</b> (yo'q bo'lsa <code>0</code>):"), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_yosh_qoramol)


def calc_step_yosh_qoramol(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_yosh_qoramol)
        return
    calc_state[user_id]["yosh_qoramol"] = val
    msg = bot.send_message(message.chat.id, localize_text(user_id, "🐎 <b>Ot va tuyalar sonini kiriting</b> (yo'q bo'lsa <code>0</code>):"), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_ot_tuya)


def calc_step_ot_tuya(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_ot_tuya)
        return
    calc_state[user_id]["ot_tuya"] = val
    msg = bot.send_message(message.chat.id, localize_text(user_id, "🐖 <b>Katta yoshdagi cho'chqalar sonini kiriting</b> (yo'q bo'lsa <code>0</code>):"), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_chochqa)


def calc_step_chochqa(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_chochqa)
        return
    calc_state[user_id]["chochqa"] = val
    msg = bot.send_message(message.chat.id, localize_text(user_id, "🐑 <b>Qo'ylar va echkilar sonini kiriting</b> (yo'q bo'lsa <code>0</code>):"), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_qoy_echki)


def calc_step_qoy_echki(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_qoy_echki)
        return
    calc_state[user_id]["qoy_echki"] = val
    msg = bot.send_message(message.chat.id, localize_text(user_id, "🐓 <b>Katta yoshdagi va yosh parrandalar jami sonini kiriting</b> (yo'q bo'lsa <code>0</code>):"), parse_mode="HTML")
    bot.register_next_step_handler(msg, calc_step_parranda)


def calc_step_parranda(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_parranda)
        return
    calc_state[user_id]["katta_parranda"] = val
    msg = bot.send_message(
        message.chat.id,
        localize_text(
            user_id,
            "🌱 <b>Sug'oriladigan bog' va dehqon xo'jaligi yerlari maydonini kiriting (sotixda, faqat raqamda, masalan: <code>6</code> yoki <code>0</code>):</b>",
        ),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_yer_sotix)


def calc_step_yer_sotix(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(message.chat.id, "⚠️ Yer maydonini sotixda faqat raqam bilan kiriting (masalan: <code>4</code> yoki <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_yer_sotix)
        return
    calc_state[user_id]["yer_sotix"] = float(val)
    msg = bot.send_message(
        message.chat.id,
        localize_text(
            user_id,
            "🏢 <b>Daromad olib keluvchi noturar joylar (do'kon, ustaxona, ombor va b.) sonini kiriting</b> (yo'q bo'lsa <code>0</code>):",
        ),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, calc_step_noturar_joy)


def calc_step_noturar_joy(message):
    user_id = message.from_user.id
    if is_cancel_message(message):
        calc_state.pop(user_id, None)
        bot.send_message(message.chat.id, "❌ Kalkulyator bekor qilindi.", reply_markup=get_user_main_menu(user_id))
        return
    chat_id = message.chat.id
    val = parse_non_negative_int(message.text)
    if val is None:
        msg = bot.send_message(chat_id, "⚠️ Faqat raqamda kiriting (masalan: <code>0</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, calc_step_noturar_joy)
        return
    calc_state[user_id]["noturar_joy"] = val

    # 6-qadam: Og'ir hayotiy vaziyat yuzaga kelganligi bo'yicha asoslar
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("1️⃣ I–II guruh nogironi / bolalikdan nogiron bor oila", callback_data="ogir_1"),
        types.InlineKeyboardButton("2️⃣ Boquvchisini yo'qotgan / yolg'iz ona (ota) oilasi", callback_data="ogir_2"),
        types.InlineKeyboardButton("3️⃣ O'zgalar parvarishiga muhtoj yolg'iz shaxs", callback_data="ogir_3"),
        types.InlineKeyboardButton("4️⃣ Oila a'zosi muddatli harbiy xizmatda / Jazoni ijro etishda", callback_data="ogir_4"),
        types.InlineKeyboardButton("5️⃣ Og'ir kasallikka chalingan (onkologiya, sil va b.) a'zosi bor oila", callback_data="ogir_5"),
        types.InlineKeyboardButton("6️⃣ Yong'in, tabiiy yoki texnogen favqulodda vaziyatdan jabrlangan", callback_data="ogir_6"),
        types.InlineKeyboardButton("➖ Yuqoridagilarning hech biri mavjud emas", callback_data="ogir_0"),
    )

    text = (
        "6️⃣ <b>OG'IR HAYOTIY VAZIYAT YUZAGA KELGANLIGI BO'YICHA ASOSLAR MAVJUDLIGI (toifalarning biri belgilanadi):</b>\n\n"
        "• <b>1:</b> I va (yoki) II guruh nogironligi bo'lgan shaxs yoxud bolalikdan nogironligi bo'lgan shaxs bor oila;\n"
        "• <b>2:</b> Boquvchisini yo'qotgan yoki bolasini yolg'iz tarbiyalayotgan oila;\n"
        "• <b>3:</b> O'zgalar parvarishiga muhtoj bo'lgan yolg'iz yashovchi hamda yolg'iz shaxs;\n"
        "• <b>4:</b> Oila a'zosi muddatli harbiy xizmatda yoki jazoni ijro etish muassasasida bo'lgan oila;\n"
        "• <b>5:</b> Oila a'zosi psixiatriya, narkologiya, sil kasalliklari dispanserida bo'lgan yoki onkologiya markazlarida ro'yxatda bo'lgan yoxud gematologiya, immunologiya, jigar, buyrak yetishmovchiligi kabi og'ir kasallikka chalingan oila a'zosi mavjud oila;\n"
        "• <b>6:</b> Yong'in, baxtsiz hodisa, tabiiy yoki texnogen favqulodda vaziyatlardan jabrlangan oila.\n\n"
        "👇 <b>Oilangizga mos keladigan bandni tanlang:</b>"
    )
    bot.send_message(chat_id, localize_text(user_id, text), reply_markup=markup, parse_mode="HTML")


def evaluate_calculator_result(data: dict, ogir_code: str) -> str:
    """Kiritilgan raqamlar asosida qonuniy mezonlarni hisoblab, HTML xulosa qaytaradi."""
    ogir_nomi = OGIR_VAZIYAT_VARIANTLARI.get(ogir_code, "")
    oila_soni = max(1, data.get("oila_soni", 1))
    rasmiy_daromad = data.get("jami_daromad", 0)
    norasmiy_bandlar = data.get("norasmiy_bandlar", 0)
    avtolar = data.get("avtolar", [])
    noturar = data.get("noturar_joy", 0)

    chorva_daromad = (
        data.get("buqa_sigir", 0) * 320000
        + data.get("yosh_qoramol", 0) * 150000
        + data.get("ot_tuya", 0) * 350000
        + data.get("chochqa", 0) * 200000
        + data.get("qoy_echki", 0) * 65000
        + data.get("katta_parranda", 0) * 8000
    )
    yer_daromad = data.get("yer_sotix", 0.0) * 45000
    jami_hisoblangan_daromad = rasmiy_daromad + chorva_daromad + yer_daromad
    jon_boshiga_daromad = jami_hisoblangan_daromad / oila_soni

    salbiy_sabablar = []

    # 1. 18 yoshdan katta mehnatga layoqatli a'zolarning rasmiy bandligi
    if norasmiy_bandlar > 0:
        salbiy_sabablar.append(
            f"❌ <b>Rasmiy bandlik mezoni bajarilmagan:</b> Oilada 18 yoshdan katta mehnatga layoqatli, "
            f"uzrli sababsiz rasmiy ishlamaydigan <b>{norasmiy_bandlar} nafar</b> a'zo mavjud (VM 654-son qaroriga ko'ra mehnatga layoqatli a'zolar rasmiy band bo'lishi shart)."
        )

    # 2. Noturar joy mavjudligi
    if noturar > 0:
        salbiy_sabablar.append(
            f"❌ <b>Noturar joy mavjudligi:</b> Oilada daromad olib keluvchi <b>{noturar} ta</b> noturar joy mavjud."
        )

    # 3. Avtotransport mezoni
    current_year = datetime.now().year
    yosh_cheklov = 12 if ogir_code == "ogir_1" else 7
    if len(avtolar) >= 2:
        salbiy_sabablar.append(
            f"❌ <b>Avtotransport soni:</b> Oilaning foydalanishida <b>{len(avtolar)} ta</b> avtotransport vositasi mavjud (2 va undan ortiq texnika bo'lganda rad etiladi)."
        )
    for a in avtolar:
        if (current_year - a["yili"]) < yosh_cheklov:
            salbiy_sabablar.append(
                f"❌ <b>Yangi avtotransport vositasi:</b> {esc(a['turi'])} ({a['yili']}-yil) ishlab chiqarilganiga {yosh_cheklov} yil to'lmagan."
            )

    # 4. Jon boshiga daromad mezoni
    if jon_boshiga_daromad > MINIMAL_ISTEMOL_XARAJATI:
        salbiy_sabablar.append(
            f"❌ <b>Daromad mezoni:</b> Oilaning jon boshiga to'g'ri keladigan o'rtacha oylik shartli daromadi "
            f"(<b>{int(jon_boshiga_daromad):,} so'm</b>) minimal iste'mol xarajatlari mezonidan (<b>{MINIMAL_ISTEMOL_XARAJATI:,} so'm</b>) yuqori."
        )

    if salbiy_sabablar:
        natija_sarlavha = "🔴 <b>TAHLIL NATIJASI: SALBIY (Rad etilish ehtimoli yuqori)</b>"
        sabablar_matni = "\n".join(salbiy_sabablar)
    else:
        natija_sarlavha = "🟢 <b>TAHLIL NATIJASI: IJOBIY EHTIMOL (Mezonlarga mos keladi)</b>"
        sabablar_matni = (
            "✅ Kiritilgan raqamlar bo'yicha oilangizda asosiy rad etuvchi omillar (bandlik, avtotransport, noturar joy va daromad oshib ketishi) aniqlanmadi."
        )

    ogir_izoh = ""
    if ogir_code != "ogir_0":
        ogir_izoh = (
            f"\n\n📌 <b>Og'ir hayotiy vaziyat bo'yicha qo'shimcha ma'lumot:</b>\n"
            f"Siz <i>«{esc(ogir_nomi)}»</i> toifasini belgiladingiz. Vazirlar Mahkamasining 442-son qaroriga muvofiq, "
            f"ushbu toifadagi oilalar mahalla ijtimoiy xodimi (A. Jo'rayev) va «mahalla beshligi» tomonidan joyiga chiqib individual o'rganilishi mumkin."
        )

    qat_iy_ogohlantirish = (
        "\n\n🚨 <b>MUHIM HUQUQIY OGOHLANTIRISH (DIQQAT BILAN O'QING!):</b>\n"
        "1. Ushbu kalkulyator natijasi <b>HECH QANDAY HAQIQIY YOKI 100% RASMIY NATIJA EMAS!</b>\n"
        "2. Mazkur bot <b>hech qanday davlat axborot tizimlari</b> («Ijtimoiy himoya yagona reestri», Soliq, Kadastr, YHXX, Bank va Pensiya bazalari) bilan integratsiyaga ega emas.\n"
        "3. Bot faqat siz kiritgan raqamlar asosida <b>taxminiy (ehtimoliy) hisob-kitob</b> qiladi va ushbu xabar nafaqa yoki moddiy yordam talab qilish uchun <b>QONUNIY ASOS BO'LA OLMAYDI!</b>\n"
        "4. Nafaqa tayinlash yoki rad etish faqatgina rasmiy ariza topshirilgach, davlat elektron axborot tizimlari tomonidan avtomatik tarzda belgilanadi."
    )

    return (
        f"📊 <b>KALKULYATOR TAHLILI XULOSASI</b>\n\n"
        f"{natija_sarlavha}\n\n"
        f"• <b>Oila a'zolari soni:</b> {oila_soni} nafar\n"
        f"• <b>Kiritilgan rasmiy daromad:</b> {rasmiy_daromad:,} so'm\n"
        f"• <b>Chorva va yerdan shartli oylik daromad:</b> {int(chorva_daromad + yer_daromad):,} so'm\n"
        f"• <b>Jon boshiga o'rtacha oylik daromad:</b> {int(jon_boshiga_daromad):,} so'm <i>(Mezon: {MINIMAL_ISTEMOL_XARAJATI:,} so'm)</i>\n"
        f"• <b>18+ uzrsiz rasmiy ishlamaydiganlar:</b> {norasmiy_bandlar} nafar\n"
        f"• <b>Avtotransportlar:</b> {len(avtolar)} ta | <b>Noturar joylar:</b> {noturar} ta\n\n"
        f"📋 <b>Huquqiy tahlil tafsiloti:</b>\n{sabablar_matni}"
        f"{ogir_izoh}"
        f"{qat_iy_ogohlantirish}"
    )


@bot.callback_query_handler(func=lambda call: call.data in OGIR_VAZIYAT_VARIANTLARI)
def handle_calc_final_analysis(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    data = calc_state.get(user_id)
    if not data:
        bot.send_message(chat_id, "⚠️ Ma'lumotlar topilmadi. Iltimos, kalkulyatorni qaytadan boshlang.")
        return

    hisobot = evaluate_calculator_result(data, call.data)
    bot.send_message(
        chat_id,
        localize_text(user_id, hisobot),
        parse_mode="HTML",
        reply_markup=get_user_main_menu(user_id),
    )


# ==============================================================================
# 12.5. TELEGRAM MINI APP (TMA) INTEGRATSIYASI VA HODISALARI
# ==============================================================================
@bot.callback_query_handler(func=lambda call: call.data == "tma_info")
def handle_tma_info_callback(call):
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
        markup.add(types.InlineKeyboardButton("🚀 Mini App ни очиш", web_app=types.WebAppInfo(url=WEB_APP_URL)))

    info_text = (
        "📱 <b>Shayxali MFY Telegram Mini App (TMA) Imkoniyatlari:</b>\n\n"
        "1️⃣ <b>Interaktiv Nafaqa Kalkulyatori:</b> Bir zumda daromad va chorva ko'rsatkichlarini hisoblash.\n"
        "2️⃣ <b>AI Huquqiy Maslahatchi:</b> Rasmiy me'yoriy hujjatlar asosida suhbat.\n"
        "3️⃣ <b>Elektron Navbat:</b> Bo'sh kun va soatni tanlab, navbat talonini olish.\n"
        "4️⃣ <b>Arizalar Monitori:</b> Barcha rasmiy murojaatlaringiz holati va CSAT baholash.\n"
        "5️⃣ <b>Tezkor Tasdiqlash:</b> O'RQ-547 bo'yicha rasm va videosiz 4 qadamli faollashtirish.\n\n"
        "<i>Mini App dan Telegram ichida yoki pastdagi tugma orqali foydalanishingiz mumkin.</i>"
    )
    bot.send_message(call.message.chat.id, info_text, reply_markup=markup, parse_mode="HTML")


@bot.message_handler(content_types=['web_app_data'])
def handle_web_app_data(message):
    """Mini App ichidan Telegram.WebApp.sendData() orqali kelgan ma'lumotlar."""
    try:
        user_id = message.from_user.id
        raw_data = message.web_app_data.data
        data = json.loads(raw_data)
        act = data.get("action", "")

        if act == "appeal":
            bot.send_message(
                message.chat.id,
                "✅ <b>Murojaatingiz Mini App orqali muvaffaqiyatli qabul qilindi!</b>\n"
                "Ijtimoiy xodim holatni o'rganib, tez orada siz bilan bog'lanadi.",
                parse_mode="HTML"
            )
        elif act == "queue":
            slot = data.get("time_slot", "")
            dt = data.get("date", "")
            bot.send_message(
                message.chat.id,
                f"🎟 <b>Elektron navbat band qilindi!</b>\n\n"
                f"📅 <b>Sana:</b> {dt}\n"
                f"⏰ <b>Vaqt:</b> {slot}\n"
                f"📍 <b>Manzil:</b> Shayxali MFY binosi",
                parse_mode="HTML"
            )
        elif act == "verify":
            bot.send_message(
                message.chat.id,
                "✅ <b>Shaxsingiz Mini App orqali tasdiqlandi!</b>\n"
                "Endi barcha xizmatlardan cheklovlarsiz foydalanishingiz mumkin.",
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                message.chat.id,
                "✅ <b>Mini App ma'lumoti muvaffaqiyatli saqlandi!</b>",
                parse_mode="HTML"
            )
    except Exception as e:
        print("web_app_data qayta ishlash xatosi:", e)


# ==============================================================================
# 13. ASOSIY MATNLI XABARLAR VA MENYU TUGMALARI HANDLERI
# ==============================================================================
@bot.message_handler(func=lambda message: True, content_types=["text"])
def handle_user_questions(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = (message.text or "").strip()

    # Admin Ijtimoiy AI-konsultanti yoki Bilimlar bazasiga matn yuborayotgan bo'lsa
    if is_admin(user_id) and admin_ai_assistant.handle_admin_ai_message(bot, message, admin_state, is_admin, get_admin_panel_menu):
        return

    # Admin boshqaruv klaviaturasi tugmalari bosilganda
    if is_admin(user_id):
        if text in ["⚙️ Бошқарув панели", "/admin", "бошқарув панели"]:
            handle_admin_command(message)
            return

        if text in ["🧠 AI Ёрдамчи", "AI Ёрдамчи"]:
            admin_state[user_id] = {"action": "waiting_for_ai_case"}
            cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            cancel_markup.add(types.KeyboardButton("🔙 Бекор қилиш"))
            msg_text = (
                "🧠 <b>ИЖТИМОИЙ ХОДИМ AI-КОНСУЛЬТАНТИ (МУАММО ЕЧИМИ)</b>\n\n"
                "Фуқаро муаммоси, кейс тавсифи, ариза матни ёки фотосуратини юборинг:\n\n"
                "💡 <b>Мисол:</b> <i>«Фуқаро О. Каримова 2 нафар фарзанди билан турмуш ўртоғи томонидан уйдан ҳайдалган, доимий даромади йўқ...»</i>\n\n"
                "<i>(Бекор қилиш учун 🔙 Бекор қилиш ёки /cancel)</i>"
            )
            bot.send_message(chat_id, msg_text, reply_markup=cancel_markup, parse_mode="HTML")
            return

        if text in ["⚙️ Тизим созламалари", "/sozlamalar", "тизим созламалари"]:
            show_admin_settings_panel(chat_id)
            return

        if text in ["📊 Статистика", "статистика"]:
            bot.send_message(chat_id, format_system_stats_html(), parse_mode="HTML")
            return

        if text in ["🔍 Фуқарони қидириш", "фуқарони қидириш"]:
            msg = bot.send_message(chat_id, "🔍 <b>Қидирилаётган фуқаро исми, фамилияси, ЖШШИР ёки кўча номини киритинг:</b>", parse_mode="HTML")
            bot.register_next_step_handler(msg, process_admin_search_step)
            return

        if text in ["📥 Excel базани юклаш", "excel юклаш"]:
            bot.send_message(chat_id, "📥 <b>Excel ҳисоботи шакллантирилмоқда...</b>", parse_mode="HTML")
            send_full_excel_report(chat_id)
            return

    # Bekor qilish tugmasi bosilganda asosiy menyuni chiqarish
    if is_cancel_message(message):
        user_data.pop(user_id, None)
        calc_state.pop(user_id, None)
        bot.send_message(
            chat_id,
            localize_text(user_id, "Асосий меню:", "Главное меню:"),
            reply_markup=get_user_main_menu(user_id),
        )
        return

    # 0. Mini App tugmasi bosilganda
    if "mini app" in text.lower() or "мини апп" in text.lower():
        markup = types.InlineKeyboardMarkup()
        if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
            markup.add(types.InlineKeyboardButton("📱 Мини Аппни очиш (TMA)", web_app=types.WebAppInfo(url=WEB_APP_URL)))
            msg_t = (
                "📱 <b>Шайх-Али МФЙ Телеграм Мини Апп (TMA):</b>\n\n"
                "Интерактив калькулятор, расмий мурожаат, электрон навбат ва AI маслаҳатчидан "
                "замонавий дастур кўринишида фойдаланиш учун қуйидаги тугмани босинг:"
            )
        else:
            msg_t = (
                "📱 <b>Шайх-Али МФЙ Телеграм Мини Апп тизими фаол!</b>\n\n"
                "Илтимос, чап пастдаги <b>📱 Мини Апп</b> тугмасини босинг."
            )
        bot.send_message(chat_id, msg_t, reply_markup=markup if markup.keyboard else None, parse_mode="HTML")
        return

    # Tilni o'zgartirish tugmasi — barcha uchun ochiq!
    if text == "🔤 Til / Язык":
        show_language_selection(chat_id)
        return

    # 1. "Savol yo'llash / Murojaat qilish" tugmasi bosilganda — Xavfsizlik ogohlantirishi
    if text in ["📝 Savol yóllaş / Murojaat qiliş", "📝 Savol yo'llash / Murojaat qilish", "📝 Савол йўллаш / Мурожаат қилиш", "📝 Задать вопрос / Обращение"]:
        user_data.setdefault(user_id, {})["force_personal"] = False
        bot.send_message(message.chat.id, localize_text(user_id, PRIVACY_WARNING_TEXT), parse_mode="HTML")
        return

    # 2. "Ijtimoiy xodim bilan bog'lanish" tugmasi bosilganda — Ikki bosqichli tekshiruv
    if text in [
        "👨‍💼 Ijtimoiy xodim bilan boǵlaniş", "👨‍💼 Ijtimoiy xodim bilan bog'lanish",
        "👨💼 Ijtimoiy xodim bilan boǵlaniş", "👨💼 Ijtimoiy xodim bilan bog'lanish",
        "👨‍💼 Ижтимоий ходим билан боғланиш", "👨‍💼 Связь с соцработником"
    ]:
        if not is_citizen_verified(user_id):
            prompt_citizen_verification(chat_id, user_id, reason="murojaat")
            return
        user_data.setdefault(user_id, {})["force_personal"] = True
        bot.send_message(
            message.chat.id,
            localize_text(
                user_id,
                "👨‍💼 <b>Shayxali MFY ijtimoiy xodimi (A. Jo'rayev) ga bevosita murojaat yuborish</b>\n\n"
                "📞 <b>Telefon:</b> <code>+998 91 454 53 51</code>\n"
                "📍 <b>Manzil:</b> Shayxali MFY idorasi\n"
                "🕒 <b>Qabul vaqti:</b> Dushanba – Juma (09:00 – 18:00)\n\n"
                + PRIVACY_WARNING_TEXT,
                "👨‍💼 <b>Прямая связь с соцработником МСГ «Шайхали» (А. Жураев)</b>\n\n"
                "📞 <b>Телефон:</b> <code>+998 91 454 53 51</code>\n"
                "📍 <b>Адрес:</b> Здание МСГ «Шайхали»\n"
                "🕒 <b>Время приёма:</b> Понедельник – Пятница (09:00 – 18:00)\n\n"
                + PRIVACY_WARNING_TEXT,
            ),
            parse_mode="HTML",
        )
        return

    # 3. "Tezkor savollar" tugmasi bosilganda — API'siz tayyor tugmalar
    if text in ["📋 Tezkor savollar", "📋 Тезкор саволлар", "📋 Частые вопросы"]:
        bot.send_message(
            message.chat.id,
            localize_text(
                user_id,
                "📋 <b>Eng ko'p beriladigan savollar:</b>\nKerakli mavzuni tanlang va soniyalarda qonuniy ma'lumot oling:",
                "📋 <b>Часто задаваемые вопросы:</b>\nВыберите нужную тему:",
            ),
            reply_markup=get_faq_inline_menu(),
            parse_mode="HTML",
        )
        return

    # 4. "Manzillar" tugmasi bosilganda -> Mini App ga yo'naltirish
    if text in ["📍 Manzillar", "📍 Манзиллар", "📍 Адреса и контакты"]:
        markup = types.InlineKeyboardMarkup()
        if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
            markup.add(types.InlineKeyboardButton("📍 Манзилларни очиш (Мини Апп)", web_app=types.WebAppInfo(url=WEB_APP_URL)))
        bot.send_message(
            message.chat.id,
            "📍 <b>Шайх-Али МФЙ манзиллари ва ишонч телефонлари:</b>\n\n"
            "Ушбу маълумотлар тўлиқ <b>Телеграм Мини Апп</b>га жойлаштирилган. "
            "Қуйидаги тугма ёки чап пастдаги <b>📱 Мини Апп</b> орқали кўришингиз мумкин.",
            reply_markup=markup if markup.keyboard else None,
            parse_mode="HTML"
        )
        return

    # 5. "Qabulga onlayn yozilish (Elektron navbat)" tugmasi bosilganda — Ikki bosqichli tekshiruv
    if text in ["📅 Qabulga onlayn yozilish", "📅 Қабулга онлайн ёзилиш", "📅 Запись на приём"]:
        if not is_citizen_verified(user_id):
            prompt_citizen_verification(chat_id, user_id, reason="qabul")
            return
        show_queue_days_menu(message.chat.id, user_id)
        return

    # 6. "Nafaqa va bola puli kalkulyatori" tugmasi bosilganda -> Mini App ga yo'naltirish
    if text in ["🧮 Nafaqa va bola puli kalkulyatori", "🧮 Нафақа ва бола пули калькулятори", "🧮 Калькулятор пособий"]:
        markup = types.InlineKeyboardMarkup()
        if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
            markup.add(types.InlineKeyboardButton("🧮 Калькуляторни очиш (Мини Апп)", web_app=types.WebAppInfo(url=WEB_APP_URL)))
        bot.send_message(
            message.chat.id,
            "🧮 <b>Нафақа ва Бола пули калькулятори:</b>\n\n"
            "Калькулятор интерактив кўринишда (жонли ҳисоблаш ва хулосалар билан) тўлиқ <b>Телеграм Мини Апп</b>га кўчирилди. "
            "Қуйидаги тугма ёки чап пастдаги <b>📱 Мини Апп</b> менюси орқали ҳисоблашингиз мумкин.",
            reply_markup=markup if markup.keyboard else None,
            parse_mode="HTML"
        )
        return

    # 7. "Murojaatim holati" tugmasi bosilganda — Status tracking
    if text in ["🔍 Murojaatim holati", "🔍 Мурожаатим ҳолати", "🔍 Статус обращения"]:
        user_appeals = database.get_citizen_appeals(user_id, limit=5)
        if not user_appeals:
            bot.send_message(
                message.chat.id,
                localize_text(
                    user_id,
                    "📭 Сизда ҳозирча юборилган мурожаатлар мавжуд эмас. Савол юбориш учун <b>«📝 Савол йўллаш / Мурожаат қилиш»</b> тугмасини босинг.",
                    "📭 У вас пока нет отправленных обращений.",
                ),
                parse_mode="HTML",
            )
            return

        status_lines = ["🔍 <b>СИЗНИНГ ОХИРГИ МУРОЖААТЛАРИНГИЗ ҲОЛАТИ:</b>\n"]
        for row in user_appeals:
            st = esc(row.get("Status", "Кутмоқда"))
            izoh = esc(row.get("Admin_Izohi") or "")
            raw_savol = row.get("Savol") or ""
            savol_qisqa = esc((raw_savol[:70] + "...") if len(raw_savol) > 70 else raw_savol)
            block = (
                f"🆔 <b>{esc(row.get('Murojaat_ID'))}</b> ({esc(row.get('Sana'))})\n"
                f"❓ <i>{savol_qisqa}</i>\n"
                f"📌 <b>Ҳолати:</b> {st}"
            )
            if izoh:
                block += f"\n💬 <b>Ижтимоий ходим жавоби:</b> {izoh}"
            status_lines.append(block)

        send_split_message(
            chat_id=message.chat.id,
            text=localize_text(user_id, "\n\n".join(status_lines)),
            parse_mode="HTML",
        )
        return

    # 8. Oddiy savol yoki murojaat matni yuborilganda -> Gemini AI + Admin bildirishnomasi
    # 8.1. Anti-Spam (Rate Limiter himoyasi): 1 daqiqada ko'pi bilan 3 ta savol!
    limited, wait_sec = is_rate_limited(user_id, max_requests=3, window_seconds=60)
    if limited:
        bot.send_message(
            chat_id,
            localize_text(
                user_id,
                f"🛡️ <b>Iltimos, biroz kuting!</b>\n\n"
                f"Tizim xavfsizligi va barcha fuqarolarga teng xizmat ko'rsatish maqsadida 1 daqiqada ko'pi bilan 3 ta savol yo'llash mumkin.\n\n"
                f"⏳ <i>Iltimos, yana <b>{wait_sec} soniyadan</b> keyin savolingizni yuboring.</i>",
                f"🛡️ <b>Пожалуйста, подождите!</b>\n\n"
                f"Разрешено не более 3 вопросов в минуту.\n\n"
                f"⏳ <i>Попробуйте через <b>{wait_sec} сек.</b></i>",
            ),
            parse_mode="HTML",
        )
        return

    # Фойдаланувчи сўровини (Лотин ёки Кирилл) тўлиқ Кирилл ёзувига ўгириш
    question_cyr = latin_to_cyrillic_uz(text)

    bot.send_chat_action(message.chat.id, "typing")
    force_personal = user_data.get(user_id, {}).get("force_personal", False)
    if user_id in user_data:
        user_data[user_id]["force_personal"] = False

    # Fuqaroga tahlil jarayoni boshlanganini darhol ko'rsatish (Interaktiv status)
    progress_msg = None
    try:
        progress_text = get_analysis_progress_message(question_cyr, user_id)
        progress_msg = bot.reply_to(message, progress_text, parse_mode="HTML")
    except Exception:
        pass

    try:
        citizen_obj = get_citizen_by_tg_id(user_id) or {}
        process_and_dispatch_question(
            message=message,
            citizen=citizen_obj,
            original_question=question_cyr,
            force_personal=force_personal,
            progress_msg_id=progress_msg.message_id if progress_msg else None,
        )
    except Exception as e:
        if progress_msg:
            safe_delete_message(message.chat.id, progress_msg.message_id)
        print("Murojaatni qayta ishlash xatosi:", e)
        send_split_message(
            chat_id=message.chat.id,
            text="⚠️ Tizimda kichik texnik uzilish yuz berdi. Murojaatingiz ijtimoiy xodimga yozib olindi, iltimos birozdan so'ng qayta urinib ko'ring.",
            reply_to_message_id=message.message_id,
        )


_cf_process = None


def is_tunnel_alive(url, timeout=4):
    """URL ning haqiqatan ham jonli va ishlayotganini tekshirish (HTTP 200/302)."""
    if not url or not str(url).startswith("https://"):
        return False
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (IHMA-HealthCheck)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 301, 302, 304)
    except Exception:
        return False


def set_bot_menu_button_safe(url):
    """Telegram global Menu Button va admin tugmasini xavfsiz yangilash."""
    if not url or not str(url).startswith("https://"):
        return
    try:
        bot.set_chat_menu_button(
            chat_id=None,
            menu_button=types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=url))
        )
        if ADMIN_ID and str(ADMIN_ID).isdigit():
            bot.set_chat_menu_button(
                chat_id=int(ADMIN_ID),
                menu_button=types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=f"{url}?user_id={ADMIN_ID}&lang=uz_cyr"))
            )
        print(f"📱 Telegram global Menu Button (Мини Апп) muvaffaqiyatli o'rnatildi: {url}")
    except Exception as mb_err:
        print("Menu button o'rnatishda ogohlantirish:", mb_err)


def auto_ensure_tunnel(port=5001):
    """
    Agar WEB_APP_URL mavjud va jonli bo'lsa, uni ishlatadi.
    Aks holda cloudflared orqali yangi bepul HTTPS tunnel ochadi va Telegram Menu Button'ni yangilaydi.
    """
    global WEB_APP_URL, _cf_process

    if WEB_APP_URL and is_tunnel_alive(WEB_APP_URL):
        print(f"✅ Mavjud Mini App tunneli faol: {WEB_APP_URL}")
        set_bot_menu_button_safe(WEB_APP_URL)
        return WEB_APP_URL

    print("⚠️ Mini App URL nofaol yoki mavjud emas. Yangi Cloudflare HTTPS tunnel yaratilmoqda...")

    bin_paths = [
        os.path.join(BASE_DIR, "bin", "cloudflared"),
        os.path.expanduser("~/.gemini/antigravity/bin/cloudflared"),
        "/usr/local/bin/cloudflared",
        "/opt/homebrew/bin/cloudflared",
        "/usr/bin/cloudflared"
    ]
    cf_bin = None
    for p in bin_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            cf_bin = p
            break

    if not cf_bin:
        print("⚠️ cloudflared binar fayli topilmadi!")
        return WEB_APP_URL

    try:
        import subprocess

        if _cf_process and _cf_process.poll() is None:
            try:
                _cf_process.terminate()
                _cf_process.wait(timeout=5)
            except Exception:
                _cf_process.kill()

        cmd = [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{port}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        _cf_process = proc

        found = {}
        url_found = threading.Event()

        def _drain_tunnel_output():
            # Quvur to'lib qolsa cloudflared to'xtab qoladi, shuning uchun chiqishni oxirigacha o'qiymiz
            for line in proc.stdout:
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m and "url" not in found:
                    found["url"] = m.group(0)
                    url_found.set()

        threading.Thread(target=_drain_tunnel_output, daemon=True).start()
        url_found.wait(timeout=25)
        new_url = found.get("url")

        if new_url:
            WEB_APP_URL = new_url
            print(f"🚀 Telegram Mini App uchun yangi Cloudflare Tunnel faollashdi: {WEB_APP_URL}")
            set_bot_menu_button_safe(WEB_APP_URL)
        else:
            print("⚠️ Cloudflare tunnel URL topilmadi yoki vaqt tugadi.")

    except Exception as e:
        print("Tunnelni ishga tushirishda ogohlantirish:", e)

    return WEB_APP_URL


def tunnel_watchdog_worker(port=5001):
    """Orqa fonda doimiy ravishda tunnel faolligini nazorat qiluvchi posbon."""
    time.sleep(20)
    while True:
        try:
            if not is_tunnel_alive(WEB_APP_URL):
                print(f"⚠️ Mini App tunnel uzilgan yoki nofaol ({WEB_APP_URL}). Qayta tiklanmoqda...")
                auto_ensure_tunnel(port=port)
        except Exception as we:
            print("Tunnel watchdog xatoligi:", we)
        time.sleep(45)
# ==============================================================================
# 14. BOTNI ISHGA TUSHIRISH
# ==============================================================================
if __name__ == "__main__":
    # Windows tizimi uyqu rejimiga (Sleep) o'tib ketmasligini ta'minlash
    import sys
    if sys.platform == "win32":
        import ctypes
        # ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001)
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)

    # Telegram Mini App (Flask REST API va WebApp Server) ni orqa fonda ishga tushirish
    _setup_file_logging()
    tma_port = int(os.getenv("PORT", 5001))
    # cloudflared serverga mahalliy ulanadi: tashqi tarmoqqa ochish uchun WEBAPP_HOST=0.0.0.0 bering
    tma_host = os.getenv("WEBAPP_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        import webapp_server
        webapp_server.set_ai_backend(answer_citizen_question)
        webapp_server.set_lang_change_listener(user_lang_cache.__setitem__)
        webapp_server.start_server_in_background(host=tma_host, port=tma_port, bot=bot)
        print(f"🌐 Telegram Mini App serveri fon rejimida faol: http://{tma_host}:{tma_port}")
    except Exception as ws_err:
        print("⚠️ Mini App serverini ishga tushirishda ogohlantirish:", ws_err)

    # Avtomatik HTTPS Tunnel tekshirish yoki yaratish
    try:
        auto_ensure_tunnel(port=tma_port)
    except Exception as tunnel_err:
        print("⚠️ Tunnel sozlashda ogohlantirish:", tunnel_err)

    # Telegram global Menu Button (Mini App) ni o'rnatish
    if WEB_APP_URL and WEB_APP_URL.startswith("https://"):
        try:
            bot.set_chat_menu_button(
                chat_id=None,
                menu_button=types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=WEB_APP_URL))
            )
            if ADMIN_ID and str(ADMIN_ID).isdigit():
                bot.set_chat_menu_button(
                    chat_id=int(ADMIN_ID),
                    menu_button=types.MenuButtonWebApp(type="web_app", text="📱 Мини Апп", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?user_id={ADMIN_ID}&lang=uz_cyr"))
                )
            print(f"📱 Telegram global Menu Button (Мини Апп) muvaffaqiyatli o'rnatildi: {WEB_APP_URL}")
        except Exception as mb_err:
            print("Menu button o'rnatishda ogohlantirish:", mb_err)

    # Tunnel sog'lig'ini nazorat qiluvchi fondagi oqim
    tunnel_thread = threading.Thread(target=tunnel_watchdog_worker, args=(tma_port,), daemon=True)
    tunnel_thread.start()

    # Muddati o'tayotgan murojaatlarni har soatda tekshiruvchi orqa fon oqimi
    sla_thread = threading.Thread(target=sla_background_worker, daemon=True)
    sla_thread.start()

    # Bazaning kunlik avtomatik zaxirasi
    threading.Thread(target=backup_background_worker, daemon=True).start()

    print("✅ Shayxali MFY Ijtimoiy Xodim AI Agent boti to'liq ishga tushdi...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as poll_e:
            print(f"⚠️ Telegram bot polling to'xtadi: {poll_e}. 3 soniyadan so'ng avtomatik qayta ulanadi...")
            time.sleep(3)
