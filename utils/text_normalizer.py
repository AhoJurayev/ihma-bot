# -*- coding: utf-8 -*-
"""
Ўзбек тили алифбо нормализатори ва конвертори (Text Normalizer & Cyrillic Converter).
Лотин (эски ва янги) ёзувидаги матнларни қидирув учун ягона стандартга келтиради
ҳамда барча лотинча матнларни мукаммал Ўзбек Кирилл алифбосига ўгиради.
"""

import re

CYR_TO_LAT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "ғ": "g'", "қ": "q", "ҳ": "h",
    "А": "a", "Б": "b", "В": "v", "Г": "g", "Д": "d", "Е": "e", "Ё": "yo", "Ж": "j",
    "З": "z", "И": "i", "Й": "y", "К": "k", "Л": "l", "М": "m", "Н": "n", "О": "o",
    "П": "p", "Р": "r", "С": "s", "Т": "t", "У": "u", "Ф": "f", "Х": "x", "Ц": "ts",
    "Ч": "ch", "Ш": "sh", "Щ": "sh", "Ъ": "'", "Ь": "", "Э": "e", "Ю": "yu", "Я": "ya",
    "Ў": "o'", "Ғ": "g'", "Қ": "q", "Ҳ": "h"
}


def normalize_for_search(text: str) -> str:
    """
    Ҳар қандай алифбодаги ўзбекча матнни қидирув учун ягона стандартга келтиради:
    - Янги лотин (ş, ç, ó, ǵ) -> sh, ch, o', g'
    - Кирилл алифбоси -> лотин алифбоси
    - Барча апостроф вариантлари (‘, ’, ʻ, ʼ, `, ?) -> '
    - Кичик ҳарфларга ўтказиш ва ортиқча белгиларни тозалаш
    """
    if not text:
        return ""
    s = str(text).lower()

    # 1. Янги лотин ҳарфларини стандартлаштириш
    s = s.replace("ş", "sh").replace("ç", "ch").replace("ó", "o'").replace("ǵ", "g'")

    # 2. Кирилл ҳарфларини транслитерация қилиш
    res = []
    for ch in s:
        res.append(CYR_TO_LAT_MAP.get(ch, ch))
    s = "".join(res)

    # 3. Барча турдаги апострофларни ягона стандарт (') га келтириш
    s = re.sub(r"[\u2018\u2019\u02bb\u02bc`?]", "'", s)

    # 4. Тиниш белгиларини бўшлиқ билан алмаштириш ва тозалаш
    s = re.sub(r"[^\w\s']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def text_matches(query: str, target: str) -> bool:
    """
    Фойдаланувчи қайси алифбода ёзишидан қатъи назар,
    query матни target матн ичида борлигини 100% аниқликда текширади.
    """
    norm_query = normalize_for_search(query)
    norm_target = normalize_for_search(target)
    if not norm_query or not norm_target:
        return False
    return norm_query in norm_target


# Кириллга ўгирилмайдиган қисмлар: <code>/<pre> блоклари, HTML теглар ва entity лар,
# URL ва домен номлари, ҳамда M-1001 / Q-0001 / N-101 кўринишидаги рақамлар.
_CONVERSION_PROTECTED_RE = re.compile(
    r"(<code>.*?</code>|<pre>.*?</pre>|<[^>]+>"
    r"|&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);"
    r"|https?://[^\s<>\"]+|\b(?:my\.gov\.uz|ihma\.uz)\b"
    r"|\b[MQN]-\d+\b)",
    re.DOTALL,
)


def latin_to_cyrillic_uz(text: str) -> str:
    """
    Ўзбек лотин ёзувидаги матнни (HTML теглари ва URL манзилларни бузмасдан)
    мукаммал, бенуқсон Кирилл ёзувига ўгиради.
    Янги лотин (ó, ǵ, ş, ç) ва анъанавий (o', g', sh, ch) ҳарфларини тўлиқ қўллайди.
    """
    if not text:
        return ""
    # HTML entity va apostroflarni tozalash
    source = str(text).replace("&#x27;", "'").replace("&#39;", "'").replace("&apos;", "'").replace("&quot;", '"')
    parts = _CONVERSION_PROTECTED_RE.split(source)
    out = []
    for p in parts:
        if _CONVERSION_PROTECTED_RE.fullmatch(p):
            out.append(p)
            continue

        s = p
        # 1. Янги лотин ҳарфлари
        s = s.replace("Ó", "Ў").replace("ó", "ў")
        s = s.replace("Ǵ", "Ғ").replace("ǵ", "ғ")
        s = s.replace("Ş", "Ш").replace("ş", "ш")
        s = s.replace("Ç", "Ч").replace("ç", "ч")

        # 2. Ў ва Ғ (турли апострофлар билан — ҳам лотин, ҳам кирилл o/g)
        s = re.sub(r"[O0О][\‘\’\`\´\ʼ\'\ʻ]", "Ў", s)
        s = re.sub(r"[oо][\‘\’\`\´\ʼ\'\ʻ]", "ў", s)
        s = re.sub(r"[GГ][\‘\’\`\´\ʼ\'\ʻ]", "Ғ", s)
        s = re.sub(r"[gг][\‘\’\`\´\ʼ\'\ʻ]", "ғ", s)

        # 3. Ҳарф бирикмалари
        s = s.replace("Sh", "Ш").replace("SH", "Ш").replace("sh", "ш")
        s = s.replace("Ch", "Ч").replace("CH", "Ч").replace("ch", "ч")
        s = s.replace("Yo", "Ё").replace("YO", "Ё").replace("yo", "ё")
        s = s.replace("Yu", "Ю").replace("YU", "Ю").replace("yu", "ю")
        s = s.replace("Ya", "Я").replace("YA", "Я").replace("ya", "я")
        s = s.replace("Ye", "Е").replace("YE", "Е").replace("ye", "е")
        s = s.replace("Ts", "Ц").replace("TS", "Ц").replace("ts", "ц")

        res = []
        for i, c in enumerate(s):
            prev_c = s[i - 1] if i > 0 else " "
            if c == "E":
                if i == 0 or not prev_c.isalpha():
                    res.append("Э")
                else:
                    res.append("Е")
                continue
            elif c == "e":
                if i == 0 or not prev_c.isalpha():
                    res.append("э")
                else:
                    res.append("е")
                continue

            mp = {
                "A": "А", "a": "а", "B": "Б", "b": "б", "D": "Д", "d": "д",
                "F": "Ф", "f": "ф", "G": "Г", "g": "г", "H": "Ҳ", "h": "ҳ",
                "I": "И", "i": "и", "J": "Ж", "j": "ж", "K": "К", "k": "к",
                "L": "Л", "l": "л", "M": "М", "m": "м", "N": "Н", "n": "н",
                "O": "О", "o": "о", "P": "П", "p": "п", "Q": "Қ", "q": "қ",
                "R": "Р", "r": "р", "S": "С", "s": "с", "T": "Т", "t": "т",
                "U": "У", "u": "у", "V": "В", "v": "в", "X": "Х", "x": "х",
                "Y": "Й", "y": "й", "Z": "З", "z": "з",
                "'": "ъ", "‘": "ъ", "’": "ъ", "ʼ": "ъ", "`": "ъ",
            }
            res.append(mp.get(c, c))
        converted_part = "".join(res)
        converted_part = re.sub(r"Жо[\‘\’\`\´\ʼ\'\ʻ]?раев", "Жўраев", converted_part, flags=re.IGNORECASE)
        converted_part = re.sub(r"Жораев", "Жўраев", converted_part, flags=re.IGNORECASE)
        converted_part = re.sub(r"Қучқаров", "Қўчқаров", converted_part, flags=re.IGNORECASE)
        converted_part = re.sub(r"Кучкаров", "Қўчқаров", converted_part, flags=re.IGNORECASE)
        out.append(converted_part)
    return "".join(out)


def ensure_cyrillic(text: str) -> str:
    """
    Агар матнда биронта лотин ҳарфи бўлса, уни автоматик тарзда
    Ўзбек Кирилл ёзувига ўгиради.
    """
    if not text:
        return ""
    # Агар лотин ҳарфлари мавжуд бўлса
    if re.search(r"[A-Za-zóǵşçÓǴŞÇ]", str(text)):
        return latin_to_cyrillic_uz(text)
    return str(text)
