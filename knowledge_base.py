# -*- coding: utf-8 -*-
"""
Shayxali MFY Ijtimoiy Xodim AI Agent — Universal Bilimlar Bazasi va RAG Tizimi
Barcha turdagi ma'lumotlarni (PDF, DOC, DOCX, TXT, RTF, XLSX, XLS, CSV) o'qish,
moddalarga bo'lish, qonuniy tahlil qilish va qat'iy Grounding asosida javob berish.
"""

import os
import re
import json
import zipfile
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pandas as pd
except ImportError:
    pd = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HUJJATLAR_DIR = os.path.join(BASE_DIR, "hujjatlar")
OCR_CACHE_DIR = os.path.join(HUJJATLAR_DIR, ".ocr_cache")
INDEX_FILE = os.path.join(BASE_DIR, "knowledge_index.json")

os.makedirs(HUJJATLAR_DIR, exist_ok=True)
os.makedirs(OCR_CACHE_DIR, exist_ok=True)

# Lotin - Kirill konvertatsiya xaritasi (qidiruv aniqligi uchun)
LAT_TO_CYR_MAP = {
    "o'": "ў", "g'": "ғ", "sh": "ш", "ch": "ч", "yo": "ё", "yu": "ю", "ya": "я",
    "o‘": "ў", "g‘": "ғ",
    "a": "а", "b": "б", "d": "д", "e": "э", "f": "ф", "g": "г", "h": "ҳ",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "x": "х", "y": "й", "z": "з",
}

CYR_TO_LAT_MAP = {
    "ў": "o'", "ғ": "g'", "ш": "sh", "ч": "ch", "ё": "yo", "ю": "yu", "я": "ya",
    "а": "a", "б": "b", "д": "d", "э": "e", "ф": "f", "г": "g", "ҳ": "h",
    "и": "i", "ж": "j", "k": "к", "l": "l", "м": "m", "n": "n", "o": "o",
    "п": "p", "қ": "q", "р": "r", "с": "s", "т": "t", "у": "u", "в": "v",
    "х": "x", "й": "y", "з": "z", "е": "e", "ц": "ts", "щ": "sh", "ъ": "'",
}


def normalize_search_text(text: str) -> str:
    """Matnni qidiruv uchun tozalash va kichik harflarga o'tkazish."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s\-\']", " ", text)
    return " ".join(text.split())


def transliterate_to_cyrillic(text: str) -> str:
    res = text.lower()
    for lat, cyr in LAT_TO_CYR_MAP.items():
        res = res.replace(lat, cyr)
    return res


def transliterate_to_latin(text: str) -> str:
    res = text.lower()
    for cyr, lat in CYR_TO_LAT_MAP.items():
        res = res.replace(cyr, lat)
    return res


# ==============================================================================
# 1. BARCHA TURDAGI HUJJATLARNI O'QISH FUNKSIYALARI
# ==============================================================================

def extract_text_from_pdf(filepath: str) -> list:
    """1. PDF fayllarni sahifama-sahifa o'qish (raqamli matn va OCR keshli skanerlar)."""
    fname = os.path.basename(filepath)
    cached_file = os.path.join(OCR_CACHE_DIR, f"{fname}.txt")
    if os.path.exists(cached_file):
        try:
            with open(cached_file, "r", encoding="utf-8") as cf:
                cached_text = cf.read().strip()
                if cached_text:
                    return [{"page": 1, "text": cached_text}]
        except Exception:
            pass

    pages_text = []
    if pypdf is None:
        return pages_text

    try:
        reader = pypdf.PdfReader(filepath)
        for idx, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            txt = txt.strip()
            if txt:
                pages_text.append({"page": idx + 1, "text": txt})
    except Exception as e:
        print(f"⚠️ PDF o'qishda xatolik ({fname}): {e}")

    return pages_text


def extract_text_from_doc(filepath: str) -> list:
    """2. Eski Microsoft Word (.doc) va RTF (.rtf) fayllarini to'liq o'qish."""
    text = ""
    try:
        # macOS tizimida o'rnatilgan yuqori aniqlikdagi textutil
        res = subprocess.run(
            ["textutil", "-convert", "txt", filepath, "-stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=15,
        )
        text = res.stdout.decode("utf-8", errors="ignore").strip()
    except Exception:
        # Zaxira usul: binar oqimdan matn bloklarini filtrlash
        try:
            with open(filepath, "rb") as f:
                raw = f.read()
                words = re.findall(b"[\x20-\x7E\xA0-\xFF\x04\x00-\x04\xFF]{4,}", raw)
                text = " ".join([w.decode("latin1", errors="ignore") for w in words])
        except Exception as e:
            print(f"⚠️ DOC o'qishda xatolik ({os.path.basename(filepath)}): {e}")

    if text and len(text) > 30:
        return [{"page": 1, "text": text}]
    return []


def extract_text_from_docx(filepath: str) -> list:
    """3. Yangi Microsoft Word (.docx) fayllarini xatboshilar va jadvallar bilan o'qish."""
    paragraphs = []
    try:
        with zipfile.ZipFile(filepath) as z:
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

            for elem in tree.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag in ["p", "tr"]:
                    texts = [node.text for node in elem.iterfind(".//w:t", namespaces) if node.text]
                    if texts:
                        line = "".join(texts).strip()
                        if line and (not paragraphs or paragraphs[-1] != line):
                            paragraphs.append(line)
    except Exception as e:
        print(f"⚠️ DOCX o'qishda xatolik ({os.path.basename(filepath)}): {e}")

    full_text = "\n\n".join(paragraphs)
    if full_text:
        return [{"page": 1, "text": full_text}]
    return []


def extract_text_from_txt(filepath: str) -> list:
    """4. Oddiy matn (.txt, .text, .md) fayllarini ko'p kodlashda (UTF-8, CP1251) o'qish."""
    encodings = ["utf-8", "windows-1251", "cp1251", "utf-16", "latin1"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                txt = f.read().strip()
                if txt:
                    return [{"page": 1, "text": txt}]
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"⚠️ TXT o'qishda xatolik ({os.path.basename(filepath)}): {e}")
            break
    return []


def extract_text_from_excel(filepath: str, max_rows: int = 60) -> list:
    """5. Excel jadvallari (.xlsx, .xls, .csv) dan mezonlar va ma'lumotlarni o'qish."""
    if pd is None:
        return []

    sheets_data = []
    try:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == ".csv":
            df = pd.read_csv(filepath, nrows=max_rows, dtype=str).dropna(how="all")
            if not df.empty:
                cols = [str(c) for c in df.columns if "Unnamed" not in str(c)]
                lines = ["Ustunlar: " + " | ".join(cols)]
                for _, row in df.head(40).iterrows():
                    vals = [f"{k}: {v}" for k, v in row.items() if str(v).strip() and str(v) != "nan" and "Unnamed" not in str(k)]
                    if vals:
                        lines.append("• " + "; ".join(vals[:6]))
                sheets_data.append({"page": 1, "text": "\n".join(lines)})
        else:
            xl = pd.ExcelFile(filepath)
            for idx, sname in enumerate(xl.sheet_names[:4]):
                df = xl.parse(sname, nrows=max_rows, dtype=str).dropna(how="all")
                if not df.empty:
                    cols = [str(c) for c in df.columns if "Unnamed" not in str(c)]
                    lines = [f"=== VARAQ: {sname} ===", "Ustunlar: " + " | ".join(cols)]
                    for _, row in df.head(25).iterrows():
                        vals = [f"{k}: {v}" for k, v in row.items() if str(v).strip() and str(v) != "nan" and "Unnamed" not in str(k)]
                        if vals:
                            lines.append("• " + "; ".join(vals[:6]))
                    sheets_data.append({"page": idx + 1, "text": "\n".join(lines)})
    except Exception as e:
        print(f"⚠️ Excel o'qishda xatolik ({os.path.basename(filepath)}): {e}")

    return sheets_data


def extract_text_from_image(filepath: str) -> list:
    """6. Rasm va skaner hujjatlar (.png, .jpg, .jpeg, .webp) dan matnni OCR orqali olish."""
    fname = os.path.basename(filepath)
    cached_file = os.path.join(OCR_CACHE_DIR, f"{fname}.txt")
    if os.path.exists(cached_file):
        try:
            with open(cached_file, "r", encoding="utf-8") as cf:
                cached_text = cf.read().strip()
                if cached_text:
                    return [{"page": 1, "text": cached_text}]
        except Exception:
            pass

    try:
        from PIL import Image
        import google.generativeai as genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            env_file = os.path.join(BASE_DIR, ".env")
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line and not line.startswith("#"):
                            k, v = line.strip().split("=", 1)
                            if k == "GEMINI_API_KEY":
                                api_key = v
                                break
        if api_key:
            genai.configure(api_key=api_key)
            model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash")
            model = genai.GenerativeModel(model_name)

            pil_img = Image.open(filepath)
            if max(pil_img.size) > 2000:
                pil_img.thumbnail((2000, 2000))

            prompt = (
                "Ushbu skaner qilingan yoki suratga olingan huquqiy qaror/buyruq matnini to'liq, "
                "so'zma-so'z o'zbek tilida yozib ber. Barcha moddalar, bandlar, jadvallar va raqamlarni aniq ko'rsat."
            )
            res = model.generate_content([pil_img, prompt])
            text = (res.text or "").strip()
            if text:
                with open(cached_file, "w", encoding="utf-8") as cf:
                    cf.write(text)
                return [{"page": 1, "text": text}]
    except Exception as e:
        print(f"⚠️ Rasm OCR xatolik ({fname}): {e}")

    return []


def extract_text_universal(filepath: str) -> list:
    """Hujjat kengaytmasiga qarab tegishli o'quvchi funksiyaga yo'naltiradi."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext in [".doc", ".rtf"]:
        return extract_text_from_doc(filepath)
    elif ext == ".docx":
        return extract_text_from_docx(filepath)
    elif ext in [".txt", ".text", ".md", ".log"]:
        return extract_text_from_txt(filepath)
    elif ext in [".xlsx", ".xls", ".csv"]:
        return extract_text_from_excel(filepath)
    elif ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        return extract_text_from_image(filepath)
    return []


# ==============================================================================
# 2. MATNNI MODDALAR VA PARCHALARGA BO'LISH (CHUNKING)
# ==============================================================================

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> list:
    """Matnni mantiqiy qismlarga (parchalarga) ajratish."""
    if not text:
        return []

    words = text.split()
    if len(words) <= 150:
        return [text]

    chunks = []
    step = max(50, chunk_size - overlap)
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(text_len, start + chunk_size)
        if end < text_len:
            space_idx = text.rfind(" ", start, end)
            if space_idx > start + 200:
                end = space_idx

        segment = text[start:end].strip()
        if segment and len(segment) > 80:
            chunks.append(segment)

        start += step

    return chunks


# ==============================================================================
# 3. BILIMLAR BAZASINI INDEKSLASH VA SAQLASH
# ==============================================================================

SUPPORTED_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".txt", ".text", ".rtf", ".md", ".xlsx", ".xls", ".csv",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp"
)


def build_knowledge_index() -> dict:
    """
    hujjatlar/ papkasidagi barcha PDF, DOC, DOCX, TXT, RTF, XLSX fayllarni tahlil qilib,
    qidiruv indeksini (knowledge_index.json) yangilaydi.
    """
    files = [
        f for f in os.listdir(HUJJATLAR_DIR)
        if f.lower().endswith(SUPPORTED_EXTENSIONS) and not f.startswith("~$")
    ]

    all_chunks = []
    documents_meta = []

    for fname in sorted(files):
        fpath = os.path.join(HUJJATLAR_DIR, fname)
        size_kb = round(os.path.getsize(fpath) / 1024, 1)

        pages_data = extract_text_universal(fpath)
        total_pages = len(pages_data)
        doc_chunks_count = 0

        for p_item in pages_data:
            page_no = p_item["page"]
            text_content = p_item["text"]
            segments = chunk_text(text_content, chunk_size=1200, overlap=200)

            for c_idx, seg in enumerate(segments):
                chunk_id = f"{fname}_p{page_no}_c{c_idx+1}"
                norm_text = normalize_search_text(seg)
                cyr_text = transliterate_to_cyrillic(norm_text)
                lat_text = transliterate_to_latin(norm_text)

                all_chunks.append({
                    "id": chunk_id,
                    "filename": fname,
                    "page": page_no,
                    "content": seg,
                    "search_terms": f"{norm_text} {cyr_text} {lat_text}",
                })
                doc_chunks_count += 1

        documents_meta.append({
            "filename": fname,
            "size_kb": size_kb,
            "pages": total_pages,
            "chunks": doc_chunks_count,
        })

    index_data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_documents": len(documents_meta),
        "total_chunks": len(all_chunks),
        "documents": documents_meta,
        "chunks": all_chunks,
    }

    try:
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Indeksni saqlashda xatolik: {e}")

    return index_data


def load_knowledge_index() -> dict:
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return build_knowledge_index()


# ==============================================================================
# 4. QONUNIY QIDIRUV VA GROUNDING PROMPTI (ZERO-HALLUCINATION)
# ==============================================================================

def search_knowledge_base(query: str, top_k: int = 4) -> list:
    """
    Fuqaro savoli bo'yicha bazadagi barcha qonun, qaror va jadvallardan
    eng mos parchalarni qidiradi.
    """
    index_data = load_knowledge_index()
    chunks = index_data.get("chunks", [])
    if not chunks:
        return []

    norm_query = normalize_search_text(query)
    cyr_query = transliterate_to_cyrillic(norm_query)
    lat_query = transliterate_to_latin(norm_query)

    query_words = set(norm_query.split() + cyr_query.split() + lat_query.split())
    stopwords = {"va", "hamda", "yoki", "uchun", "bilan", "deb", "esa", "kerak", "nima", "qanday", "bu", "shu"}
    meaningful_words = [w for w in query_words if len(w) >= 3 and w not in stopwords]

    if not meaningful_words:
        return []

    scored_chunks = []
    for c in chunks:
        score = 0
        search_field = c.get("search_terms", "")
        fname_lower = c.get("filename", "").lower()

        # 1. Hujjat nomi yoki buyruq raqami to'g'ri kelsa katta ball
        for w in meaningful_words:
            if w in fname_lower:
                score += 20

        # 2. Kalit so'zlar uchrashi
        for w in meaningful_words:
            if f" {w} " in f" {search_field} " or f" {w}" in search_field:
                score += 5

        # 3. Butun ibora mos kelsa katta bonus
        if norm_query in search_field or cyr_query in search_field or lat_query in search_field:
            score += 30

        if score > 0:
            scored_chunks.append((score, c))

    scored_chunks.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_chunks[:top_k]]


def format_legal_grounding_prompt(query: str, top_chunks: list) -> str:
    """
    RAG konteksti va O'zbekiston qonunchiligi bo'yicha kengaytirilgan bilimlar bazasi integratsiyasi.
    """
    context_str = ""
    if top_chunks:
        context_parts = []
        for c in top_chunks:
            header = f"[HUJJAT: {c.get('filename')} | Sahifa/Qism: {c.get('page')}]"
            context_parts.append(f"{header}\n{c.get('content')}")
        context_str = "\n\n" + ("=" * 60) + "\n\n".join(context_parts) + "\n" + ("=" * 60)

    prompt = (
        "\n\n### ⚖️ MAHALLA BILIMLAR BAZASIDAN TOPILGAN RASMIY HUQUQIY HUJJATLAR MATNLARI:\n"
        f"{context_str}\n\n"
        "### 💡 JAVOB BERISH STANDARTLARI (ANIQLIK VA KENGAYTIRILGAN BILIMLAR):\n"
        "1. Agar yuqorida keltirilgan mahalliy hujjatlar bo'laklarida savolga oid aniq faktlar bo'lsa, ulardan to'liq va asosli foydalaning.\n"
        "2. Agar savol (masalan: «IHMA qachon tuzilgan?», «Qonun qachon chiqqan?», «Nafaqa qanday hisoblanadi?») bo'yicha yuqoridagi mahalla hujjatlari bo'laklarida to'liq javob bo'lmasa, o'zingizning O'zbekiston Respublikasi qonunchiligi (Prezident Farmon va Qarorlari, xususan 2023-yil 1-iyundagi PF-82-son Farmon, Vazirlar Mahkamasi qarorlari, lex.uz) bo'yicha umumiy va chuqur bilimlaringizdan foydalanib ANIQ, TO'LIQ VA FAKTLAR ASOSIDA javob bering.\n"
        "3. QAT'IYAN TAQIQLANADI: «Mahalla bazasida bu hujjat keltirilmagan» yoki «Hujjatlarda to'liq ko'rsatma mavjud emas» deb javob qaytarmang! Savolga to'g'ridan-to'g'ri faktlar bilan, lo'nda va tushunarli tarzda javob bering.\n"
        "4. Javobingiz do'stona, samimiy, oddiy xalq tilida va asosiy mohiyatni punktlar (•) bilan ajratgan holda yozilsin.\n"
        "5. QAT'IY MOLIYAVIY VA HUQUQIY QOIDA: Qonun va qarorlar bo'yicha to'lov, nafaqa va yordam miqdorlari haqida gapirganda TAXMINIY SO'M SUMMALARINI (masalan: «taxminan 500 000 so'm», «750 000 so'm atrofida») ASLO YOZMANG! Barcha miqdorlarni FAQAT qonunda belgilangan BXM (Bazaviy hisoblash miqdori) yoki MIH (Minimal iste'mol xarajatlari) ko'rsatkichlarida (masalan: «BXMning 50 foizi miqdorida», «BXMning 2 baravari miqdorida», «MIH chegarasi bo'yicha») ko'rsating!"
    )
    return prompt


def get_knowledge_base_stats() -> dict:
    idx = load_knowledge_index()
    return {
        "total_documents": idx.get("total_documents", 0),
        "total_chunks": idx.get("total_chunks", 0),
        "updated_at": idx.get("updated_at", "Noma'lum"),
        "documents": idx.get("documents", []),
    }
