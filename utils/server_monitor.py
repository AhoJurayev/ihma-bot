# -*- coding: utf-8 -*-
"""
Server va tizim resurslarini monitoring qilish yordamchi moduli.
CPU, RAM, Disk, Uptime va loglarni boshqarish uchun psutil asosida qurilgan.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from typing import Dict, Any
import psutil

# Process start time
_BOT_START_TIME = datetime.now()


def format_bytes(size: float) -> str:
    """Format bytes into MB / GB."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def get_system_metrics() -> Dict[str, Any]:
    """Collects CPU, RAM, Disk, and Uptime metrics."""
    cpu_percent = psutil.cpu_percent(interval=0.2)
    cpu_count = psutil.cpu_count(logical=True)

    vmem = psutil.virtual_memory()
    ram_total = format_bytes(vmem.total)
    ram_used = format_bytes(vmem.used)
    ram_percent = vmem.percent

    disk = psutil.disk_usage("/")
    disk_total = format_bytes(disk.total)
    disk_used = format_bytes(disk.used)
    disk_percent = disk.percent

    # Bot Uptime
    bot_delta = datetime.now() - _BOT_START_TIME
    days = bot_delta.days
    hours, rem = divmod(bot_delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    bot_uptime_str = f"{days} kun, {hours:02d}:{minutes:02d}:{seconds:02d}"

    # Server Uptime
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    srv_delta = datetime.now() - boot_time
    s_days = srv_delta.days
    s_hours, s_rem = divmod(srv_delta.seconds, 3600)
    s_mins, _ = divmod(s_rem, 60)
    srv_uptime_str = f"{s_days} kun, {s_hours:02d}:{s_mins:02d}"

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram_total": ram_total,
        "ram_used": ram_used,
        "ram_percent": ram_percent,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_percent": disk_percent,
        "bot_uptime": bot_uptime_str,
        "server_uptime": srv_uptime_str,
    }


def format_server_status_html() -> str:
    """Formats system metrics into an attractive Telegram HTML message."""
    m = get_system_metrics()

    cpu_icon = "🟢" if m["cpu_percent"] < 60 else ("🟡" if m["cpu_percent"] < 85 else "🔴")
    ram_icon = "🟢" if m["ram_percent"] < 75 else ("🟡" if m["ram_percent"] < 90 else "🔴")
    disk_icon = "🟢" if m["disk_percent"] < 80 else ("🟡" if m["disk_percent"] < 92 else "🔴")

    msg = (
        "📊 <b>СЕРВЕР ВА БОТ МОНИТОРИНГ ҲОЛАТИ:</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🖥 <b>Процессор (CPU):</b> {cpu_icon} <code>{m['cpu_percent']}%</code> ({m['cpu_count']} ядро)\n"
        f"🧠 <b>Оператив хотира (RAM):</b> {ram_icon} <code>{m['ram_percent']}%</code>\n"
        f"   └ Банд: <code>{m['ram_used']}</code> / Жами: <code>{m['ram_total']}</code>\n"
        f"💾 <b>Диск хотираси:</b> {disk_icon} <code>{m['disk_percent']}%</code>\n"
        f"   └ Банд: <code>{m['disk_used']}</code> / Жами: <code>{m['disk_total']}</code>\n\n"
        f"⏱ <b>Бот иш вақти (Uptime):</b> <code>{m['bot_uptime']}</code>\n"
        f"🌐 <b>Сервер Uptime:</b> <code>{m['server_uptime']}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <i>Янгиланган вақт: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )
    return msg


def get_recent_logs(log_file_path: str, lines_count: int = 20) -> str:
    """Reads the last N lines of log files."""
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                recent = lines[-lines_count:]
                if recent:
                    return "".join(recent).strip()
        except Exception as e:
            return f"Лог файлини ўқишда хатолик: {e}"

    try:
        res = subprocess.run(
            ["journalctl", "--user", "-u", "ihma-bot", "-n", str(lines_count), "--no-pager"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        if res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return "Ҳозирча тизим логлари топилмади."


def clean_logs_file(log_file_path: str, keep_lines: int = 500) -> str:
    """Trims the log file to keep_lines to free disk space."""
    if not os.path.exists(log_file_path):
        return "Лог файли мавжуд эмас."
    try:
        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        old_size = len(lines)
        if old_size <= keep_lines:
            return f"Лог файли ҳажми нормал ({old_size} қатор). Қисқартириш шарт эмас."
        kept = lines[-keep_lines:]
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        return f"Лог файли тозаланди: {old_size} қатордан {keep_lines} қаторга қисқартирилди."
    except Exception as e:
        return f"Логни тозалашда хатолик: {e}"
