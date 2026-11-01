# -*- coding: utf-8 -*-
"""
Telegram Mini App (TMA) initData Authentication and Validation Module.
Implements the official Telegram Web Apps authentication algorithm:
HMAC-SHA256 signature verification, auth_date freshness check, and secure user parsing.
"""

import os
import json
import time
import hmac
import hashlib
import urllib.parse
from typing import Optional, Dict, Any, Tuple


DEFAULT_AUTH_MAX_AGE = 86400  # 24 hours in seconds


def parse_init_data(init_data_raw: str) -> Dict[str, str]:
    """Parse raw query string initData into a dictionary of key-value pairs."""
    if not init_data_raw:
        return {}
    
    # Strip optional 'tma ' or 'Bearer ' prefix if passed from Authorization header
    raw = init_data_raw.strip()
    if raw.lower().startswith("tma "):
        raw = raw[4:].strip()
    elif raw.lower().startswith("bearer "):
        raw = raw[7:].strip()

    parsed = urllib.parse.parse_qsl(raw, keep_blank_values=True)
    return dict(parsed)


def compute_init_data_hash(data: Dict[str, str], bot_token: str) -> str:
    """Compute the HMAC-SHA256 signature for the given data dictionary according to Telegram specification."""
    filtered_items = [f"{k}={v}" for k, v in sorted(data.items()) if k != "hash"]
    data_check_string = "\n".join(filtered_items)
    
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def create_test_init_data(user_dict: Dict[str, Any], bot_token: str, auth_date: Optional[int] = None, query_id: str = "AAHdF6IQAAAAAN0XohD_test") -> str:
    """
    Helper to generate valid cryptographically signed initData strings for testing and automation.
    """
    if auth_date is None:
        auth_date = int(time.time())
    
    data = {
        "auth_date": str(auth_date),
        "query_id": query_id,
        "user": json.dumps(user_dict, separators=(",", ":"), ensure_ascii=False)
    }
    
    data_hash = compute_init_data_hash(data, bot_token)
    data["hash"] = data_hash
    
    return urllib.parse.urlencode(data)


def verify_telegram_init_data(
    init_data_raw: str,
    bot_token: str,
    max_age_seconds: int = DEFAULT_AUTH_MAX_AGE
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Verify Telegram WebApp initData string.

    Returns:
        (is_valid, user_data_dict, error_message)
    """
    if not init_data_raw or not isinstance(init_data_raw, str):
        return False, None, "initData kiritilmadi (bo'sh)"

    if not bot_token:
        return False, None, "Server bot_token topilmadi"

    data = parse_init_data(init_data_raw)
    if "hash" not in data:
        return False, None, "initData ichida 'hash' imzosi mavjud emas"

    received_hash = data.get("hash", "")
    
    # 1. Signature check
    calculated_hash = compute_init_data_hash(data, bot_token)
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False, None, "Telegram raqamli imzosi noto'g'ri (soxtalashtirilgan bo'lishi mumkin)"

    # 2. auth_date freshness check
    auth_date_str = data.get("auth_date")
    if not auth_date_str:
        return False, None, "auth_date mavjud emas"

    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return False, None, "auth_date formati noto'g'ri"

    now = int(time.time())
    # Reject if in the future by more than 60 seconds (clock skew tolerance)
    if auth_date > now + 60:
        return False, None, "auth_date kelajak vaqtiga tegishli"

    # Reject if expired
    if max_age_seconds > 0 and (now - auth_date) > max_age_seconds:
        return False, None, f"Telegram sessiyasi muddati o'tgan ({now - auth_date} soniya oldin yaratilgan)"

    # 3. User payload parsing
    user_json = data.get("user")
    if not user_json:
        return False, None, "initData ichida 'user' ma'lumoti topilmadi"

    try:
        user_data = json.loads(user_json)
    except Exception as e:
        return False, None, f"'user' JSON parse xatosi: {e}"

    if "id" not in user_data:
        return False, None, "'user' ichida 'id' maydoni mavjud emas"

    return True, user_data, "Muvaffaqiyatli"
