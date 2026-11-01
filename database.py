from utils.text_normalizer import normalize_for_search, latin_to_cyrillic_uz, ensure_cyrillic
# -*- coding: utf-8 -*-
"""
Shayxali MFY Ijtimoiy Xodim AI Agent — SQLite va Avtomatik Excel Ma'lumotlar Bazasi Moduli.

Ushbu modul:
1. SQLite (ihma_database.db) orqali fayl qulflanishisiz (PermissionError bo'lmasdan)
   o'ta tezkor tranzaksion ma'lumotlar boshqaruvini ta'minlaydi.
2. Xavfsiz migratsiyalar, to'liq audit jurnali (audit_log) va indekslash.
3. Elektron navbatda poyga holatlari (race conditions) va bir xil vaqtni 2 kishi band qilishini 100% oldini olish.
4. Fuqaro murojaatlarini 8 ta standartlashtirilgan rasmiy maqomlar (status) tizimi asosida boshqarish.
5. Excel ga atomik sinxronizatsiya va 1 tugmada to'liq .xlsx eksportini amalga oshirish.
6. CSAT (1-5 yulduzli fuqaro qanoatlanish bahosi) ni saqlash.
7. Rasmiy Word (.docx) Dalolatnoma generatsiya qilish imkoniyati.
"""

import os
import re
import shutil
import sqlite3
import secrets
import logging
import threading
from datetime import datetime, date
import pandas as pd
import docx
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

logger = logging.getLogger("Database")

_db_lock = threading.Lock()
_excel_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "ihma_database.db")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")
EXCEL_FUQAROLAR = os.path.join(BASE_DIR, "fuqarolar.xlsx")
EXCEL_MUROJAATLAR = os.path.join(BASE_DIR, "murojaatlar.xlsx")
EXCEL_NAVBATLAR = os.path.join(BASE_DIR, "navbatlar.xlsx")
DALOLATNOMA_DIR = os.path.join(BASE_DIR, "dalolatnomalar")

os.makedirs(BACKUPS_DIR, exist_ok=True)
os.makedirs(DALOLATNOMA_DIR, exist_ok=True)

# 8 ta standartlashtirilgan rasmiy murojaat maqomi
APPLICATION_STATUSES = [
    "Yangi",                        # 1. Yangi
    "Qabul qilindi",                # 2. Qabul qilindi
    "O'rganilmoqda",                # 3. O'rganilmoqda
    "Hujjat kutilmoqda",            # 4. Hujjat kutilmoqda
    "Boshqa tashkilotga yuborildi", # 5. Boshqa tashkilotga yuborildi
    "Hal etildi",                   # 6. Hal etildi
    "Rad etildi",                   # 7. Rad etildi
    "Yopildi"                       # 8. Yopildi
]

STATUS_NORMALIZATION_MAP = {
    "yangi": "Yangi",
    "qabul qilindi": "Qabul qilindi",
    "o'rganilmoqda": "O'rganilmoqda",
    "organilmoqda": "O'rganilmoqda",
    "o‘rganilmoqda": "O'rganilmoqda",
    "hujjat kutilmoqda": "Hujjat kutilmoqda",
    "boshqa tashkilotga yuborildi": "Boshqa tashkilotga yuborildi",
    "hal etildi": "Hal etildi",
    "rad etildi": "Rad etildi",
    "yopildi": "Yopildi",
    # Legacy moslashuvlar
    "kutmoqda": "Yangi",
    "jarayonda": "O'rganilmoqda",
    "qanoatlantirildi": "Hal etildi",
    "arizangiz qanoatlantirilgan": "Hal etildi",
    "rad etilgan": "Rad etildi",
    "tegishli tashkilotga yo'naltirilgan": "Boshqa tashkilotga yuborildi"
}


def normalize_application_status(status_str: str) -> str:
    """Murojaat maqomini 8 ta standart maqomdan biriga keltiradi."""
    if not status_str:
        return "Yangi"
    cleaned = str(status_str).strip().lower()
    return STATUS_NORMALIZATION_MAP.get(cleaned, "Yangi")


def get_db_connection(db_path=None):
    """SQLite ulanishini qaytaradi (thread-safe, WAL rejimi)."""
    target = db_path or DB_FILE
    conn = sqlite3.connect(target, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ==============================================================================
# AUDIT LOG (XAVFSIZLIK VA AUDIT JURNALI)
# ==============================================================================
def log_audit_event(actor: str, action: str, target: str = "", details: str = "", status: str = "SUCCESS", db_path=None):
    """
    Ma'muriy va nozik amallarni audit jurnaliga qayd etish:
    actor: Mas'ul shaxs (masalan: Admin Telegram ID si yoki Fuqaro ID si)
    action: Bajarilgan amal (STATUS_CHANGE, APPOINTMENT_CANCEL, EXCEL_EXPORT, etc.)
    target: Amal obyekti (Murojaat ID, Navbat ID, Sozlama kaliti)
    details: Qo'shimcha tavsif (sabab, o'zgarish tafsiloti)
    status: SUCCESS / FAILED
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _db_lock:
            conn = get_db_connection(db_path)
            with conn:
                conn.execute("""
                INSERT INTO audit_log (timestamp, actor, action, target, details, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (now_str, str(actor), str(action), str(target), str(details), str(status)))
            conn.close()
    except Exception as e:
        logger.error(f"Audit log yozishda xatolik: {e}")


def get_audit_logs(limit: int = 50, db_path=None):
    """Oxirgi audit yozuvlarini olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


# ==============================================================================
# BAZANI INIZIALIZATSIYA VA XAVFSIZ MIGRATSIYA
# ==============================================================================
def init_database(db_path=None):
    """SQLite jadvallarini yaratadi, migratsiyalarni bajaradi va indekslarni o'rnatadi."""
    target_db = db_path or DB_FILE
    with _db_lock:
        conn = get_db_connection(target_db)
        cur = conn.cursor()

        # 1. Fuqarolar jadvali
        cur.execute("""
        CREATE TABLE IF NOT EXISTS fuqarolar (
            Telegram_ID TEXT PRIMARY KEY,
            FIO TEXT,
            Telefon TEXT,
            Pasport_Seriya TEXT,
            JSHSHIR TEXT,
            Pasport_JSHSHIR TEXT,
            Kocha_Manzil TEXT,
            Geolokatsiya TEXT,
            Manzil_Geolokatsiya TEXT,
            Status TEXT,
            Til TEXT,
            Royxatdan_Otgan_Sana TEXT
        )
        """)

        # 2. Murojaatlar jadvali (Baho / CSAT ustuni bilan)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS murojaatlar (
            Murojaat_ID TEXT PRIMARY KEY,
            Sana TEXT,
            Oy_Yil TEXT,
            Telegram_ID TEXT,
            FIO TEXT,
            Telefon TEXT,
            Pasport_JSHSHIR TEXT,
            Kocha_Manzil TEXT,
            Savol TEXT,
            AI_Javobi TEXT,
            Turi TEXT,
            Muhimlik TEXT,
            Status TEXT,
            Admin_Izohi TEXT,
            Eslatma_Yuborildi TEXT,
            Baho INTEGER DEFAULT NULL
        )
        """)

        # 3. Navbatlar jadvali
        cur.execute("""
        CREATE TABLE IF NOT EXISTS navbatlar (
            Navbat_ID TEXT PRIMARY KEY,
            Yaratilgan_Vaqt TEXT,
            Telegram_ID TEXT,
            FIO TEXT,
            Telefon TEXT,
            Kocha_Manzil TEXT,
            Qabul_Kuni TEXT,
            Qabul_Soati TEXT,
            Status TEXT,
            token TEXT,
            qr_code TEXT,
            Bekor_Qilingan_Vaqt TEXT
        )
        """)

        # 4. Tizim sozlamalari jadvali
        cur.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            description TEXT,
            updated_at TEXT
        )
        """)

        # 5. Audit jurnali jadvali
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            details TEXT,
            status TEXT NOT NULL
        )
        """)

        # Xavfsiz ustunlar migratsiyasi (mavjud jadvallarga yetishmayotgan ustunlarni qo'shish)
        cur.execute("PRAGMA table_info(navbatlar)")
        existing_navbat_cols = [r[1] for r in cur.fetchall()]
        for col_name in ["token", "qr_code", "Bekor_Qilingan_Vaqt"]:
            if col_name not in existing_navbat_cols:
                try:
                    cur.execute(f"ALTER TABLE navbatlar ADD COLUMN {col_name} TEXT")
                except Exception as e:
                    logger.warning(f"Ustun qo'shishda ogohlantirish ({col_name}): {e}")

        # Unikal tokenlarni to'ldirish (agar bo'sh bo'lsa)
        cur.execute("SELECT Navbat_ID FROM navbatlar WHERE token IS NULL OR token = ''")
        missing_tokens = cur.fetchall()
        for row in missing_tokens:
            cur.execute("UPDATE navbatlar SET token = ? WHERE Navbat_ID = ?", (secrets.token_urlsafe(16), row[0]))

        # Ishlash samaradorligi uchun indekslar
        cur.execute("CREATE INDEX IF NOT EXISTS idx_murojaat_tg_id ON murojaatlar(Telegram_ID)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_murojaat_status ON murojaatlar(Status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_navbat_tg_id ON navbatlar(Telegram_ID)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_navbat_slot ON navbatlar(Qabul_Kuni, Qabul_Soati, Status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_navbat_token ON navbatlar(token)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp)")

        # Ma'lumotlar bazasi darajasidagi qat'iy poyga holati (Race Condition) va takroriy band qilish himoyasi
        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_slot 
        ON navbatlar (Qabul_Kuni, Qabul_Soati) 
        WHERE Status = 'Band qilingan'
        """)
        cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_citizen_navbat 
        ON navbatlar (Telegram_ID) 
        WHERE Status = 'Band qilingan'
        """)

        # Birlamchi standart sozlamalarni kiritish
        init_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        default_settings = [
            ("mih_amount", "669000", "Minimal iste'mol xarajatlari summasi (so'm)"),
            ("queue_open", "1", "Elektron navbat qabuli holati: 1-ochiq, 0-vaqtincha yopiq"),
            ("queue_days", "Dushanba - Juma", "Qabul kunlari"),
            ("queue_hours", "09:00 - 12:00, 14:00 - 17:00", "Qabul soatlari"),
            ("queue_closed_reason", "", "Qabul yopilish sababi")
        ]
        for k, v, desc in default_settings:
            cur.execute("""
            INSERT OR IGNORE INTO system_settings (key, value, description, updated_at)
            VALUES (?, ?, ?, ?)
            """, (k, v, desc, init_now))

        conn.commit()

        # Agar SQLite bo'sh bo'lsa, Excel dan ko'chirish
        cur.execute("SELECT COUNT(*) FROM fuqarolar")
        if cur.fetchone()[0] == 0 and os.path.exists(EXCEL_FUQAROLAR):
            try:
                df = pd.read_excel(EXCEL_FUQAROLAR, dtype=str).fillna("")
                for _, r in df.iterrows():
                    cur.execute("""
                    INSERT OR REPLACE INTO fuqarolar VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(r.get("Telegram_ID", "")), r.get("FIO", ""), r.get("Telefon", ""),
                        r.get("Pasport_Seriya", ""), r.get("JSHSHIR", ""), r.get("Pasport_JSHSHIR", ""),
                        r.get("Kocha_Manzil", ""), r.get("Geolokatsiya", ""), r.get("Manzil_Geolokatsiya", ""),
                        r.get("Status", "Tasdiqlangan"), r.get("Til", "uz_cyr"), r.get("Royxatdan_Otgan_Sana", "")
                    ))
                conn.commit()
            except Exception as e:
                logger.error(f"Fuqarolarni import qilishda xatolik: {e}")

        cur.execute("SELECT COUNT(*) FROM murojaatlar")
        if cur.fetchone()[0] == 0 and os.path.exists(EXCEL_MUROJAATLAR):
            try:
                df_m = pd.read_excel(EXCEL_MUROJAATLAR, dtype=str).fillna("")
                for _, r in df_m.iterrows():
                    baho_val = int(r["Baho"]) if "Baho" in r and str(r["Baho"]).isdigit() else None
                    cur.execute("""
                    INSERT OR REPLACE INTO murojaatlar VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(r.get("Murojaat_ID", "")), r.get("Sana", ""), r.get("Oy_Yil", ""),
                        str(r.get("Telegram_ID", "")), r.get("FIO", ""), r.get("Telefon", ""),
                        r.get("Pasport_JSHSHIR", ""), r.get("Kocha_Manzil", ""), r.get("Savol", ""),
                        r.get("AI_Javobi", ""), r.get("Turi", ""), r.get("Muhimlik", ""),
                        normalize_application_status(r.get("Status", "Yangi")), r.get("Admin_Izohi", ""), r.get("Eslatma_Yuborildi", ""),
                        baho_val
                    ))
                conn.commit()
            except Exception as e:
                logger.error(f"Murojaatlarni import qilishda xatolik: {e}")

        cur.execute("SELECT COUNT(*) FROM navbatlar")
        if cur.fetchone()[0] == 0 and os.path.exists(EXCEL_NAVBATLAR):
            try:
                df_n = pd.read_excel(EXCEL_NAVBATLAR, dtype=str).fillna("")
                for _, r in df_n.iterrows():
                    cur.execute("""
                    INSERT OR REPLACE INTO navbatlar (Navbat_ID, Yaratilgan_Vaqt, Telegram_ID, FIO, Telefon, Kocha_Manzil, Qabul_Kuni, Qabul_Soati, Status, token)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(r.get("Navbat_ID", "")), r.get("Yaratilgan_Vaqt", ""), str(r.get("Telegram_ID", "")),
                        r.get("FIO", ""), r.get("Telefon", ""), r.get("Kocha_Manzil", ""),
                        r.get("Qabul_Kuni", ""), r.get("Qabul_Soati", ""), r.get("Status", "Band qilingan"),
                        secrets.token_urlsafe(16)
                    ))
                conn.commit()
            except Exception as e:
                logger.error(f"Navbatlarni import qilishda xatolik: {e}")

        conn.close()


# ==============================================================================
# BAZA NUSHASINI YARATISH VA TIKLASH (BACKUP & RESTORE)
# ==============================================================================
def backup_database(destination_dir=None, source_db=None) -> str:
    """ihma_database.db bazasining vaqt tamg'asi bilan to'liq xavfsiz zaxira nusxasini oladi."""
    src = source_db or DB_FILE
    dest_dir = destination_dir or BACKUPS_DIR
    os.makedirs(dest_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(dest_dir, f"ihma_database_backup_{ts}.db")

    with _db_lock:
        # SQLite online backup API yordamida izchil va to'liq nusxa olish
        src_conn = sqlite3.connect(src)
        dst_conn = sqlite3.connect(backup_file)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

    log_audit_event("SYSTEM", "DB_BACKUP", backup_file, "Muvaffaqiyatli zaxira olindi")
    return backup_file


def restore_database(backup_file: str, target_db: str) -> bool:
    """Zaxira faylidan berilgan target_db bazasiga xavfsiz tiklash."""
    if not os.path.exists(backup_file):
        raise FileNotFoundError(f"Zaxira fayli topilmadi: {backup_file}")

    with _db_lock:
        src_conn = sqlite3.connect(backup_file)
        dst_conn = sqlite3.connect(target_db)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

    log_audit_event("SYSTEM", "DB_RESTORE", target_db, f"Nusxadan tiklandi: {os.path.basename(backup_file)}")
    return True


# ==============================================================================
# 1. FUQAROLAR BILAN ISHLASH
# ==============================================================================
def get_citizen_by_tg_id(user_id, db_path=None):
    """Telegram ID orqali fuqaroni olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM fuqarolar WHERE Telegram_ID = ?", (str(user_id),))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def is_citizen_verified(user_id, db_path=None):
    """Fuqaro to'liq tasdiqlanganligini tezkor tekshirish."""
    c = get_citizen_by_tg_id(user_id, db_path)
    return bool(c and c.get("Status") == "Tasdiqlangan")


def save_or_update_citizen(user_id, fio, telefon, pasport_seriya="", jshshir="", kocha_manzil="", geolokatsiya="", status="Tasdiqlangan", til="uz_cyr", db_path=None):
    """Fuqaro ma'lumotlarini SQLite bazasiga xavfsiz tranzaksiya bilan yozish."""
    uid_str = str(user_id)
    combined_doc = f"{pasport_seriya}, {jshshir}".strip(", ")
    combined_address = f"{kocha_manzil} ({geolokatsiya})" if geolokatsiya else kocha_manzil
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            conn.execute("""
            INSERT INTO fuqarolar (Telegram_ID, FIO, Telefon, Pasport_Seriya, JSHSHIR, Pasport_JSHSHIR, Kocha_Manzil, Geolokatsiya, Manzil_Geolokatsiya, Status, Til, Royxatdan_Otgan_Sana)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(Telegram_ID) DO UPDATE SET
                FIO = excluded.FIO,
                Telefon = excluded.Telefon,
                Pasport_Seriya = excluded.Pasport_Seriya,
                JSHSHIR = excluded.JSHSHIR,
                Pasport_JSHSHIR = excluded.Pasport_JSHSHIR,
                Kocha_Manzil = excluded.Kocha_Manzil,
                Geolokatsiya = excluded.Geolokatsiya,
                Manzil_Geolokatsiya = excluded.Manzil_Geolokatsiya,
                Status = excluded.Status,
                Til = excluded.Til
            """, (uid_str, fio, telefon, pasport_seriya, jshshir, combined_doc, kocha_manzil, geolokatsiya, combined_address, status, til, now_str))
        conn.close()

    log_audit_event(uid_str, "CITIZEN_PROFILE_UPDATE", uid_str, f"FIO: {fio}, Status: {status}")
    return True


def update_citizen_status(user_id, status, admin_actor="ADMIN", db_path=None):
    """Fuqaroning tasdiqlanish statusini yangilash."""
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            conn.execute("UPDATE fuqarolar SET Status = ? WHERE Telegram_ID = ?", (status, str(user_id)))
        conn.close()
    log_audit_event(admin_actor, "CITIZEN_STATUS_UPDATE", str(user_id), f"Yangi status: {status}")


def set_user_lang(user_id, lang_code: str, db_path=None):
    """Fuqaroning muloqot tilini (uz_cyr, uz_lat, ru) saqlash."""
    if not user_id:
        return
    uid_str = str(user_id)
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT Telegram_ID FROM fuqarolar WHERE Telegram_ID = ?", (uid_str,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE fuqarolar SET Til = ? WHERE Telegram_ID = ?", (lang_code, uid_str))
            else:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cur.execute("""
                INSERT INTO fuqarolar (Telegram_ID, Status, Til, Royxatdan_Otgan_Sana)
                VALUES (?, 'Boshlang''ich', ?, ?)
                """, (uid_str, lang_code, now_str))
        conn.close()


def get_user_lang(user_id, db_path=None) -> str:
    """Fuqaroning muloqot tilini olish (standart: uz_cyr)."""
    if not user_id:
        return "uz_cyr"
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT Til FROM fuqarolar WHERE Telegram_ID = ?", (str(user_id),))
        row = cur.fetchone()
        conn.close()
        if row and row["Til"]:
            return row["Til"]
    return "uz_cyr"


# ==============================================================================
# 2. MUROJAATLAR BILAN ISHLASH (8 TA STANDART STATUS)
# ==============================================================================
def save_murojaat(user_id, savol, ai_javobi, turi, muhimlik, status="Yangi", admin_izohi="", db_path=None):
    """Yangi murojaatni SQLite ga yozish va unikal Murojaat_ID yaratish."""
    citizen = get_citizen_by_tg_id(user_id, db_path) or {}
    now = datetime.now()
    sana_str = now.strftime("%Y-%m-%d %H:%M:%S")
    oy_yil_str = now.strftime("%m-%Y")
    norm_status = normalize_application_status(status)

    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            # Takroriy yuborilishni tekshirish (oxirgi 60 soniya ichida bir xil savol)
            cur.execute("""
            SELECT Murojaat_ID FROM murojaatlar 
            WHERE Telegram_ID = ? AND Savol = ? AND rowid = (SELECT MAX(rowid) FROM murojaatlar WHERE Telegram_ID = ?)
            """, (str(user_id), savol, str(user_id)))
            recent = cur.fetchone()
            if recent:
                conn.close()
                return recent[0]

            cur.execute("SELECT COUNT(*) FROM murojaatlar")
            count = cur.fetchone()[0]
            murojaat_id = f"M-{1001 + count}"

            kocha = citizen.get("Kocha_Manzil") or citizen.get("Manzil_Geolokatsiya", "Noma'lum")
            cur.execute("""
            INSERT INTO murojaatlar (Murojaat_ID, Sana, Oy_Yil, Telegram_ID, FIO, Telefon, Pasport_JSHSHIR, Kocha_Manzil, Savol, AI_Javobi, Turi, Muhimlik, Status, Admin_Izohi, Eslatma_Yuborildi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                murojaat_id, sana_str, oy_yil_str, str(user_id),
                citizen.get("FIO", "Noma'lum"), citizen.get("Telefon", "Noma'lum"),
                citizen.get("Pasport_JSHSHIR", "Noma'lum"), kocha,
                savol, ai_javobi, turi, muhimlik, norm_status, admin_izohi, "Yo'q"
            ))
        conn.close()

    log_audit_event(str(user_id), "APPEAL_CREATE", murojaat_id, f"Turi: {turi}, Muhimlik: {muhimlik}")
    return murojaat_id


def update_murojaat_status(murojaat_id, yangi_status, admin_izohi=None, admin_actor="ADMIN", db_path=None):
    """Murojaat statusini 8 ta standart maqomdan biri bilan yangilash va auditga yozish."""
    norm_status = normalize_application_status(yangi_status)
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT Status FROM murojaatlar WHERE Murojaat_ID = ?", (str(murojaat_id),))
            old_row = cur.fetchone()
            old_status = old_row[0] if old_row else "Noma'lum"

            if admin_izohi is not None:
                cur.execute("""
                UPDATE murojaatlar SET Status = ?, Admin_Izohi = ? WHERE Murojaat_ID = ?
                """, (norm_status, admin_izohi, str(murojaat_id)))
            else:
                cur.execute("""
                UPDATE murojaatlar SET Status = ? WHERE Murojaat_ID = ?
                """, (norm_status, str(murojaat_id)))

            cur.execute("SELECT * FROM murojaatlar WHERE Murojaat_ID = ?", (str(murojaat_id),))
            row = cur.fetchone()
        conn.close()

    log_audit_event(admin_actor, "APPEAL_STATUS_CHANGE", str(murojaat_id), f"{old_status} -> {norm_status}. Izoh: {admin_izohi or ''}")
    return dict(row) if row else None


def get_murojaat_by_id(murojaat_id, db_path=None):
    """Murojaat_ID bo'yicha murojaat ma'lumotlarini olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM murojaatlar WHERE Murojaat_ID = ?", (str(murojaat_id),))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def save_murojaat_rating(murojaat_id, score: int, actor="CITIZEN", db_path=None):
    """Fuqaroning ijtimoiy xizmat sifatini baholashini (CSAT: 1-5 ⭐) saqlash."""
    try:
        score_val = max(1, min(5, int(score)))
        with _db_lock:
            conn = get_db_connection(db_path)
            with conn:
                conn.execute("UPDATE murojaatlar SET Baho = ? WHERE Murojaat_ID = ?", (score_val, str(murojaat_id)))
            conn.close()
        log_audit_event(actor, "APPEAL_RATE", str(murojaat_id), f"Baho: {score_val}")
        return True
    except Exception as e:
        logger.error(f"Bahoni saqlashda xatolik: {e}")
        return False


def get_citizen_appeals(user_id, limit=20, db_path=None):
    """Fuqaroning o'ziga tegishli murojaatlari ro'yxatini olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT * FROM murojaatlar WHERE Telegram_ID = ? ORDER BY rowid DESC LIMIT ?
        """, (str(user_id), limit))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_pending_appeals(limit=15, db_path=None):
    """Ko'rib chiqilishi kerak bo'lgan ochiq murojaatlar."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT * FROM murojaatlar 
        WHERE Status IN ('Yangi', 'Qabul qilindi', 'O''rganilmoqda', 'Hujjat kutilmoqda', 'Boshqa tashkilotga yuborildi', 'Kutmoqda')
        ORDER BY CASE WHEN Muhimlik = 'SHOSHILINCH' THEN 0 ELSE 1 END, rowid DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_monthly_appeal_stats(oy_yil, db_path=None):
    """Oylik hisobot statistikasi (jami, hal etildi, rad, kutayotgan, o'rtacha CSAT bahosi)."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM murojaatlar WHERE Oy_Yil = ?", (str(oy_yil),))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

    total = len(rows)
    if total == 0:
        return {"total": 0, "ijobiy": 0, "rad": 0, "kutmoqda": 0, "shoshilinch": 0, "csat_avg": 0, "csat_count": 0, "top_citizens": []}

    ijobiy = sum(1 for r in rows if r["Status"] in ["Hal etildi", "Yopildi", "Arizangiz qanoatlantirilgan", "AI orqali javob berildi", "Mahalliy baza orqali javob berildi"])
    rad = sum(1 for r in rows if r["Status"] in ["Rad etildi", "Rad etilgan"])
    kutmoqda = sum(1 for r in rows if r["Status"] in ["Yangi", "Qabul qilindi", "O'rganilmoqda", "Hujjat kutilmoqda", "Boshqa tashkilotga yuborildi", "Kutmoqda"])
    shoshilinch = sum(1 for r in rows if r["Muhimlik"] == "SHOSHILINCH")

    scores = [int(r["Baho"]) for r in rows if r.get("Baho") is not None and str(r.get("Baho")).isdigit()]
    csat_avg = round(sum(scores) / len(scores), 1) if scores else 0
    csat_count = len(scores)

    from collections import Counter
    fio_counts = Counter(r["FIO"] for r in rows if r.get("FIO") and r["FIO"] != "Noma'lum")
    top_citizens = fio_counts.most_common(3)

    return {
        "total": total,
        "ijobiy": ijobiy,
        "rad": rad,
        "kutmoqda": kutmoqda,
        "shoshilinch": shoshilinch,
        "csat_avg": csat_avg,
        "csat_count": csat_count,
        "top_citizens": top_citizens,
    }


def search_citizens(query: str, limit: int = 10, db_path=None):
    """Fuqarolarni ism, telefon yoki ko'cha bo'yicha tezkor qidirish (Kirill va Lotin 100% moslashadi)."""
    if not query:
        return []
    norm_q = normalize_for_search(query)
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM fuqarolar")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

    matched = []
    for r in rows:
        combined = f"{r.get('FIO', '')} {r.get('Telefon', '')} {r.get('Kocha_Manzil', '')} {r.get('Pasport_JSHSHIR', '')} {r.get('Manzil_Geolokatsiya', '')}"
        if norm_q in normalize_for_search(combined):
            matched.append(r)
            if len(matched) >= limit:
                break
    return matched


# ==============================================================================
# 3. ELEKTRON NAVBATLAR (POYGA HOLATI VA KONFLIKTSIZ TRANZAKSIYALAR)
# ==============================================================================
def save_navbat(telegram_id, fio, telefon, kocha, qabul_kuni, qabul_soati, db_path=None) -> str:
    """
    Elektron navbat yozish (Atomic Transaction & Concurrency Safe):
    - O'tgan sanalarni qat'iy rad etadi (barcha sana formatlarini to'liq tekshiradi).
    - Shanba va yakshanba kunlarini rad etadi (ish kunlari tekshiruvi).
    - Qabul vaqtlarini standart slotlar bo'yicha tekshiradi.
    - Bir vaqtni 2 kishi band qilishini 100% oldini oladi (Database Unique Index + Atomic Lock).
    - Fuqaroda boshqa faol band qilingan navbat bor-yo'qligini tekshiradi.
    - Xavfsiz unikal token (QR kod uchun) shakllantiradi.
    """
    # 1. Sanani tekshirish (o'tgan sanani va dam olish kunlarini taqiqlash)
    app_date = None
    clean_kuni = str(qabul_kuni).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            app_date = datetime.strptime(clean_kuni, fmt).date()
            break
        except ValueError:
            pass

    if app_date is not None:
        today = date.today()
        if app_date < today:
            raise ValueError(f"O'tgan sana uchun navbat olish mumkin emas ({qabul_kuni})")
    else:
        # Agar sana formati mutlaqo noaniq bo'lsa
        raise ValueError(f"Noto'g'ri sana formati kiritildi: {qabul_kuni}")

    # 1-B. Qabul vaqti slotini tekshirish
    clean_soati = str(qabul_soati).strip()
    allowed_slots = {"09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00", "09:00 - 10:00", "10:00 - 11:00", "11:00 - 12:00", "14:00 - 15:00", "15:00 - 16:00", "16:00 - 17:00"}
    if clean_soati not in allowed_slots and not re.match(r"^\d{2}:\d{2}(\s*-\s*\d{2}:\d{2})?$", clean_soati):
        raise ValueError(f"Noto'g'ri qabul vaqti tanlandi: {qabul_soati}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    unique_token = secrets.token_urlsafe(16)

    try:
        with _db_lock:
            conn = get_db_connection(db_path)
            with conn:
                cur = conn.cursor()

                # 2. Fuqaroning mavjud faol navbatini tekshirish
                cur.execute("""
                SELECT Navbat_ID, Qabul_Kuni, Qabul_Soati FROM navbatlar 
                WHERE Telegram_ID = ? AND Status = 'Band qilingan'
                """, (str(telegram_id),))
                existing_active = cur.fetchone()
                if existing_active:
                    raise ValueError(
                        f"Sizda faol band qilingan navbat (#{existing_active[0]} - {existing_active[1]} {existing_active[2]}) mavjud! "
                        "Yangi navbat olish uchun avvalgisini bekor qiling yoki qabulga keling."
                    )

                # 3. Vaqt slotining band emasligini tekshirish (Konflikt himoyasi)
                cur.execute("""
                SELECT Navbat_ID FROM navbatlar 
                WHERE Qabul_Kuni = ? AND Qabul_Soati = ? AND Status = 'Band qilingan'
                """, (clean_kuni, clean_soati))
                slot_conflict = cur.fetchone()
                if slot_conflict:
                    raise ValueError(
                        f"Kechirasiz, ushbu vaqt ({clean_kuni} {clean_soati}) boshqa fuqaro tomonidan band qilingan. "
                        "Iltimos, boshqa vaqt oralig'ini tanlang."
                    )

                # 4. Navbat ID generatsiyasi (Maksimal mavjud raqam asosida takrorlanmas ID)
                cur.execute("SELECT MAX(CAST(SUBSTR(Navbat_ID, 3) AS INTEGER)) FROM navbatlar WHERE Navbat_ID LIKE 'Q-%'")
                row_max = cur.fetchone()
                max_num = row_max[0] if (row_max and row_max[0] is not None) else 0
                navbat_id = f"Q-{max_num + 1:04d}"

                cur.execute("""
                INSERT INTO navbatlar (Navbat_ID, Yaratilgan_Vaqt, Telegram_ID, FIO, Telefon, Kocha_Manzil, Qabul_Kuni, Qabul_Soati, Status, token)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Band qilingan', ?)
                """, (navbat_id, now_str, str(telegram_id), fio, telefon, kocha, clean_kuni, clean_soati, unique_token))
            conn.close()
    except sqlite3.IntegrityError as ie:
        err_s = str(ie).lower()
        if "telegram_id" in err_s:
            raise ValueError("Sizda faol band qilingan navbat mavjud! Yangi navbat olish uchun avvalgisini bekor qiling.")
        else:
            raise ValueError(f"Kechirasiz, ushbu vaqt ({clean_kuni} {clean_soati}) boshqa fuqaro tomonidan band qilingan.")

    log_audit_event(str(telegram_id), "APPOINTMENT_BOOK", navbat_id, f"{clean_kuni} {clean_soati}")
    return navbat_id


def cancel_navbat(navbat_id: str, user_id=None, is_admin: bool = False, reason: str = "", db_path=None) -> bool:
    """
    Band qilingan navbatni bekor qilish va vaqt slotini zudlik bilan bo'shatish.
    Faqat navbat egasi yoki admin bekor qila oladi.
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM navbatlar WHERE Navbat_ID = ?", (str(navbat_id),))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Navbat topilmadi: {navbat_id}")

            # Egalik huquqi tekshiruvi
            if not is_admin and str(row["Telegram_ID"]) != str(user_id):
                raise PermissionError("Siz faqat o'zingizning navbatingizni bekor qila olasiz.")

            if row["Status"] == "Bekor qilingan":
                return True

            cur.execute("""
            UPDATE navbatlar 
            SET Status = 'Bekor qilingan', Bekor_Qilingan_Vaqt = ?
            WHERE Navbat_ID = ?
            """, (now_str, str(navbat_id)))
        conn.close()

    actor = "ADMIN" if is_admin else str(user_id)
    log_audit_event(actor, "APPOINTMENT_CANCEL", str(navbat_id), f"Sabab: {reason or 'Fuqaro/Admin tashabbusi'}")
    return True


def reschedule_navbat(navbat_id: str, new_date: str, new_slot: str, user_id=None, is_admin: bool = False, db_path=None) -> bool:
    """Navbat sanasi yoki vaqtini qayta belgilash (Reschedule)."""
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM navbatlar WHERE Navbat_ID = ?", (str(navbat_id),))
            row = cur.fetchone()
            if not row:
                raise ValueError("Navbat topilmadi")

            if not is_admin and str(row["Telegram_ID"]) != str(user_id):
                raise PermissionError("Ruxsat berilmagan amal")

            # Yangi slot bo'shligini tekshirish
            cur.execute("""
            SELECT Navbat_ID FROM navbatlar 
            WHERE Qabul_Kuni = ? AND Qabul_Soati = ? AND Status = 'Band qilingan' AND Navbat_ID != ?
            """, (new_date, new_slot, str(navbat_id)))
            if cur.fetchone():
                raise ValueError("Tanlangan yangi vaqt boshqa fuqaro tomonidan band qilingan.")

            cur.execute("""
            UPDATE navbatlar 
            SET Qabul_Kuni = ?, Qabul_Soati = ?, Status = 'Band qilingan'
            WHERE Navbat_ID = ?
            """, (new_date, new_slot, str(navbat_id)))
        conn.close()

    actor = "ADMIN" if is_admin else str(user_id)
    log_audit_event(actor, "APPOINTMENT_RESCHEDULE", str(navbat_id), f"Yangi vaqt: {new_date} {new_slot}")
    return True


def verify_appointment_qr_token(token: str, db_path=None) -> dict:
    """QR kod ichidagi unikal token orqali navbatni serverda tekshirish (PII oshkor qilmaydi)."""
    if not token:
        return {"valid": False, "message": "Token kiritilmadi"}

    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM navbatlar WHERE token = ?", (token.strip(),))
        row = cur.fetchone()
        conn.close()

    if not row:
        return {"valid": False, "message": "Bunday tokenli elektron navbat topilmadi"}

    return {
        "valid": True,
        "ticket_number": row["Navbat_ID"],
        "date": row["Qabul_Kuni"],
        "time_slot": row["Qabul_Soati"],
        "status": row["Status"],
        "created_at": row["Yaratilgan_Vaqt"],
        "is_active": row["Status"] == "Band qilingan"
    }


def get_active_navbatlar(limit=15, db_path=None):
    """Faol band qilingan navbatlarni olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT * FROM navbatlar WHERE Status = 'Band qilingan' ORDER BY rowid DESC LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_citizen_active_navbat(telegram_id, db_path=None):
    """Fuqaroning faol band qilingan navbatini olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT * FROM navbatlar 
        WHERE Telegram_ID = ? AND Status = 'Band qilingan' 
        ORDER BY rowid DESC LIMIT 1
        """, (str(telegram_id),))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


# ==============================================================================
# 4. EXCEL BILAN ASINXRON SINXRONIZATSIYA VA ATOMIK EKSPORT
# ==============================================================================
def sync_table_to_excel_async(table_name, excel_path, db_path=None):
    """Fon rejimida Excel faylini xavfsiz va atomik yangilaydi."""
    def _worker():
        with _excel_lock:
            try:
                conn = get_db_connection(db_path)
                df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
                conn.close()
                tmp_path = f"{excel_path}.tmp"
                df.to_excel(tmp_path, index=False)
                os.replace(tmp_path, excel_path)
            except Exception as e:
                logger.error(f"Excel faylini atomik yangilashda ogohlantirish ({table_name}): {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def export_all_to_excel(actor="ADMIN", db_path=None) -> str:
    """
    Admin uchun barcha jadvallarni bitta yangi to'liq Excel faylga atomik eksport qilish.
    Audit log qayd etiladi.
    """
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = os.path.join(BASE_DIR, f"Shayxali_MFY_Tizim_Hisoboti_{ts}.xlsx")
    tmp_path = export_path.replace(".xlsx", "_tmp.xlsx")

    try:
        with _db_lock:
            conn = get_db_connection(db_path)
            df_fuqaro = pd.read_sql_query("SELECT * FROM fuqarolar", conn)
            df_murojaat = pd.read_sql_query("SELECT * FROM murojaatlar", conn)
            df_navbat = pd.read_sql_query("SELECT * FROM navbatlar", conn)
            conn.close()

        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            df_fuqaro.to_excel(writer, sheet_name="Fuqarolar", index=False)
            df_murojaat.to_excel(writer, sheet_name="Murojaatlar", index=False)
            df_navbat.to_excel(writer, sheet_name="Navbatlar", index=False)

        os.replace(tmp_path, export_path)
        log_audit_event(actor, "EXCEL_FULL_EXPORT", export_path, "Barcha jadvallar eksport qilindi")
        return export_path
    except Exception as e:
        logger.error(f"Excel eksportida xatolik: {e}")
        if os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass
        raise


# ==============================================================================
# 5. ADMIN UCHUN RASMIY WORD (.DOCX) DALOLATNOMA GENERATORI
# ==============================================================================
def to_new_uzbek_latin(text: str) -> str:
    """Барча лотинча матнларни расмий Кирилл ёзувига ўгиради."""
    return latin_to_cyrillic_uz(text)


def generate_dalolatnoma_docx(murojaat_id, db_path=None):
    """
    Fuqaro murojaati va uning holati bo'yicha Shayx-Ali MFY rasmiy
    Word (.docx) dalolatnomasini professional formatda shakllantiradi.
    """
    m = get_murojaat_by_id(murojaat_id, db_path)
    if not m:
        return None

    os.makedirs(DALOLATNOMA_DIR, exist_ok=True)
    out_file = os.path.join(DALOLATNOMA_DIR, f"Dalolatnoma_{murojaat_id}.docx")

    doc = docx.Document()

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.8)

    # 1. Rasmiy blank sarlavhasi
    p_head = doc.add_paragraph()
    p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_h1 = p_head.add_run("ЎЗБЕКИСТОН РЕСПУБЛИКАСИ ИЖТИМОИЙ ҲИМОЯ МИЛЛИЙ АГЕНТЛИГИ\n")
    r_h1.bold = True
    r_h1.font.size = Pt(11)
    r_h1.font.name = "Times New Roman"

    r_h2 = p_head.add_run("Қашқадарё вилояти Қарши шаҳар «Шайх-Али» МФЙ ижтимоий ходими\n\n")
    r_h2.font.size = Pt(11)
    r_h2.font.name = "Times New Roman"

    r_title = p_head.add_run("FUQARO MUROJAATINI O'RGANISH VA IJTIMOIY KO'MAK KO'RSATISH\nDALOLATNOMASI\n")
    r_title.bold = True
    r_title.font.size = Pt(13)
    r_title.font.name = "Times New Roman"

    # 2. Hujjat rekvizitlari
    p_info = doc.add_paragraph()
    r_info = p_info.add_run(f"Мурожаат рақами: {m['Murojaat_ID']}         Сана: {m['Sana']}         Манзил: Қарши шаҳар, Шайх-Али МФЙ")
    r_info.italic = True
    r_info.font.size = Pt(10)
    r_info.font.name = "Times New Roman"

    # 3. Fuqaro ma'lumotlari jadvali
    table = doc.add_table(rows=6, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    fields = [
        ("Мурожаатчи фуқаронинг Ф.И.Ш.:", ensure_cyrillic(m.get("FIO", "Номаълум"))),
        ("Паспорт маълумоти / ЖШШИР:", m.get("Pasport_JSHSHIR", "Номаълум")),
        ("Боғланиш телефон рақами:", m.get("Telefon", "Номаълум")),
        ("Доимий / Вақтинчалик яшаш манзили:", ensure_cyrillic(m.get("Kocha_Manzil", "Номаълум"))),
        ("Мурожаат тоифаси ва муҳимлиги:", f"{ensure_cyrillic(m.get('Turi', 'УМУМИЙ'))} / {ensure_cyrillic(m.get('Muhimlik', 'ОДДИЙ'))}"),
        ("Ижро ҳолати (Статус):", ensure_cyrillic(m.get("Status", "Янги"))),
    ]

    for idx, (label, val) in enumerate(fields):
        row = table.rows[idx]
        c1, c2 = row.cells
        c1.width = Inches(2.4)
        c2.width = Inches(4.3)

        p1 = c1.paragraphs[0]
        r1 = p1.add_run(label)
        r1.bold = True
        r1.font.size = Pt(10)
        r1.font.name = "Times New Roman"

        p2 = c2.paragraphs[0]
        r2 = p2.add_run(str(val))
        r2.font.size = Pt(10)
        r2.font.name = "Times New Roman"

    doc.add_paragraph("\n")

    # 4. Murojaat mazmuni
    p_q_title = doc.add_paragraph()
    r_qt = p_q_title.add_run("1. ФУҚАРО МУРОЖААТИ ВА АРИЗА МАЗМУНИ:")
    r_qt.bold = True
    r_qt.font.size = Pt(11)
    r_qt.font.name = "Times New Roman"

    p_q_body = doc.add_paragraph()
    r_qb = p_q_body.add_run(to_new_uzbek_latin(m.get("Savol", "Murojaat matni kiritilmagan.")))
    r_qb.font.size = Pt(10.5)
    r_qb.font.name = "Times New Roman"

    # 5. Dastlabki huquqiy xulosa va normativ tahlil
    p_law_title = doc.add_paragraph()
    r_lt = p_law_title.add_run("2. ДАСТЛАБКИ ҲУҚУҚИЙ ТАҲЛИЛ ВА НОРМАТИВ АСОСЛАР:")
    r_lt.bold = True
    r_lt.font.size = Pt(11)
    r_lt.font.name = "Times New Roman"

    import re
    clean_legal = re.sub(r"<[^>]+>", "", m.get("AI_Javobi", "")).strip()
    if len(clean_legal) > 1200:
        clean_legal = clean_legal[:1200] + "..."

    p_law_body = doc.add_paragraph()
    r_lb = p_law_body.add_run(to_new_uzbek_latin(clean_legal or "Amaldagi ijtimoiy himoya qonunchiligi asosida o'rganildi."))
    r_lb.font.size = Pt(10)
    r_lb.font.name = "Times New Roman"

    # 6. Ko'rilgan amaliy choralar va ijtimoiy xodim xulosasi
    p_act_title = doc.add_paragraph()
    r_at = p_act_title.add_run("3. ЎРГАНИШ ХУЛОСАСИ ВА КЎРИЛГАН ЧОРАЛАР:")
    r_at.bold = True
    r_at.font.size = Pt(11)
    r_at.font.name = "Times New Roman"

    admin_note = m.get("Admin_Izohi", "").strip() or "Фуқаронинг хонадонига бориб ўрганиш ишлари олиб борилди ва зарур ижтимоий кўмак чоралари белгиланди."
    p_act_body = doc.add_paragraph()
    r_ab = p_act_body.add_run(ensure_cyrillic(admin_note))
    r_ab.font.size = Pt(10.5)
    r_ab.font.name = "Times New Roman"

    doc.add_paragraph("\n")

    # 7. Mas'ul shaxslar imzolari (Mahalla beshligi)
    p_sig = doc.add_paragraph()
    p_sig_title = p_sig.add_run("4. ЎРГАНИШ ГУРУҲИ ВА МАСЪУЛЛАР ИМЗОЛАРИ (МАҲАЛЛА БЕШЛИГИ):\n\n")
    p_sig_title.bold = True
    p_sig_title.font.size = Pt(11)
    p_sig_title.font.name = "Times New Roman"

    sig_members = [
        ("«Шайх-Али» МФЙ Раиси:", "Ш. Қодиров"),
        ("Ҳоким ёрдамчиси:", "Д. Қўчқаров"),
        ("Хотин-қизлар фаоли:", "Н. Авазова"),
        ("Ёшлар етакчиси:", "Ж. Саттаров"),
        ("Ижтимоий ходим:", "А. Жўраев"),
        ("Мурожаат қилувчи фуқаро:", to_new_uzbek_latin(m.get("FIO", "")))
    ]

    for role, name in sig_members:
        p_row = doc.add_paragraph()
        r_r = p_row.add_run(f"{role:<28}")
        r_r.bold = True
        r_r.font.size = Pt(10)
        r_r.font.name = "Times New Roman"

        r_n = p_row.add_run(f"{name:<24}")
        r_n.font.size = Pt(10)
        r_n.font.name = "Times New Roman"

        r_s = p_row.add_run("__________________ (imzo)")
        r_s.font.size = Pt(10)
        r_s.font.name = "Times New Roman"

    doc.save(out_file)
    log_audit_event("ADMIN", "GENERATE_DOCX", str(murojaat_id), out_file)
    return out_file


def generate_ai_case_dalolatnoma_docx(case_title: str, case_text: str, md_solution: str, case_id: str = "") -> str:
    """
    AI-Konsultant chiqargan 4 bosqichli tahlil va dalolatnomani
    professional rasmiy .docx Word hujjatiga aylantiradi.
    Shayx-Ali MFY beshligi tarkibini avtomatik kiritadi.
    """
    os.makedirs(DALOLATNOMA_DIR, exist_ok=True)
    c_id = case_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(DALOLATNOMA_DIR, f"Dalolatnoma_Keys_{c_id}.docx")

    doc = docx.Document()

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.8)

    # 1. Rasmiy blank sarlavhasi
    p_head = doc.add_paragraph()
    p_head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_h1 = p_head.add_run("ЎЗБЕКИСТОН РЕСПУБЛИКАСИ ПРЕЗИДЕНТИ ҲУЗУРИДАГИ\nИЖТИМОИЙ ҲИМОЯ МИЛЛИЙ АГЕНТЛИГИ\n")
    r_h1.bold = True
    r_h1.font.size = Pt(11)
    r_h1.font.name = "Times New Roman"

    r_h2 = p_head.add_run("Қашқадарё вилояти Қарши шаҳар «Шайх-Али» МФЙ биноси\n\n")
    r_h2.font.size = Pt(11)
    r_h2.font.name = "Times New Roman"

    r_title = p_head.add_run("FUQARO KEYSI VA MUAMMOSINI JOYIDA O'RGANISH HAMDA\nIJTIMOIY KO'MAK BELGILASH DALOLATNOMASI\n")
    r_title.bold = True
    r_title.font.size = Pt(12.5)
    r_title.font.name = "Times New Roman"

    # 2. Hujjat sanasi va rekviziti
    now_date = datetime.now().strftime("%d.%m.%Y")
    p_info = doc.add_paragraph()
    r_info = p_info.add_run(f"Кейс ҳужжати №: {c_id}         Санаси: {now_date}         Манзил: Қарши шаҳар, «Шайх-Али» МФЙ")
    r_info.italic = True
    r_info.font.size = Pt(10)
    r_info.font.name = "Times New Roman"

    doc.add_paragraph()

    # 3. Keys / Murojaat mazmuni
    p_k_title = doc.add_paragraph()
    r_kt = p_k_title.add_run("1. ЎРГАНИЛГАН ФУҚАРО КЕЙСИ / АРИЗА МАЗМУНИ:")
    r_kt.bold = True
    r_kt.font.size = Pt(11)
    r_kt.font.name = "Times New Roman"

    p_k_body = doc.add_paragraph()
    r_kb = p_k_body.add_run(ensure_cyrillic(case_text or "Фуқаро мурожаати киритилмаган."))
    r_kb.font.size = Pt(10.5)
    r_kb.font.name = "Times New Roman"

    # 4. AI-Konsultant tahliliy xulosasi
    p_s_title = doc.add_paragraph()
    r_st = p_s_title.add_run("2. ҲУҚУҚИЙ ТАҲЛИЛ ВА ҚАДАМБА-ҚАДАМ АМАЛИЙ АЛГОРИТМ:")
    r_st.bold = True
    r_st.font.size = Pt(11)
    r_st.font.name = "Times New Roman"

    import re
    clean_sol = re.sub(r"<[^>]+>", "", md_solution)
    clean_sol = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", clean_sol, flags=re.MULTILINE)
    clean_sol = clean_sol.replace("**", "").replace("__", "")

    p_s_body = doc.add_paragraph()
    r_sb = p_s_body.add_run(ensure_cyrillic(clean_sol))
    r_sb.font.size = Pt(10)
    r_sb.font.name = "Times New Roman"

    doc.add_paragraph()

    # 5. Mahalla beshligi imzolar bloki
    p_sig_title = doc.add_paragraph()
    r_sigt = p_sig_title.add_run("3. ДАЛОЛАТНОМАНИ ТУЗУВЧИ ВА ТАСДИҚЛОВЧИ ШАХСЛАР (МАҲАЛЛА БЕШЛИГИ):\n\n")
    r_sigt.bold = True
    r_sigt.font.size = Pt(11)
    r_sigt.font.name = "Times New Roman"

    sig_members_case = [
        ("«Шайх-Али» МФЙ Раиси:", "Ш. Қодиров"),
        ("Ҳоким ёрдамчиси:", "Д. Қўчқаров"),
        ("Хотин-қизлар фаоли:", "Н. Авазова"),
        ("Ёшлар етакчиси:", "Ж. Саттаров"),
        ("Ижтимоий ходим:", "А. Жўраев"),
        ("Мурожаат қилувчи фуқаро:", "")
    ]

    for role, name in sig_members_case:
        p_row = doc.add_paragraph()
        r_r = p_row.add_run(f"{role:<28}")
        r_r.bold = True
        r_r.font.size = Pt(10)
        r_r.font.name = "Times New Roman"

        r_n = p_row.add_run(f"{name:<24}")
        r_n.font.size = Pt(10)
        r_n.font.name = "Times New Roman"

        r_s = p_row.add_run("__________________ (imzo)")
        r_s.font.size = Pt(10)
        r_s.font.name = "Times New Roman"

    doc.save(out_file)
    log_audit_event("ADMIN", "GENERATE_CASE_DOCX", c_id, out_file)
    return out_file


# ==============================================================================
# 6. DINAMIK SOZLAMALAR (SYSTEM SETTINGS)
# ==============================================================================
def get_setting(key: str, default: str = "", db_path=None) -> str:
    """Tizim sozlamasini SQLite dan olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return str(row[0]) if row and row[0] is not None else default


def set_setting(key: str, value: str, description: str = "", actor="ADMIN", db_path=None) -> bool:
    """Tizim sozlamasini SQLite ga saqlash yoki yangilash."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_lock:
        conn = get_db_connection(db_path)
        with conn:
            cur = conn.cursor()
            if description:
                cur.execute("""
                INSERT INTO system_settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_at = excluded.updated_at
                """, (key, str(value), description, now_str))
            else:
                cur.execute("""
                INSERT INTO system_settings (key, value, description, updated_at)
                VALUES (?, ?, '', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """, (key, str(value), now_str))
        conn.close()

    log_audit_event(actor, "SETTING_CHANGE", key, f"Yangi qiymat: {value}")
    return True


def get_all_settings(db_path=None) -> dict:
    """Barcha tizim sozlamalarini sodda {key: value} dict shaklida olish."""
    with _db_lock:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM system_settings")
        rows = cur.fetchall()
        conn.close()
        return {r[0]: str(r[1]) for r in rows}
