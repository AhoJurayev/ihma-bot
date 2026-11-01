# -*- coding: utf-8 -*-
"""
Шахсга доир маълумотларни ниқоблаш (PII Masker) модули.
Ўзбекистон Республикаси «Шахсга доир маълумотлар тўғрисида»ги Қонуни (ЎРҚ-547)
талабларига биноан, фуқаро маълумотлари ташқи AI (Google Gemini, Groq)
серверларига юборилишидан олдин махфий реквизитлар автоматик ниқобланади.

Ҳимояланган тоифалар:
1. 14 хонали ЖШШИР (PINFL)
2. Паспорт серияси ва рақами (2 та ҳарф + 7 та рақам)
3. Телефон рақамлари (+998...)
4. Банк пластик карта рақамлари (16 хонали)
5. Яшаш манзиллари (кўча, уй, хонадон)
6. Тиббий ташхислар ва ногиронлик гуруҳи маълумотлари
7. Ҳужжатлар ва OCR матнидан метамаълумотларни тозалаш

Эслатма: Регекс алгоритми структуралашган шахсий маълумотларни юқори аниқликда
ниқоблайди, бироқ табиий тилдаги эркин жумлалар хавфсизлиги учун қўшимча
ҳуқуқий ва инсоний назорат (defense-in-depth) доимо сақлаб қолинади.
"""

import re
from typing import Dict, Any

# 1. 14 хонали ЖШШИР (PINFL)
_PINFL_REGEX = re.compile(r"\b\d{14}\b")

# 2. Паспорт серияси ва рақами (2 та ҳарф + ихтиёрий чизиқча/бўшлиқ + 7 та рақам)
_PASSPORT_REGEX = re.compile(r"\b[A-Za-zА-Яа-яЎўҒғҚқҲҳ]{2}\s*[-–—]?\s*\d{7}\b")

# 3. Телефон рақамлари (+998 ва турли бўшлиқ/чизиқча вариантлари)
_PHONE_REGEX = re.compile(
    r"(?:\+?998[\s\-\.]?\(?\d{2}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{2}[\s\-\.]?\d{2}"
    r"|\(?\b9\d{1}\)?[\s\-\.]\d{3}[\s\-\.]\d{2}[\s\-\.]\d{2}"
    r"|\b998\d{9}\b)"
)

# 4. Банк пластик карта рақамлари (16 хонали: 8600, 9860, 5614, 4... ва б.)
_CARD_REGEX = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")

# 5. Манзил нақшлари (кўча, уй, хонадон, массив)
_ADDRESS_REGEX = re.compile(
    r"\b(?:[A-Za-zА-Яа-яЎўҒғҚқҲҳ0-9\-\'\u2018\u2019\u02bb\u02bc]+\s+)?(?:ko[\'\u2018\u2019\u02bb\u02bc`]?cha(?:si)?|kucha(?:si)?|кўча(?:си)?|куча(?:си)?)[,\s]+(?:\d+[-–]?(?:uy|xonadon|уй|хонадон)?|(?:uy|xonadon|уй|хонадон)\s*[:№]?\s*\d+[a-zA-Zа-яА-Я]?)\b",
    re.IGNORECASE
)

# 6. Нозик тиббий маълумотлар ва ногиронлик гуруҳлари
_MEDICAL_REGEX = re.compile(
    r"\b(?:[1-3][-–]?(?:guruh|гуруҳ)\s+nogiron(?:i|ligi)?|[1-3][-–]?(?:guruh|гуруҳ)\s+ногирон(?:и|лиги)?"
    r"|bolalikdan\s+nogiron(?:i|ligi)?|болаликдан\s+ногирон(?:и|лиги)?"
    r"|tashxisi|ташхиси|saraton|онкология|диагноз|ДЦП|cerebral\s+palsy|церебрал\s+фалаж)\b",
    re.IGNORECASE
)


def mask_pii(text: str) -> str:
    """
    Матн ичидаги барча шахсий ва нозик маълумотларни (ЖШШИР, Паспорт,
    Телефон, Банк картаси, Манзил ва Тиббий маълумотлар) ташқи AI
    хизматларига юборишдан олдин хавфсиз ниқоблайди.
    """
    if not text:
        return ""
    s = str(text)

    # 1. ЖШШИР ни ниқоблаш
    s = _PINFL_REGEX.sub("[ЖШШИР_ЯШИРИЛГАН]", s)

    # 2. Паспорт серия ва рақамини ниқоблаш
    s = _PASSPORT_REGEX.sub("[ПАСПОРТ_ЯШИРИЛГАН]", s)

    # 3. Банк пластик карта рақамларини ниқоблаш
    s = _CARD_REGEX.sub("[КАРТА_ЯШИРИЛГАН]", s)

    # 4. Телефон рақамларини ниқоблаш
    s = _PHONE_REGEX.sub("[ТЕЛ_ЯШИРИЛГАН]", s)

    # 5. Манзил нақшларини ниқоблаш
    s = _ADDRESS_REGEX.sub("[МАНЗИЛ_ЯШИРИЛГАН]", s)

    # 6. Нозик тиббий маълумотларни ниқоблаш
    s = _MEDICAL_REGEX.sub("[ТИББИЙ_МАЪЛУМОТ_ЯШИРИЛГАН]", s)

    return s


def has_pii(text: str) -> bool:
    """Матнда бирор шахсий ёки нозик маълумот борлигини текширади."""
    if not text:
        return False
    s = str(text)
    return bool(
        _PINFL_REGEX.search(s)
        or _PASSPORT_REGEX.search(s)
        or _PHONE_REGEX.search(s)
        or _CARD_REGEX.search(s)
        or _ADDRESS_REGEX.search(s)
        or _MEDICAL_REGEX.search(s)
    )


def mask_document_metadata(doc_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Ҳужжат ёки OCR натижасидан олинган метамаълумотларни хавфсиз тозалаш."""
    if not doc_dict or not isinstance(doc_dict, dict):
        return {}
    sanitized = {}
    for k, v in doc_dict.items():
        if isinstance(v, str):
            sanitized[k] = mask_pii(v)
        elif isinstance(v, list):
            sanitized[k] = [mask_pii(item) if isinstance(item, str) else item for item in v]
        elif isinstance(v, dict):
            sanitized[k] = mask_document_metadata(v)
        else:
            sanitized[k] = v
    return sanitized
