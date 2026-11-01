# -*- coding: utf-8 -*-
"""
Qarshi shahar "Shayx-Ali" MFY Ijtimoiy xodimi (A. Jo'rayev) uchun
Ijtimoiy AI-konsultanti va Alohida Ijtimoiy AI Bilimlari Bazasi (RAG) moduli.
Rasmiy O'zbek tili va qonunchilik me'yorlari asosida to'liq lokalizatsiya qilingan.
"""

import os
import re
import io
import json
import time
import sqlite3
import threading
import urllib.request
from datetime import datetime
import telebot
from telebot import types
import pypdf
import docx
import openpyxl
from PIL import Image
import google.generativeai as genai
from utils.pii_masker import mask_pii
from utils.text_normalizer import normalize_for_search, latin_to_cyrillic_uz, ensure_cyrillic
from utils.audio_transcriber import transcribe_audio_bytes

# --- 1. KONFIGURATSIYA VA YO'LLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_KB_DIR = os.path.join(BASE_DIR, "admin_social_kb")
ADMIN_KB_INDEX_JSON = os.path.join(ADMIN_KB_DIR, "kb_index.json")
TELEGRAPH_TOKEN_FILE = os.path.join(ADMIN_KB_DIR, "telegraph_token.json")
DB_FILE = os.path.join(BASE_DIR, "ihma_database.db")
os.makedirs(ADMIN_KB_DIR, exist_ok=True)

_kb_lock = threading.Lock()
_ai_solutions_cache = {}  # Telegraph va Telegram uchun so'nggi tahlillar kesh xotirasi

# --- 2. YANGI O'ZBEK LOTIN ALIFBOSI ALMASHTIRGICHI ---
def to_new_uzbek_latin(text: str) -> str:
    """Барча лотинча матнларни расмий Кирилл алифбосига ўгиради."""
    return latin_to_cyrillic_uz(text)


def clean_markdown_to_telegram_html(text: str) -> str:
    """
    Markdown (headers, bold, italic, bullet points, horizontal dividers)
    belgilarini xavfsiz va chiroyli Telegram HTML formatiga o'tkazadi.
    Barcha xom '**', '#', '---' belgilari to'liq tozalanishini kafolatlaydi.
    """
    if not text:
        return ""
    s = str(text)
    # 1. Gorizontal ajratgich chiziqlar (tozalash)
    s = re.sub(r"^[ \t]*[-*_]{3,}[ \t]*$", "", s, flags=re.MULTILINE)

    # 2. **bold** va __bold__
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)

    # 3. Sarlavhalar (#, ##, ###, ####)
    def _header_sub(m):
        hashes = m.group(1)
        title = m.group(2).strip()
        title = re.sub(r"^<b>(.*?)</b>$", r"\1", title)
        title = re.sub(r"[\*\_]", "", title).strip()
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
    return to_new_uzbek_latin(s)


# --- 2.1 TELEGRAPH (TELEGRA.PH) INTEGRATSIYASI ---
def get_or_create_telegraph_token() -> str:
    """Telegraph API hisobini boshqaradi va tokenini saqlaydi."""
    if os.path.exists(TELEGRAPH_TOKEN_FILE):
        try:
            with open(TELEGRAPH_TOKEN_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                tok = d.get("access_token")
                if tok:
                    return tok
        except Exception:
            pass

    try:
        data = json.dumps({"short_name": "ShayxaliMFY", "author_name": "A. Jo'rayev (Ijtimoiy xodim)"}).encode("utf-8")
        req = urllib.request.Request("https://api.telegra.ph/createAccount", data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            token = res.get("result", {}).get("access_token")
            if token:
                with open(TELEGRAPH_TOKEN_FILE, "w", encoding="utf-8") as f:
                    json.dump({"access_token": token}, f)
                return token
    except Exception as e:
        print("Telegraph akkaunt yaratishda ogohlantirish:", e)
    return ""


def parse_inline_telegraph(text: str) -> list:
    """Matndagi **bold**, *italic*, `code` larni Telegraph node elementlariga aylantiradi."""
    text = to_new_uzbek_latin(text)
    tokens = re.split(r"(\*\*.*?\*\*|\*.*?\*|`.*?`)", text)
    children = []
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) >= 4:
            children.append({"tag": "b", "children": [token[2:-2]]})
        elif token.startswith("*") and token.endswith("*") and len(token) >= 2:
            children.append({"tag": "i", "children": [token[1:-1]]})
        elif token.startswith("`") and token.endswith("`") and len(token) >= 2:
            children.append({"tag": "code", "children": [token[1:-1]]})
        else:
            children.append(token)
    return children


def markdown_to_telegraph_nodes(case_title: str, case_text: str, md_solution: str) -> list:
    """
    AI tahlili va Dalolatnoma qoralamasini estetik Telegraph DOM node daraxtiga aylantiradi.
    """
    nodes = []

    # 1. Rasmiy sarlavha paneli (Header Blockquote)
    now_str = datetime.now().strftime("%d.%m.%Y, %H:%M")
    nodes.append({
        "tag": "blockquote",
        "children": [
            {"tag": "b", "children": ["🏛 ҚАШҚАДАРЁ ВИЛОЯТИ, ҚАРШИ ШАҲАР «ШАЙХ-АЛИ» МФЙ"]},
            {"tag": "br"},
            "Масъул: А. Жўраев (Ижтимоий ходим) | Шахсий Методик ва Ҳуқуқий AI-Маслаҳатчи Хулосаси",
            {"tag": "br"},
            f"Санаси: {now_str} | Ҳуқуқий асос: ИҲМА меъёрий ҳужжатлари ҳамда ВМ қарорлари"
        ]
    })

    # 2. Fuqaro keysi / Murojaat mazmuni
    if case_text:
        nodes.append({"tag": "h4", "children": ["📋 Ўрганилган Фуқаро Кейси / Мурожаат Мазмуни:"]})
        nodes.append({
            "tag": "blockquote",
            "children": [latin_to_cyrillic_uz(case_text.strip())]
        })

    nodes.append({"tag": "hr"})

    # 3. Asosiy tahlil matnini qatorma-qator parse qilish
    lines = md_solution.split("\n")
    current_list = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current_list:
                nodes.append(current_list)
                current_list = None
            continue

        if re.match(r"^[-*_]{3,}$", line):
            if current_list:
                nodes.append(current_list)
                current_list = None
            nodes.append({"tag": "hr"})
            continue

        # Sarlavhalar: #, ##, ###, ####
        header_m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if header_m:
            if current_list:
                nodes.append(current_list)
                current_list = None
            level = len(header_m.group(1))
            h_text = header_m.group(2).replace("**", "").replace("__", "").strip()
            h_text = to_new_uzbek_latin(h_text)
            tag = "h3" if level <= 3 else "h4"
            nodes.append({"tag": tag, "children": [h_text]})
            continue

        # Ro'yxat punktlari: * yoki -
        bullet_m = re.match(r"^[\*\-]\s+(.*)$", line)
        if bullet_m:
            item_text = bullet_m.group(1).strip()
            item_children = parse_inline_telegraph(item_text)
            if not current_list or current_list.get("tag") != "ul":
                if current_list:
                    nodes.append(current_list)
                current_list = {"tag": "ul", "children": []}
            current_list["children"].append({"tag": "li", "children": item_children})
            continue

        # Raqamlangan ro'yxat: 1. yoki 2)
        num_m = re.match(r"^\d+[\.\)]\s+(.*)$", line)
        if num_m:
            item_text = num_m.group(1).strip()
            item_children = parse_inline_telegraph(item_text)
            if not current_list or current_list.get("tag") != "ol":
                if current_list:
                    nodes.append(current_list)
                current_list = {"tag": "ol", "children": []}
            current_list["children"].append({"tag": "li", "children": item_children})
            continue

        # Iqtibos: >
        if line.startswith(">"):
            if current_list:
                nodes.append(current_list)
                current_list = None
            b_text = line.lstrip("> ").strip()
            nodes.append({"tag": "blockquote", "children": parse_inline_telegraph(b_text)})
            continue

        # Oddiy paragraf
        if current_list:
            nodes.append(current_list)
            current_list = None

        p_children = parse_inline_telegraph(line)
        nodes.append({"tag": "p", "children": p_children})

    if current_list:
        nodes.append(current_list)

    # 4. Mahalla beshligi tekshiruv dalolatnomasi xotimasi
    nodes.append({"tag": "hr"})
    nodes.append({
        "tag": "blockquote",
        "children": [
            {"tag": "b", "children": ["⚖️ JOYIGA CHIQIB O'RGANISH VA DALOLATNOMA MAS'ULLARI (MAHALLA BESHLIGI):"]},
            {"tag": "br"},
            "1. MFY Raisi: Sh. Qodirov",
            {"tag": "br"},
            "2. Hokim yordamchisi: D. Qo'chqorov",
            {"tag": "br"},
            "3. Xotin-qizlar faoli: N. Avazova",
            {"tag": "br"},
            "4. Yoshlar yetakchisi: J. Sattarov",
            {"tag": "br"},
            "5. Ijtimoiy xodim: A. Jo'rayev"
        ]
    })
    nodes.append({
        "tag": "p",
        "children": [
            {"tag": "i", "children": [
                "Ushbu tahliliy hujjat Qarshi shahar «Shayx-Ali» MFY ijtimoiy xodimi A.Jo'rayevning sun'iy intellekt "
                "maslahatchisi tomonidan IHMA qoidalari asosida avtomatik shakllantirildi."
            ]}
        ]
    })
    return nodes


def publish_case_to_telegraph(case_title: str, case_text: str, md_solution: str) -> str:
    """
    Keys tahlili va Dalolatnoma qoralamasini Telegraph da nashr qiladi va Instant View havolasini qaytaradi.
    """
    token = get_or_create_telegraph_token()
    if not token:
        return ""

    try:
        nodes = markdown_to_telegraph_nodes(case_title, case_text, md_solution)
        clean_title = to_new_uzbek_latin(case_title or "Shayx-Ali MFY | Keys Tahlili")[:200]

        payload = json.dumps({
            "access_token": token,
            "title": clean_title,
            "author_name": "A. Jo'rayev (Ijtimoiy xodim)",
            "author_url": "https://t.me/ShayxaliMFY_ijtimoiy_robot",
            "content": nodes,
            "return_content": False
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.telegra.ph/createPage",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if res.get("ok"):
                return res.get("result", {}).get("url", "")
    except Exception as e:
        print("Telegraph ga nashr etishda xatolik:", e)
    return ""


# --- 3. BAZANI INISIALIZATSIYA QILISH ---
def init_admin_social_kb():
    """Admin ijtimoiy bilimlari bazasi jadvallarini yaratadi."""
    with _kb_lock:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_social_kb (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT UNIQUE,
            title TEXT,
            file_type TEXT,
            file_path TEXT,
            original_filename TEXT,
            clean_content TEXT,
            char_count INTEGER,
            chunk_count INTEGER,
            created_at TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_social_kb_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT,
            chunk_index INTEGER,
            content TEXT,
            char_count INTEGER
        )
        """)
        conn.commit()
        conn.close()

    if not os.path.exists(ADMIN_KB_INDEX_JSON):
        _sync_json_index()


def _get_db_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _sync_json_index():
    """SQLite dagi hujjatlarni JSON indeks fayliga sinxronlaydi."""
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT doc_id, title, file_type, char_count, chunk_count, created_at FROM admin_social_kb ORDER BY id DESC")
        rows = cur.fetchall()

        docs_list = []
        total_chunks = 0
        total_chars = 0
        for r in rows:
            docs_list.append({
                "doc_id": r["doc_id"],
                "title": r["title"],
                "file_type": r["file_type"],
                "char_count": r["char_count"],
                "chunk_count": r["chunk_count"],
                "created_at": r["created_at"]
            })
            total_chunks += r["chunk_count"] or 0
            total_chars += r["char_count"] or 0
        conn.close()

        index_payload = {
            "total_documents": len(docs_list),
            "total_chunks": total_chunks,
            "total_chars": total_chars,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "documents": docs_list
        }
        with open(ADMIN_KB_INDEX_JSON, "w", encoding="utf-8") as f:
            json.dump(index_payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("JSON indeksni saqlashda ogohlantirish:", e)


# --- 4. TOKEN TEJASH VA MATNNI TOZALASH ---
def clean_text_for_tokens(text: str) -> str:
    """Matndagi ortiqcha bo'shliqlar, bo'sh qatorlar va keraksiz belgilarni tozalaydi."""
    if not text:
        return ""
    t = text.replace("\r", "").replace("\xa0", " ")
    # Ketma-ket bo'shliqlarni bitta bo'shliqqa keltirish
    t = re.sub(r"[ \t]+", " ", t)
    # Ketma-ket 2 tadan ortiq qator tashlashlarni qisqartirish
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    lines = [line.strip() for line in t.split("\n")]
    # Boshidagi va oxiridagi bo'shliqlarni olib tashlash
    return "\n".join(lines).strip()


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> list:
    """Matnni RAG uchun qulay parchalarga (chunks) bo'ladi."""
    text = clean_text_for_tokens(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    total_len = len(text)
    while start < total_len:
        end = start + chunk_size
        if end >= total_len:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Tugallangan nuqta yoki yangi qatordan bo'lish
        split_at = -1
        for sep in ["\n\n", "\n", ". ", "; ", " "]:
            pos = text.rfind(sep, start + chunk_size // 2, end)
            if pos != -1:
                split_at = pos + len(sep)
                break
        if split_at == -1:
            split_at = end

        chunk = text[start:split_at].strip()
        if chunk:
            chunks.append(chunk)
        start = max(split_at - overlap, start + 1)
    return chunks


# --- 5. FAYLLARNI O'QISH VA PARSING ---
def parse_pdf_bytes(file_bytes: bytes) -> str:
    """PDF baytlaridan matnni ajratib oladi."""
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    parts = []
    for idx, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(f"--- Sahifa {idx+1} ---\n" + txt.strip())
        except Exception:
            continue
    return "\n\n".join(parts)


def parse_docx_bytes(file_bytes: bytes) -> str:
    """Word (.docx) baytlaridan matn va jadvallarni ajratib oladi."""
    doc = docx.Document(io.BytesIO(file_bytes))
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text.strip())
    for t_idx, table in enumerate(doc.tables):
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_xlsx_bytes(file_bytes: bytes) -> str:
    """Excel (.xlsx) baytlaridan jadvallarni matn ko'rinishida ajratib oladi."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"--- Jadval varag'i: {sheet.title} ---")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_text_bytes(file_bytes: bytes) -> str:
    """Oddiy matn baytlarini o'qiydi."""
    for enc in ["utf-8", "utf-8-sig", "latin1", "cp1251"]:
        try:
            return file_bytes.decode(enc)
        except Exception:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def add_document_to_admin_kb(file_bytes: bytes, filename: str, title: str = None) -> dict:
    """
    Faylni qabul qiladi, xavfsizlik tekshiruvidan o'tkazadi (format, hajm, traversal),
    matnini tozalab ajratadi, PII niqoblaydi, chunks yaratadi, SQLite va JSON indeksga saqlaydi.
    """
    if not file_bytes:
        raise ValueError("Fayl ma'lumoti bo'sh!")

    if len(file_bytes) > 20 * 1024 * 1024:
        raise ValueError("Fayl hajmi ruxsat etilgan 20MB limitidan oshib ketdi!")

    ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt"}
    clean_base = os.path.basename(filename)
    ext = os.path.splitext(clean_base)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Ruxsat berilmagan fayl kengaytmasi ({ext}). Faqat PDF, Word, Excel va TXT fayllar qabul qilinadi.")

    raw_text = ""
    if ext == ".pdf":
        raw_text = parse_pdf_bytes(file_bytes)
        file_type = "pdf"
    elif ext in [".docx", ".doc"]:
        raw_text = parse_docx_bytes(file_bytes)
        file_type = "docx"
    elif ext in [".xlsx", ".xls"]:
        raw_text = parse_xlsx_bytes(file_bytes)
        file_type = "xlsx"
    else:
        raw_text = parse_text_bytes(file_bytes)
        file_type = "txt"

    clean_content = mask_pii(clean_text_for_tokens(raw_text))
    if not clean_content:
        raise ValueError("Hujjat ichidan o'qib olinadigan matn topilmadi!")

    chunks = chunk_text(clean_content)
    if not chunks:
        raise ValueError("Hujjat matnini bo'laklashda xatolik yuz berdi!")

    doc_id = f"SKB-{int(time.time())}"
    doc_title = title or clean_base
    safe_name = f"{doc_id}_{re.sub(r'[^a-zA-Z0-9_.-]', '_', clean_base)}"
    disk_path = os.path.join(ADMIN_KB_DIR, safe_name)

    # Diskka saqlash
    with open(disk_path, "wb") as f_out:
        f_out.write(file_bytes)

    # SQLite ga kiritish
    with _kb_lock:
        conn = _get_db_conn()
        cur = conn.cursor()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        cur.execute("""
        INSERT INTO admin_social_kb (doc_id, title, file_type, file_path, original_filename, clean_content, char_count, chunk_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (doc_id, doc_title, file_type, disk_path, filename, clean_content, len(clean_content), len(chunks), created_at))

        for idx, chunk in enumerate(chunks):
            cur.execute("""
            INSERT INTO admin_social_kb_chunks (doc_id, chunk_index, content, char_count)
            VALUES (?, ?, ?, ?)
            """, (doc_id, idx, chunk, len(chunk)))

        conn.commit()
        conn.close()

    _sync_json_index()

    return {
        "status": "ok",
        "doc_id": doc_id,
        "title": doc_title,
        "file_type": file_type,
        "char_count": len(clean_content),
        "chunk_count": len(chunks),
        "created_at": created_at
    }


def add_text_to_admin_kb(text: str, title: str = None) -> dict:
    """Admin tomonidan yuborilgan to'g'ridan-to'g'ri matnni bazaga qo'shadi."""
    clean_content = clean_text_for_tokens(text)
    if not clean_content or len(clean_content) < 10:
        raise ValueError("Kiritilgan matn juda qisqa!")

    doc_id = f"SKB-{int(time.time())}"
    doc_title = title or (clean_content[:40].replace("\n", " ") + "...")
    chunks = chunk_text(clean_content)

    safe_name = f"{doc_id}_matn.txt"
    disk_path = os.path.join(ADMIN_KB_DIR, safe_name)
    with open(disk_path, "w", encoding="utf-8") as f:
        f.write(clean_content)

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _kb_lock:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO admin_social_kb (doc_id, title, file_type, file_path, original_filename, clean_content, char_count, chunk_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (doc_id, doc_title, "matn", disk_path, "matn.txt", clean_content, len(clean_content), len(chunks), created_at))

        for idx, chunk in enumerate(chunks):
            cur.execute("""
            INSERT INTO admin_social_kb_chunks (doc_id, chunk_index, content, char_count)
            VALUES (?, ?, ?, ?)
            """, (doc_id, idx, chunk, len(chunk)))

        conn.commit()
        conn.close()

    _sync_json_index()

    return {
        "status": "ok",
        "doc_id": doc_id,
        "title": doc_title,
        "file_type": "matn",
        "char_count": len(clean_content),
        "chunk_count": len(chunks),
        "created_at": created_at
    }


def delete_document_from_admin_kb(doc_id: str) -> bool:
    """Hujjatni SQLite, disk va JSON indeksdan to'liq o'chiradi."""
    with _kb_lock:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM admin_social_kb WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return False

        file_path = row["file_path"]
        cur.execute("DELETE FROM admin_social_kb_chunks WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM admin_social_kb WHERE doc_id = ?", (doc_id,))
        conn.commit()
        conn.close()

        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    _sync_json_index()
    return True


def list_admin_kb_documents(limit: int = 50) -> list:
    """Barcha saqlangan hujjatlar ro'yxatini qaytaradi."""
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT doc_id, title, file_type, char_count, chunk_count, created_at FROM admin_social_kb ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_admin_kb_stats() -> dict:
    """Admin bilimlar bazasining statistik ma'lumotlarini beradi."""
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS total_docs, SUM(chunk_count) AS total_chunks, SUM(char_count) AS total_chars FROM admin_social_kb")
    row = cur.fetchone()
    conn.close()
    return {
        "total_documents": row["total_docs"] or 0,
        "total_chunks": row["total_chunks"] or 0,
        "total_chars": row["total_chars"] or 0
    }


# --- 6. RAG QIDIRUV TIZIMI ---
def search_admin_kb(query: str, top_k: int = 4) -> list:
    """
    Keys tavsifi bo'yicha admin ijtimoiy bazasidagi eng tegishli
    moddalar va bo'laklarni (chunks) topib beradi.
    """
    if not query:
        return []

    norm_query = normalize_for_search(query)
    words = re.findall(r"\w{3,}", norm_query)
    stop_words = {"bilan", "uchun", "yoki", "hamda", "kerak", "qanday", "nima", "qaysi", "bormi", "mumkin", "haqida", "asosida"}
    keywords = [w for w in words if w not in stop_words]
    if not keywords:
        keywords = words[:5]

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT c.doc_id, c.chunk_index, c.content, d.title, d.file_type
    FROM admin_social_kb_chunks c
    JOIN admin_social_kb d ON c.doc_id = d.doc_id
    """)
    all_chunks = cur.fetchall()
    conn.close()

    scored = []
    for r in all_chunks:
        c_text = normalize_for_search(r["content"])
        title_text = normalize_for_search(r["title"] or "")
        score = 0
        for kw in keywords:
            if kw in c_text:
                score += 2
            if kw in title_text:
                score += 3
        if score > 0:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for _, r in scored[:top_k]:
        results.append({
            "doc_id": r["doc_id"],
            "title": r["title"],
            "content": r["content"]
        })
    return results


# --- 7. AI KONSULTANT TIZIM PROMPTI VA CHAQIRISH ---
AI_CONSULTANT_SYSTEM_PROMPT = """Сиз Қарши шаҳар Шайх-Али МФЙ ижтимоий ходими А.Жўраевнинг шахсий ҳуқуқий ва методик AI-маслаҳатчисисиз. Вазифангиз: киритилган муаммо ёки кейсни (case management) чуқур таҳлил қилиш ва қуйидаги тузилмада, ФАҚАТ ЎЗБЕК КИРИЛЛ АЛИФБОСИДА аниқ ечим бериш:

1. Вазиятнинг ҳуқуқий баҳоси (ИҲМА низомлари ва ВМ қарорлари асосида).
2. Ижтимоий ходим қилиши керак бўлган қадам-бақадам амалий ҳаракатлар (алгоритм).
3. Фуқарога қайси ижтимоий хизмат ёки ёрдам тури мос келиши ва рад этиш/қабул қилиш асослари.
4. Агар жойига чиқиб ўрганиш керак бўлса, маҳалла бешлиги (МФЙ раиси Ш.Қодиров, ҳоким ёрдамчиси Д.Қўчқаров, хотин-қизлар фаоли Н.Авазова, ёшлар етакчиси Ж.Саттаров ва ижтимоий ходим А.Жўраев) иштирокида тузиладиган Далолатнома ёки расмий жавоб хати учун тайёр қоралама.

Қатъий талаблар:
- Фақатгина Ўзбекистон Республикасининг амалдаги қонунчилиги (lex.uz, ИҲМА меъёрий ҳужжатлари, ВМ-654, ВМ-442, ВМ-62, ЎРҚ-547, ЎРҚ-561, ПҚ-107) ва ижтимоий ходим томонидан юкланган «Ижтимоий AI билимлари» базасига таянган ҳолда аниқ, пухта ва профессионал таҳлил бер.
- Жавобинг ҳар доим расмий, тушунарли ва амалиётга тўлиқ татбиқ этиладиган бўлсин.
- ҚАТЪИЙ ИМЛО ҚОИДАСИ: Барча матн ва жавобларни ФАҚАТ ЎЗБЕК КИРИЛЛ АЛИФБОСИДА ёз! Ҳеч қандай лотин ҳарфларини (sh, ch, o', g' ёки ó, ǵ, ş, ç) ишлатма!
- ҚАТЪИЙ МОЛИЯВИЙ ТАЛАБ: Қонун, қарор ва нафақа меъёрлари бўйича маълумот берганда ТАХМИНИЙ СЎМ СУММАЛАРИНИ АСЛО ЁЗМА! Ҳар қандай тўлов, нафақа ва ёрдам миқдорларини ФАҚАТ ҚОНУН ҲУЖЖАТИДА БЕЛГИЛАНГАН БХМ (Базавий ҳисоблаш миқдори) ёки МИҲ (Минимал истеъмол харажатлари) кўрсаткичларида (масалан: «БХМнинг 50 фоизи», «БХМнинг 2 баравари», «МИҲ чегараси») кўрсат!"""

def ask_ai_consultant(case_text: str, image_bytes: bytes = None) -> str:
    """
    Keysni 'Ijtimoiy AI bilimlari' bazasi (RAG) va qonunchilik asosida
    Gemini API (yoki Groq zaxirasi) orqali tahlil qilib, 4 bosqichli amaliy yechim beradi.
    """
    # 1. RAG qidiruv: Admin bazasidan tegishli moddalarni olish
    kb_matches = search_admin_kb(case_text, top_k=4)
    rag_context = ""
    if kb_matches:
        rag_context = "\n\n📚 [IJTIMOIY AI BILIMLARI BAZASIDAN TOPILGAN ASOSIY MEZONLAR]:\n"
        for m in kb_matches:
            rag_context += f"• Manba: {m['title']}\n{m['content']}\n\n"
    else:
        rag_context = "\n\n📚 [IJTIMOIY AI BILIMLARI]: Maxsus ichki hujjat topilmadi, umumiy O'zbekiston Respublikasi IHMA va VM qonunchiligiga asoslanildi."

    # Check if case_text mentions server/system/devops
    lower_case = (case_text or "").lower()
    server_kw = ["server", "сервер", "ram", "cpu", "диск", "uptime", "процессор", "хотира", "лог", "log", "бошқарув", "status", "статус", "тизим"]
    if any(k in lower_case for k in server_kw):
        try:
            from utils.server_monitor import get_system_metrics, get_recent_logs
            m = get_system_metrics()
            log_tail = get_recent_logs(os.path.join(BASE_DIR, "bot.log"), lines_count=8)
            server_info = (
                "\n\n🖥️ [ЖОРИЙ СЕРВЕР ВА БОТ ҲОЛАТИ (LIVE METRICS)]:\n"
                f"- CPU: {m['cpu_percent']}%, RAM: {m['ram_percent']}%, Диск: {m['disk_percent']}%\n"
                f"- Сервер иш вақти: {m['server_uptime']}, Бот Uptime: {m['bot_uptime']}\n"
                f"- Охирги логлар:\n{log_tail}\n"
            )
            rag_context += server_info
        except Exception:
            pass

    full_prompt = (
        f"{rag_context}\n\n"
        f"📝 TAHLIL UCHUN TAQDIM ETILGAN KEYS / FUQARO MUAMMOSI:\n{case_text}\n\n"
        f"Iltimos, yuqoridagi 4 ta tuzilma bo'yicha to'liq va mukammal professional yechim taqdim et."
    )

    contents = []
    if image_bytes:
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            contents.append(pil_img)
        except Exception as img_err:
            print("Rasm yuklashda ogohlantirish:", img_err)

    contents.append(full_prompt)

    # 2. Gemini API orqali chaqirish
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    keys = [k.strip() for k in env_key.split(",") if k.strip()]
    for i in range(2, 6):
        extra_k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if extra_k and extra_k not in keys:
            keys.append(extra_k)

    env_model = os.getenv("GEMINI_MODEL_NAME", "gemini-3.8-flash").strip()
    gemini_models = [env_model, "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-3.5-flash", "gemini-3.6-flash"]
    seen_m = set()
    uniq_gemini_models = [m for m in gemini_models if not (m in seen_m or seen_m.add(m))]
    last_err = None

    for key_idx, g_key in enumerate(keys):
        try:
            genai.configure(api_key=g_key)
        except Exception:
            pass

        for m_name in uniq_gemini_models:
            try:
                model_inst = genai.GenerativeModel(
                    model_name=m_name,
                    system_instruction=AI_CONSULTANT_SYSTEM_PROMPT,
                    generation_config={"temperature": 0.2, "max_output_tokens": 4096}
                )
                resp = model_inst.generate_content(contents)
                if hasattr(resp, "text") and resp.text:
                    return to_new_uzbek_latin(resp.text)
            except Exception as e:
                last_err = e
                err_s = str(e).lower()
                if any(x in err_s for x in ["429", "quota", "resource_exhausted", "limit"]):
                    print(f"🔄 Gemini #{key_idx+1} ({m_name}) kvotasi tugadi. Groq zaxirasiga o'tilmoqda...")
                    break
                continue

    # 3. Zaxira Groq tizimi (agar rasm bo'lmasa yoki matnli bo'lsa)
    print("🔄 Gemini tokeni yoki kvotasi tugadi. Avtomatik ravishda 2-zaxira AI kalitiga (Groq API) o'tilmoqda...")
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        for gr_model in ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
            try:
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
                    data=json.dumps({
                        "model": gr_model,
                        "messages": [
                            {"role": "system", "content": AI_CONSULTANT_SYSTEM_PROMPT},
                            {"role": "user", "content": full_prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 3500
                    }).encode("utf-8")
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    choices = data.get("choices", [])
                    if choices:
                        ans = choices[0].get("message", {}).get("content", "")
                        if ans:
                            print(f"✅ Groq AI ({gr_model}) zaxira kaliti orqali tahlil olindi!")
                            return to_new_uzbek_latin(ans)
            except Exception as e:
                print(f"Groq {gr_model} zaxira xatosi:", e)
                continue

    if last_err:
        raise last_err
    return to_new_uzbek_latin("⚠️ Кечирасиз, сунъий интеллект хизматларига уланишда вақтинча муаммо юз берди. Илтимос, қайтадан уриниб кўринг.")


# --- 8. TELEGRAM HANDLERS VA ROUTER ---
def register_admin_ai_handlers(bot: telebot.TeleBot, is_admin_func, get_admin_menu_func, admin_state_dict: dict):
    """
    Barcha admin AI yordamchi va Ijtimoiy AI bilimlari routerlarini botga ulaydi.
    """
    init_admin_social_kb()

    # --- CALLBACK: TELEGRAMDA TO'LIQ MATNNI KO'RSATISH ---
    @bot.callback_query_handler(func=lambda call: call.data.startswith("adm_ai_show_"))
    def handle_ai_show_full_text(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return
        bot.answer_callback_query(call.id)

        cache_id = call.data.replace("adm_ai_show_", "")
        item = _ai_solutions_cache.get(cache_id)
        if not item:
            bot.send_message(call.message.chat.id, "⚠️ Tahlil matni muddati o'tgan yoki topilmadi. Iltimos, yangi tahlil so'rovini yuboring.")
            return

        full_md = item.get("text", "")
        # Markdown belgilarini to'liq xavfsiz Telegram HTML formatiga o'tkazish
        clean_html = clean_markdown_to_telegram_html(full_md)
        header = "🏛 <b>ШАЙХ-АЛИ МФЙ ИЖТИМОИЙ ХОДИМИ AI-КОНСУЛЬТАНТИ (ТЎЛИҚ ҲУҚУҚИЙ ТАҲЛИЛ)</b>\n\n"
        full_text = header + clean_html

        back_markup = types.InlineKeyboardMarkup(row_width=1)
        if item.get("telegraph_url"):
            back_markup.add(types.InlineKeyboardButton("📖 Telegraph'да тўлиқ ўқиш (Инстант View)", url=item["telegraph_url"]))
        back_markup.add(
            types.InlineKeyboardButton("📄 Далолатномани Word (.docx) да юклаб олиш", callback_data=f"adm_ai_docx_{cache_id}"),
            types.InlineKeyboardButton("📝 Янги кейс таҳлили", callback_data="adm_ai_consultant"),
            types.InlineKeyboardButton("🔙 Админ Панелига қайтиш", callback_data="adm_back_main")
        )

        def _safe_send(text_part, markup=None):
            try:
                bot.send_message(call.message.chat.id, text_part, reply_markup=markup, parse_mode="HTML")
            except Exception:
                plain = re.sub(r"<[^>]+>", "", text_part)
                bot.send_message(call.message.chat.id, plain, reply_markup=markup)

        if len(full_text) <= 3900:
            _safe_send(full_text, back_markup)
        else:
            paragraphs = full_text.split("\n\n")
            chunks = []
            curr = ""
            for p in paragraphs:
                if len(curr) + len(p) + 2 > 3500:
                    if curr:
                        chunks.append(curr.strip())
                    curr = p
                else:
                    curr = curr + "\n\n" + p if curr else p
            if curr:
                chunks.append(curr.strip())

            for p_idx, chunk in enumerate(chunks):
                is_last = (p_idx == len(chunks) - 1)
                _safe_send(chunk, back_markup if is_last else None)

    # --- CALLBACK: WORD (.DOCX) DALOLATNOMA YUKLASH ---
    @bot.callback_query_handler(func=lambda call: call.data.startswith("adm_ai_docx_"))
    def handle_ai_download_docx(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return

        cache_id = call.data.replace("adm_ai_docx_", "")
        item = _ai_solutions_cache.get(cache_id)
        if not item:
            bot.answer_callback_query(call.id, "⚠️ Tahlil matni topilmadi! Qaytadan keys yuboring.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "📄 Dalolatnoma Word (.docx) tayyorlanmoqda...")

        try:
            import database
            docx_path = database.generate_ai_case_dalolatnoma_docx(
                case_title=item.get("title", ""),
                case_text=item.get("case", ""),
                md_solution=item.get("text", ""),
                case_id=cache_id
            )
            if docx_path and os.path.exists(docx_path):
                with open(docx_path, "rb") as f:
                    bot.send_document(
                        call.message.chat.id,
                        f,
                        caption=(
                            "📄 <b>ШАЙХ-АЛИ МФЙ РАСМИЙ ДАЛОЛАТНОМАСИ (.DOCX)</b>\n\n"
                            "🏛 <b>Ўрганиш гуруҳи ва имзо чекувчилар (Маҳалла бешлиги):</b>\n"
                            "• МФЙ Раиси: <b>Ш. Қодиров</b>\n"
                            "• Ҳоким ёрдамчиси: <b>Д. Қўчқаров</b>\n"
                            "• Хотин-қизлар фаоли: <b>Н. Авазова</b>\n"
                            "• Ёшлар етакчиси: <b>Ж. Саттаров</b>\n"
                            "• Ижтимоий ходим: <b>А. Жўраев</b>\n\n"
                            "<i>Ҳужжат чоп этиш ва имзолаш учун тайёр.</i>"
                        ),
                        parse_mode="HTML"
                    )
            else:
                bot.send_message(call.message.chat.id, "❌ Dalolatnoma faylini shakllantirishda muammo yuz berdi.")
        except Exception as docx_err:
            bot.send_message(call.message.chat.id, f"❌ Dalolatnoma yaratish xatoligi: {docx_err}")

    # --- CALLBACK: ASOSIY BILIMLAR BAZASI MENYUSI ---
    @bot.callback_query_handler(func=lambda call: call.data == "adm_social_kb_menu")
    def handle_social_kb_menu(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return
        bot.answer_callback_query(call.id)

        stats = get_admin_kb_stats()
        kb_text = (
            "📚 <b>IJTIMOIY AI BILIMLARI BAZASI (MAXSUS RAG OMBOXONASI)</b>\n\n"
            f"📁 <b>Saqlangan hujjatlar soni:</b> {stats['total_documents']} ta\n"
            f"📑 <b>Таҳлил қилинган моддалар/парчалар:</b> {stats['total_chunks']} та\n"
            f"📊 <b>Baza hajmi:</b> {round(stats['total_chars'] / 1024, 1)} KB (tozalangan matn)\n\n"
            "⚖️ <i>Ушбу база фуқаролар базасидан БУТУНЛАЙ АЛОҲИДА бўлиб, фақат сиз (ижтимоий ходим) "
            "учун ишлайди. Юклаган қоидалар, низомлар ва тавсиялар «🧠 AI Ёрдамчи» кейс таҳлилида "
            "бевосита асос қилиб олинади.</i>\n\n"
            "<i>Kerakli amalni tanlang:</i>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("➕ Маълумот қўшиш (PDF, Word, Excel, Матн)", callback_data="adm_social_kb_add"),
            types.InlineKeyboardButton("📋 База рўйхати ва ўчириш", callback_data="adm_social_kb_list"),
            types.InlineKeyboardButton("🔙 Админ Панелига қайтиш", callback_data="adm_back_main"),
        )
        try:
            bot.edit_message_text(kb_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, kb_text, reply_markup=markup, parse_mode="HTML")

    # --- CALLBACK: MA'LUMOT QO'SHISH REJIMI ---
    @bot.callback_query_handler(func=lambda call: call.data == "adm_social_kb_add")
    def handle_social_kb_add(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return
        bot.answer_callback_query(call.id)

        admin_state_dict[call.from_user.id] = {"action": "waiting_for_admin_kb_upload"}

        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Бекор қилиш"))

        prompt_text = (
            "➕ <b>ИЖТИМОИЙ AI БИЛИМЛАРИ БАЗАСИГА МАЪЛУМОТ ҚЎШИШ</b>\n\n"
            "Quyidagi shakllardan birida ma'lumot yuboring:\n"
            "1️⃣ <b>Файл юбориш:</b> PDF (.pdf), Word (.docx), Excel (.xlsx) ёки Матнли (.txt) ҳужжат;\n"
            "2️⃣ <b>To'g'ridan-to'g'ri matn:</b> Qonun moddasi, ichki nizom, mezon yoki ko'rsatmani to'g'ridan-to'g'ri xabar sifatida yozing.\n\n"
            "⚡ <i>Hujjat avtomatik ravishda ortiqcha bo'shliqlardan tozalanadi, parchalarga ajratiladi va sun'iy intellekt xotirasiga kiritiladi.</i>"
        )
        bot.send_message(call.message.chat.id, prompt_text, reply_markup=cancel_markup, parse_mode="HTML")

    # --- CALLBACK: BAZA RO'YXATI VA O'CHIRISH ---
    @bot.callback_query_handler(func=lambda call: call.data == "adm_social_kb_list")
    def handle_social_kb_list(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return
        bot.answer_callback_query(call.id)

        docs = list_admin_kb_documents(limit=30)
        if not docs:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("➕ Маълумот қўшиш", callback_data="adm_social_kb_add"),
                types.InlineKeyboardButton("🔙 Ортга", callback_data="adm_social_kb_menu")
            )
            empty_text = "📭 <b>Ижтимоий AI билимлари базаси ҳозирча бўш.</b>\n\nИлтимос, «➕ Маълумот қўшиш» тугмаси орқали ҳужжат юкланг."
            try:
                bot.edit_message_text(empty_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
            except Exception:
                bot.send_message(call.message.chat.id, empty_text, reply_markup=markup, parse_mode="HTML")
            return

        text = "📋 <b>IJTIMOIY AI BILIMLAR BAZASIDAGI HUJJATLAR:</b>\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)
        for d in docs:
            icon = "📕" if d["file_type"] == "pdf" else ("📘" if d["file_type"] == "docx" else ("📗" if d["file_type"] == "xlsx" else "📄"))
            text += f"{icon} <b>{d['title']}</b>\n🆔 ID: <code>{d['doc_id']}</code> | 📑 {d['chunk_count']} та парча | 📅 {d['created_at']}\n\n"
            markup.add(types.InlineKeyboardButton(f"🗑 Ўчириш: {d['title'][:25]}", callback_data=f"adm_skb_del_{d['doc_id']}"))

        markup.add(types.InlineKeyboardButton("➕ Яна ҳужжат қўшиш", callback_data="adm_social_kb_add"))
        markup.add(types.InlineKeyboardButton("🔙 Билимлар менюсига қайтиш", callback_data="adm_social_kb_menu"))

        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode="HTML")

    # --- CALLBACK: HUJJATNI O'CHIRISH ---
    @bot.callback_query_handler(func=lambda call: call.data.startswith("adm_skb_del_"))
    def handle_social_kb_delete(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return

        doc_id = call.data.replace("adm_skb_del_", "")
        deleted = delete_document_from_admin_kb(doc_id)
        if deleted:
            bot.answer_callback_query(call.id, "✅ Hujjat bazadan muvaffaqiyatli o'chirildi!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "⚠️ Hujjat topilmadi!", show_alert=True)

        # Ro'yxatni yangilash
        handle_social_kb_list(call)

    # --- CALLBACK: AI KONSULTANT REJIMI ---
    @bot.callback_query_handler(func=lambda call: call.data == "adm_ai_consultant")
    def handle_ai_consultant_start(call):
        if not is_admin_func(call.from_user.id):
            bot.answer_callback_query(call.id, "Faqat Admin uchun!", show_alert=True)
            return
        bot.answer_callback_query(call.id)

        admin_state_dict[call.from_user.id] = {"action": "waiting_for_ai_case"}

        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("🔙 Бекор қилиш"))

        msg_text = (
            "🧠 <b>ИЖТИМОИЙ ХОДИМ AI-КОНСУЛЬТАНТИ (МУАММО ЕЧИМИ)</b>\n\n"
            "Fuqaro muammosi, murakkab keys tavsifi, ariza matnini yozing yoki fuqaro murojaatining fotosuratini yuboring:\n\n"
            "💡 <b>Masalan:</b>\n"
            "• <i>«Fuqaro O. Karimova 2 nafar voyaga yetmagan farzandi bilan eri tomonidan uydan haydalgan, doimiy daromadi yo'q, ruhiy tazyiqqa uchragan. Qanday choralar ko'riladi?»</i>\n"
            "• <i>«1-guruh nogironi bo'lgan fuqaroga protez-ortopediya vositalari va moddiy yordam tayinlash mezonlari...»</i>\n"
            "• <i>Yoki fuqaro arizasi / tibbiy ma'lumotnoma fotosuratini yuboring.</i>\n\n"
            "<i>AI tizim yuklangan «Ijtimoiy AI bilimlari» hamda O'zbekiston qonunchiligi asosida 4 bosqichli to'liq yechim taqdim etadi.</i>"
        )
        bot.send_message(call.message.chat.id, msg_text, reply_markup=cancel_markup, parse_mode="HTML")


# --- 9. XABARLARNI FILTRLASH VA QABUL QILISH DISPETCHERI ---
def handle_admin_ai_message(bot: telebot.TeleBot, message, admin_state_dict: dict, is_admin_func, get_admin_menu_func) -> bool:
    """
    Admin tomonidan yuborilgan matn, hujjat yoki fotosuratlarni tekshiradi.
    Agar xabar ushbu modul holatiga tegishli bo'lsa, qayta ishlab True qaytaradi.
    Aks holda False qaytaradi.
    """
    user_id = message.from_user.id
    if not is_admin_func(user_id):
        return False

    text = (getattr(message, "text", "") or getattr(message, "caption", "") or "").strip()

    # Bekor qilish tekshiruvi
    if text in ["🔙 бекор қилиш", "бекор қилиш", "🔙 bekor qiliş", "🔙 bekor qilish", "bekor qiliş", "bekor qilish", "/cancel"]:
        if user_id in admin_state_dict and admin_state_dict[user_id].get("action") in ["waiting_for_admin_kb_upload", "waiting_for_ai_case"]:
            admin_state_dict.pop(user_id, None)
            bot.send_message(
                message.chat.id,
                "✅ Jarayon bekor qilindi. Admin boshqaruv paneli:",
                reply_markup=get_admin_menu_func(),
                parse_mode="HTML"
            )
            return True

    state_info = admin_state_dict.get(user_id, {})
    current_action = state_info.get("action")

    if not current_action:
        return False

    # --- HOLAT 1: BILIMLAR BAZASIGA HUJJAT/MATN QO'SHISH ---
    if current_action == "waiting_for_admin_kb_upload":
        # 1-A: Agar hujjat fayli (Document) yuborilgan bo'lsa
        if message.content_type == "document":
            doc = message.document
            fname = doc.file_name or "hujjat.txt"
            wait_m = bot.reply_to(
                message,
                f"⏳ <b>«{fname}»</b> qabul qilinmoqda, matn tozalanishi va parchalarga ajratilishi kutilmoqda...",
                parse_mode="HTML"
            )
            try:
                f_info = bot.get_file(doc.file_id)
                f_bytes = bot.download_file(f_info.file_path)
                res = add_document_to_admin_kb(f_bytes, fname, title=fname)

                success_text = (
                    "✅ <b>Hujjat muvaffaqiyatli saqlandi va indekslandi!</b>\n\n"
                    f"📄 <b>Nomi:</b> {res['title']}\n"
                    f"🆔 <b>Hujjat ID:</b> <code>{res['doc_id']}</code>\n"
                    f"📊 <b>Tozalangan matn hajmi:</b> {res['char_count']} ta belgi\n"
                    f"📑 <b>Яратилган RAG парчалари:</b> {res['chunk_count']} та\n"
                    f"🕒 <b>Saqlangan vaqt:</b> {res['created_at']}\n\n"
                    "<i>Endi «AI Yordamchi» ushbu hujjat qoidalari asosida ijtimoiy keyslarni tahlil qiladi.</i>"
                )
                admin_state_dict.pop(user_id, None)
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("➕ Яна маълумот қўшиш", callback_data="adm_social_kb_add"),
                    types.InlineKeyboardButton("📚 Билимлар базаси менюси", callback_data="adm_social_kb_menu")
                )
                bot.edit_message_text(success_text, message.chat.id, wait_m.message_id, reply_markup=markup, parse_mode="HTML")
            except Exception as e:
                bot.edit_message_text(f"❌ <b>Hujjatni yuklashda xatolik:</b>\n{e}", message.chat.id, wait_m.message_id, parse_mode="HTML")
            return True

        # 1-B: Agar to'g'ridan-to'g'ri matn yozilgan bo'lsa
        elif message.content_type == "text":
            wait_m = bot.reply_to(message, "⏳ Matn tahlil qilinmoqda va bazaga kiritilmoqda...", parse_mode="HTML")
            try:
                res = add_text_to_admin_kb(text)
                success_text = (
                    "✅ <b>Matn muvaffaqiyatli saqlandi va indekslandi!</b>\n\n"
                    f"📄 <b>Nomi:</b> {res['title']}\n"
                    f"🆔 <b>ID:</b> <code>{res['doc_id']}</code>\n"
                    f"📊 <b>Matn hajmi:</b> {res['char_count']} ta belgi\n"
                    f"📑 <b>Yaratilgan RAG parchalari:</b> {res['chunk_count']} ta\n\n"
                    "<i>Ma'lumot sun'iy intellekt xotirasiga biriktirildi.</i>"
                )
                admin_state_dict.pop(user_id, None)
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("➕ Яна маълумот қўшиш", callback_data="adm_social_kb_add"),
                    types.InlineKeyboardButton("📚 Билимлар базаси менюси", callback_data="adm_social_kb_menu")
                )
                bot.edit_message_text(success_text, message.chat.id, wait_m.message_id, reply_markup=markup, parse_mode="HTML")
            except Exception as e:
                bot.edit_message_text(f"❌ <b>Matnni saqlashda xatolik:</b> {e}", message.chat.id, wait_m.message_id, parse_mode="HTML")
            return True

    # --- HOLAT 2: AI KONSULTANT KEYS TAHLILI ---
    elif current_action == "waiting_for_ai_case":
        img_bytes = None
        case_description = text

        # 2-A: Agar ovozli xabar (voice yoki audio) yuborilgan bo'lsa
        if message.content_type in ["voice", "audio"]:
            try:
                audio_file_id = message.voice.file_id if message.content_type == "voice" else message.audio.file_id
                f_info = bot.get_file(audio_file_id)
                audio_bytes = bot.download_file(f_info.file_path)
                transcribed = transcribe_audio_bytes(audio_bytes, filename=f"admin_voice_{user_id}.ogg")
                if transcribed:
                    case_description = transcribed
                    bot.reply_to(
                        message,
                        f"🎙 <b>Ovozli xabaringiz matnga aylantirildi:</b>\n<i>«{case_description[:250]}...»</i>",
                        parse_mode="HTML"
                    )
            except Exception as v_err:
                print("Ovozli xabarni transkripsiya qilishda xatolik:", v_err)

        # 2-B: Agar rasm yuborilgan bo'lsa
        elif message.content_type == "photo":
            try:
                f_info = bot.get_file(message.photo[-1].file_id)
                img_bytes = bot.download_file(f_info.file_path)
                if not case_description:
                    case_description = "Fuqaroning taqdim etgan arizasi yoki hujjati fotosurati."
            except Exception as e:
                print("Rasmni yuklab olishda xatolik:", e)

        if not case_description and not img_bytes:
            bot.reply_to(message, "⚠️ Iltimos, muammo matnini yozing, ovozli xabar yoki fotosurat yuboring.")
            return True

        wait_m = bot.reply_to(
            message,
            "🧠 <b>Ijtimoiy xodim AI-konsultanti:</b>\n"
            "<i>Keys 'Ijtimoiy AI bilimlari' bazasi va IHMA qonunchiligi asosida chuqur tahlil qilinmoqda...</i>",
            parse_mode="HTML"
        )

        try:
            # PII niqoblash (O'RQ-547 talabi): AI ga uzatishdan oldin JShShIR, Pasport, Telefon yashiriladi
            masked_case = mask_pii(case_description)

            solution_text = ask_ai_consultant(masked_case, image_bytes=img_bytes)

            # 1. Telegraph maqolasi yaratish (Instant View)
            clean_case_title = "Shayx-Ali MFY | Keys Tahlili va Xulosa"
            telegraph_url = publish_case_to_telegraph(clean_case_title, case_description, solution_text)

            # 2. Xotiraga keshlash (Admin Telegramda to'liq o'qishni xohlasa yoki Word yuklasa)
            import uuid
            cache_id = str(uuid.uuid4())[:8]
            _ai_solutions_cache[cache_id] = {
                "title": clean_case_title,
                "case": case_description,
                "text": solution_text,
                "telegraph_url": telegraph_url,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }

            admin_state_dict.pop(user_id, None)

            # 3. Telegram uchun estetik xulosa kartasi (Executive Summary Card)
            case_preview = case_description[:250] + ("..." if len(case_description) > 250 else "")

            summary_card = (
                "🏛 <b>ҚАРШИ ШАҲАР «ШАЙХ-АЛИ» МФЙ ИЖТИМОИЙ ХОДИМИ AI-КОНСУЛЬТАНТИ</b>\n\n"
                f"📋 <b>Таҳлил қилинган кейс / мурожаат:</b>\n"
                f"<i>{case_preview}</i>\n\n"
                "⚖️ <b>ҲУҚУҚИЙ ВА МЕТОДИК ТАҲЛИЛ ХУЛОСАСИ:</b>\n"
                "1️⃣ <b>Ҳуқуқий баҳо:</b> ИҲМА низомлари, ВМ-654 ва ВМ-62 мезонлари бўйича тўлиқ асосланди;\n"
                "2️⃣ <b>Амалий алгоритм:</b> Ижтимоий ходимнинг қадамба-қадам ҳаракатлар режаси ишлаб чиқилди;\n"
                "3️⃣ <b>Ижтимоий ёрдам:</b> Фуқарога мос хизмат турлари ва тайинлаш/рад этиш асослари белгиланди;\n"
                "4️⃣ <b>Расмий Далолатнома:</b> Маҳалла бешлиги (МФЙ раиси Ш. Қодиров, ҳоким ёрдамчиси Д. Қўчқаров, "
                "хотин-қизлар фаоли Н. Авазова, ёшлар етакчиси Ж. Саттаров ва ижтимоий ходим А. Жўраев) имзолаши учун "
                "тайёр расмий қоралама шакллантирилди.\n\n"
            )

            action_markup = types.InlineKeyboardMarkup(row_width=1)
            if telegraph_url:
                summary_card += (
                    "📖 <b>TO'LIQ MA'LUMOT VA DALOLATNOMA TELEGRAPH'DA TAYYOR!</b>\n"
                    "<i>Telegram xabarlari hajmi cheklangani sababli, barcha moddalar, to'liq tahliliy matn "
                    "va rasmiy Dalolatnoma loyihasi estetik va qulay Instant View formatida Telegraph sahifasida tayyorlandi:</i>"
                )
                action_markup.add(
                    types.InlineKeyboardButton("📖 Telegraph'да тўлиқ ўқиш (Инстант View)", url=telegraph_url),
                    types.InlineKeyboardButton("📄 Далолатномани Word (.docx) да юклаб олиш", callback_data=f"adm_ai_docx_{cache_id}"),
                    types.InlineKeyboardButton("📋 Телеграмда тўлиқ кўрсатиш", callback_data=f"adm_ai_show_{cache_id}"),
                )
            else:
                summary_card += "📋 <i>Quyidagi tugmalar orqali to'liq matn yoki Word dalolatnomani yuklashingiz mumkin:</i>"
                action_markup.add(
                    types.InlineKeyboardButton("📄 Далолатномани Word (.docx) да юклаб олиш", callback_data=f"adm_ai_docx_{cache_id}"),
                    types.InlineKeyboardButton("📋 Телеграмда тўлиқ кўрсатиш", callback_data=f"adm_ai_show_{cache_id}"),
                )

            action_markup.add(
                types.InlineKeyboardButton("📝 Янги кейс таҳлили", callback_data="adm_ai_consultant"),
                types.InlineKeyboardButton("📚 Ижтимоий AI билимлари", callback_data="adm_social_kb_menu"),
                types.InlineKeyboardButton("🔙 Админ Панелига қайтиш", callback_data="adm_back_main")
            )

            bot.edit_message_text(
                summary_card,
                message.chat.id,
                wait_m.message_id,
                reply_markup=action_markup,
                parse_mode="HTML"
            )

        except Exception as ai_e:
            bot.edit_message_text(
                f"❌ <b>AI Konsultant tahlilida xatolik:</b>\n{ai_e}\n\nIltimos, qaytadan urinib ko'ring.",
                message.chat.id,
                wait_m.message_id,
                parse_mode="HTML"
            )
        return True

    return False
