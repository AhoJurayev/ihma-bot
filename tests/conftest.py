# -*- coding: utf-8 -*-
"""Testlar haqiqiy bazaga, fayllarga va tokenga tegmasligi uchun modullar yuklanishidan oldin muhitni sozlaydi."""

import atexit
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="ihma_pytest_")
atexit.register(shutil.rmtree, _TEST_DATA_DIR, ignore_errors=True)

os.environ["IHMA_DATA_DIR"] = _TEST_DATA_DIR
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_test_token"
os.environ["ADMIN_ID"] = "7840350353"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""
os.environ.pop("ADMIN_TELEGRAPH_PUBLISH", None)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)


def future_weekday(index: int = 0) -> str:
    """Bugundan keyingi `index`-ish kuni (Dushanba-Juma) ni YYYY-MM-DD ko'rinishida qaytaradi."""
    day = date.today()
    remaining = index
    while True:
        day += timedelta(days=1)
        if day.weekday() < 5:
            if remaining == 0:
                return day.isoformat()
            remaining -= 1


def next_weekend_day() -> str:
    """Eng yaqin shanba."""
    day = date.today() + timedelta(days=1)
    while day.weekday() != 5:
        day += timedelta(days=1)
    return day.isoformat()
