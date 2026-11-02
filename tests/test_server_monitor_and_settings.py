import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.server_monitor import (
    get_system_metrics,
    format_server_status_html,
    get_recent_logs,
    clean_logs_file,
)
import main


def test_server_metrics():
    m = get_system_metrics()
    assert "cpu_percent" in m
    assert "ram_percent" in m
    assert "disk_percent" in m
    assert "bot_uptime" in m
    assert "server_uptime" in m
    assert m["cpu_count"] > 0


def test_format_server_status_html():
    html_msg = format_server_status_html()
    assert "СЕРВЕР ВА БОТ МОНИТОРИНГ ҲОЛАТИ" in html_msg
    assert "Процессор (CPU):" in html_msg
    assert "Оператив хотира (RAM):" in html_msg
    assert "Диск хотираси:" in html_msg


def test_clean_logs_file(tmp_path):
    test_log = tmp_path / "test.log"
    with open(test_log, "w", encoding="utf-8") as f:
        for i in range(100):
            f.write(f"Log line {i}\n")
    
    # Trim to 20 lines
    res = clean_logs_file(str(test_log), keep_lines=20)
    assert "тозаланди" in res
    
    with open(test_log, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 20
    assert lines[-1] == "Log line 99\n"


def test_admin_settings_menu_buttons():
    menu = main.get_admin_panel_menu()
    callbacks = [btn.callback_data for row in menu.keyboard for btn in row]
    assert "adm_settings_menu" in callbacks
    assert "adm_server_status" in callbacks
    assert "adm_system_logs" in callbacks
    # Ensure adm_queues is removed
    assert "adm_queues" not in callbacks


def test_all_admin_settings_callbacks_dispatched():
    class MockUser:
        def __init__(self, uid):
            self.id = uid

    class MockChat:
        def __init__(self, cid):
            self.id = cid

    class MockMessage:
        def __init__(self, cid=7840350353, mid=100):
            self.chat = MockChat(cid)
            self.message_id = mid
            self.text = "Mock settings text"

    class MockCall:
        def __init__(self, action, uid=7840350353):
            self.id = "query_123"
            self.data = action
            self.from_user = MockUser(uid)
            self.message = MockMessage()

    callbacks_to_test = [
        "adm_server_status",
        "adm_system_logs",
        "adm_tunnel_info",
        "adm_ai_diagnostics",
        "adm_clean_cache",
        "adm_restart_prompt",
        "adm_settings_menu",
    ]

    with patch.object(main.bot, "answer_callback_query") as mock_ans, \
         patch.object(main.bot, "edit_message_text") as mock_edit, \
         patch.object(main.bot, "send_message") as mock_send:
        for action in callbacks_to_test:
            call = MockCall(action)
            main.handle_admin_panel_callbacks(call)
            assert mock_ans.called or mock_edit.called or mock_send.called


def test_admin_reply_command():
    class MockUser:
        def __init__(self, uid=7840350353):
            self.id = uid

    class MockMessage:
        def __init__(self, text):
            self.from_user = MockUser(7840350353)
            self.chat = MockUser(7840350353)
            self.text = text
            self.message_id = 1

    murojaat_id = main.database.save_murojaat(
        user_id="555001", savol="Javob buyrug'i sinovi", ai_javobi="", turi="SHAXSIY_MUROJAAT",
        muhimlik="ODDIY", status="Yangi",
    )

    with patch.object(main.bot, "send_message") as mock_send, \
         patch.object(main.bot, "reply_to"), \
         patch.object(main.bot, "register_next_step_handler") as mock_reg:
        msg = MockMessage(f"/javob {murojaat_id}")
        main.handle_reply_command(msg)
        assert mock_send.called
        assert mock_reg.called
        assert main.admin_state.get(7840350353, {}).get("reply_murojaat_id") == murojaat_id
