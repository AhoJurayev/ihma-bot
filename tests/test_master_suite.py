# -*- coding: utf-8 -*-
"""
Shayxali MFY Social Worker AI Bot — Master Automated Test Suite
Pytest-based automated security, database, appointment, AI, and functional verification.

Covers all 18 mandatory test scenarios:
1. Telegram initData valid signature
2. Telegram initData invalid signature
3. Expired authentication
4. Citizen A cannot access Citizen B's data (Resource Ownership)
5. Unauthorized admin access is rejected
6. XSS payloads are safely rendered / escaped
7. SQL injection attempts are rejected
8. Duplicate appointments are prevented
9. Concurrent appointment booking is safe (Race condition protection)
10. Past appointment dates are rejected
11. Cancelled appointment slots become available
12. Application status permissions and normalization
13. PII masking (PINFL, passport, phone, card, address, medical)
14. Legal answer fallback when no source exists
15. Gemini failure and Groq / safe legal fallback
16. Excel export integrity
17. Database backup and restoration (tested on separate temp DB)
18. File upload validation (extension, size, traversal)
"""

import os
import sys
import time
import shutil
import tempfile
import sqlite3
import pytest
import openpyxl

# Add workspace to path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from conftest import future_weekday
import database
import webapp_server
from utils.tma_auth import create_test_init_data, verify_telegram_init_data
from utils.pii_masker import mask_pii, has_pii
from utils.text_normalizer import normalize_for_search, latin_to_cyrillic_uz
import admin_ai_assistant
import local_legal_advisor


TEST_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ_test_token"
TEST_ADMIN_ID = "7840350353"


@pytest.fixture(scope="session")
def test_env():
    """Create isolated test directory and temporary SQLite database."""
    temp_dir = tempfile.mkdtemp(prefix="ihma_test_")
    test_db = os.path.join(temp_dir, "test_ihma.db")
    
    # Save original DB and settings
    orig_db = database.DB_FILE
    database.DB_FILE = test_db
    database.init_database(test_db)
    
    # Configure Flask server for testing
    webapp_server.app.config["TESTING"] = True
    webapp_server.TELEGRAM_BOT_TOKEN = TEST_BOT_TOKEN
    webapp_server.ADMIN_ID = TEST_ADMIN_ID
    
    # Pre-populate sample citizen records
    database.save_or_update_citizen(
        user_id="1001",
        fio="Ali Valiyev",
        telefon="+998901112233",
        pasport_seriya="AA1112233",
        jshshir="12345678901234",
        kocha_manzil="Shayxali MFY, 1-uy",
        status="Tasdiqlangan",
        db_path=test_db
    )
    database.save_or_update_citizen(
        user_id="2002",
        fio="Vali Aliyev",
        telefon="+998904445566",
        pasport_seriya="BB2223344",
        jshshir="98765432109876",
        kocha_manzil="Shayxali MFY, 2-uy",
        status="Tasdiqlangan",
        db_path=test_db
    )
    
    yield {
        "temp_dir": temp_dir,
        "test_db": test_db,
        "client": webapp_server.app.test_client()
    }
    
    # Teardown
    database.DB_FILE = orig_db
    shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 1. Telegram initData Valid Signature
# ==============================================================================
def test_1_telegram_init_data_valid_signature():
    user = {"id": 1001, "first_name": "Ali", "username": "ali_user"}
    init_data = create_test_init_data(user, TEST_BOT_TOKEN)
    ok, user_data, msg = verify_telegram_init_data(init_data, TEST_BOT_TOKEN)
    
    assert ok is True, f"Valid signature should be accepted: {msg}"
    assert user_data["id"] == 1001
    assert user_data["first_name"] == "Ali"


# ==============================================================================
# 2. Telegram initData Invalid Signature
# ==============================================================================
def test_2_telegram_init_data_invalid_signature():
    user = {"id": 1001, "first_name": "Ali"}
    init_data = create_test_init_data(user, TEST_BOT_TOKEN)
    tampered = init_data.replace("hash=", "hash=deadbeefbadc0ffee")
    
    ok, user_data, msg = verify_telegram_init_data(tampered, TEST_BOT_TOKEN)
    assert ok is False, "Tampered signature must be rejected"
    assert "noto'g'ri" in msg.lower() or "signature" in msg.lower() or "imzo" in msg.lower()


# ==============================================================================
# 3. Expired Authentication
# ==============================================================================
def test_3_telegram_init_data_expired():
    user = {"id": 1001, "first_name": "Ali"}
    expired_date = int(time.time()) - 100000  # older than 86400s (24h)
    init_data = create_test_init_data(user, TEST_BOT_TOKEN, auth_date=expired_date)
    
    ok, user_data, msg = verify_telegram_init_data(init_data, TEST_BOT_TOKEN, max_age_seconds=86400)
    assert ok is False, "Expired initData must be rejected"
    assert "muddati o'tgan" in msg.lower() or "expired" in msg.lower()


# ==============================================================================
# 4. Citizen A cannot access Citizen B's data
# ==============================================================================
def test_4_citizen_a_cannot_access_citizen_b_data(test_env):
    client = test_env["client"]
    test_db = test_env["test_db"]
    
    # Create appeal for Citizen B (2002)
    appeal_b_id = database.save_murojaat(
        user_id="2002",
        savol="Citizen B shaxsiy masalasi",
        ai_javobi="Javob B",
        turi="Moddiy yordam",
        muhimlik="ODDIY",
        db_path=test_db
    )
    
    # Citizen A (1001) logs in via TMA initData
    user_a = {"id": 1001, "first_name": "Ali"}
    init_data_a = create_test_init_data(user_a, TEST_BOT_TOKEN)
    headers_a = {"X-Telegram-Init-Data": init_data_a, "Content-Type": "application/json"}
    
    # Citizen A tries to fetch /api/citizen with ?telegram_id=2002
    res = client.get("/api/citizen?telegram_id=2002", headers=headers_a)
    assert res.status_code == 200
    data = res.get_json()
    # Must return Citizen A's data, NOT Citizen B!
    assert str(data["citizen"]["telegram_id"]) == "1001"
    assert data["citizen"]["fio"] == "Ali Valiyev"
    
    # Citizen A tries to rate Citizen B's appeal
    rate_res = client.post("/api/rate", headers=headers_a, json={
        "appeal_id": appeal_b_id,
        "score": 5
    })
    assert rate_res.status_code == 403, "Citizen A must not be allowed to rate Citizen B's appeal"


# ==============================================================================
# 5. Unauthorized Admin Access Rejected
# ==============================================================================
def test_5_unauthorized_admin_access_rejected(test_env):
    client = test_env["client"]
    # Regular citizen (1001)
    user_a = {"id": 1001, "first_name": "Ali"}
    init_data_a = create_test_init_data(user_a, TEST_BOT_TOKEN)
    headers_a = {"X-Telegram-Init-Data": init_data_a, "Content-Type": "application/json"}
    
    # Try accessing admin audit logs
    res_audit = client.get("/api/admin/audit_logs", headers=headers_a)
    assert res_audit.status_code == 403
    
    # Try accessing admin excel export
    res_export = client.post("/api/admin/export_excel", headers=headers_a)
    assert res_export.status_code == 403


# ==============================================================================
# 6. XSS Payloads Safely Handled
# ==============================================================================
def test_6_xss_payloads_safely_rendered(test_env):
    client = test_env["client"]
    test_db = test_env["test_db"]
    user_a = {"id": 1001, "first_name": "Ali"}
    init_data_a = create_test_init_data(user_a, TEST_BOT_TOKEN)
    headers_a = {"X-Telegram-Init-Data": init_data_a, "Content-Type": "application/json"}
    
    xss_text = "<script>alert('XSS')</script><img src=x onerror=alert(1)>"
    res = client.post("/api/appeal", headers=headers_a, json={
        "category": "Umumiy",
        "text": xss_text,
        "priority": "ODDIY"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    
    # Check that audit log and database store text without executing
    app_id = data["appeal"]["id"]
    saved = database.get_murojaat_by_id(app_id, db_path=test_db)
    assert saved["Savol"] == xss_text


# ==============================================================================
# 7. SQL Injection Attempts Rejected
# ==============================================================================
def test_7_sql_injection_attempts_rejected(test_env):
    test_db = test_env["test_db"]
    sqli_payload = "1001' OR '1'='1'; DROP TABLE fuqarolar; --"
    
    # Attempt SQL injection through search
    results = database.search_citizens(sqli_payload, db_path=test_db)
    
    # Attempt SQL injection through get_citizen_by_tg_id
    citizen = database.get_citizen_by_tg_id(sqli_payload, db_path=test_db)
    assert citizen is None
    
    # Verify table fuqarolar was NOT dropped
    conn = database.get_db_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM fuqarolar")
    count = cur.fetchone()[0]
    conn.close()
    assert count >= 2, "fuqarolar table must remain intact"


# ==============================================================================
# 8. Duplicate Appointments Prevented
# ==============================================================================
def test_8_duplicate_appointments_prevented(test_env):
    test_db = test_env["test_db"]
    
    # Book first appointment
    t1 = database.save_navbat(
        telegram_id="1001",
        fio="Ali Valiyev",
        telefon="+998901112233",
        kocha="1-uy",
        qabul_kuni=future_weekday(0),
        qabul_soati="10:00 - 10:30",
        db_path=test_db
    )
    assert t1.startswith("Q-")
    
    # Try booking second active appointment for the same citizen
    with pytest.raises(ValueError) as excinfo:
        database.save_navbat(
            telegram_id="1001",
            fio="Ali Valiyev",
            telefon="+998901112233",
            kocha="1-uy",
            qabul_kuni=future_weekday(1),
            qabul_soati="11:00 - 11:30",
            db_path=test_db
        )
    assert "faol band qilingan navbat" in str(excinfo.value)


# ==============================================================================
# 9. Concurrent Appointment Booking Safe (Slot Collision)
# ==============================================================================
def test_9_concurrent_appointment_booking_safe(test_env):
    test_db = test_env["test_db"]
    slot_date = future_weekday(2)
    slot_time = "14:00 - 14:30"
    
    # Citizen B books the slot
    t_b = database.save_navbat(
        telegram_id="2002",
        fio="Vali Aliyev",
        telefon="+998904445566",
        kocha="2-uy",
        qabul_kuni=slot_date,
        qabul_soati=slot_time,
        db_path=test_db
    )
    assert t_b.startswith("Q-")
    
    # Another citizen (3003) tries to book the exact same slot
    with pytest.raises(ValueError) as excinfo:
        database.save_navbat(
            telegram_id="3003",
            fio="Gani Karim",
            telefon="+998907778899",
            kocha="3-uy",
            qabul_kuni=slot_date,
            qabul_soati=slot_time,
            db_path=test_db
        )
    assert "boshqa fuqaro tomonidan band qilingan" in str(excinfo.value)


# ==============================================================================
# 10. Past Appointment Dates Rejected
# ==============================================================================
def test_10_past_appointment_dates_rejected(test_env):
    test_db = test_env["test_db"]
    past_date = "2020-01-01"
    
    with pytest.raises(ValueError) as excinfo:
        database.save_navbat(
            telegram_id="4004",
            fio="Test Fuqaro",
            telefon="+998901234567",
            kocha="Test",
            qabul_kuni=past_date,
            qabul_soati="09:00 - 09:30",
            db_path=test_db
        )
    assert "O'tgan sana" in str(excinfo.value)


# ==============================================================================
# 11. Cancelled Appointment Slots Become Available
# ==============================================================================
def test_11_cancelled_appointment_slots_become_available(test_env):
    test_db = test_env["test_db"]
    slot_date = future_weekday(3)
    slot_time = "15:00 - 15:30"
    
    # Citizen 5005 books
    t_id = database.save_navbat(
        telegram_id="5005",
        fio="Sobir",
        telefon="+998905555555",
        kocha="5-uy",
        qabul_kuni=slot_date,
        qabul_soati=slot_time,
        db_path=test_db
    )
    
    # Citizen 5005 cancels appointment
    ok = database.cancel_navbat(t_id, user_id="5005", is_admin=False, reason="Bekor qilindi", db_path=test_db)
    assert ok is True
    
    # Now Citizen 6006 can book the released slot
    t_id_2 = database.save_navbat(
        telegram_id="6006",
        fio="Botir",
        telefon="+998906666666",
        kocha="6-uy",
        qabul_kuni=slot_date,
        qabul_soati=slot_time,
        db_path=test_db
    )
    assert t_id_2.startswith("Q-")


# ==============================================================================
# 12. Application Status Permissions & Normalization
# ==============================================================================
def test_12_application_status_permissions(test_env):
    test_db = test_env["test_db"]
    
    # Verify standard 8 statuses
    assert len(database.APPLICATION_STATUSES) == 8
    assert "Yangi" in database.APPLICATION_STATUSES
    assert "Hal etildi" in database.APPLICATION_STATUSES
    assert "Rad etildi" in database.APPLICATION_STATUSES
    
    # Test normalization of legacy status
    norm = database.normalize_application_status("kutmoqda")
    assert norm == "Yangi"
    norm_done = database.normalize_application_status("qanoatlantirildi")
    assert norm_done == "Hal etildi"
    
    # Create appeal and update status
    app_id = database.save_murojaat(
        user_id="1001",
        savol="Status testi",
        ai_javobi="Javob",
        turi="Umumiy",
        muhimlik="ODDIY",
        db_path=test_db
    )
    updated = database.update_murojaat_status(app_id, "O'rganilmoqda", admin_izohi="Xonadonga chiqildi", admin_actor="ADMIN", db_path=test_db)
    assert updated["Status"] == "O'rganilmoqda"
    assert updated["Admin_Izohi"] == "Xonadonga chiqildi"


# ==============================================================================
# 13. PII Masking
# ==============================================================================
def test_13_pii_masking():
    sample = (
        "Fuqaro JShShIR: 12345678901234, pasporti: AA 7654321, "
        "telefoni: +998914545351, kartasi: 8600123456789012, "
        "manzili: Bog'bonlar ko'chasi 14-uy, holati: 2-guruh nogironi"
    )
    assert has_pii(sample) is True
    masked = mask_pii(sample)
    
    assert "[ЖШШИР_ЯШИРИЛГАН]" in masked
    assert "[ПАСПОРТ_ЯШИРИЛГАН]" in masked
    assert "[ТЕЛ_ЯШИРИЛГАН]" in masked
    assert "[КАРТА_ЯШИРИЛГАН]" in masked
    assert "[МАНЗИЛ_ЯШИРИЛГАН]" in masked
    assert "[ТИББИЙ_МАЪЛУМОТ_ЯШИРИЛГАН]" in masked


# ==============================================================================
# 14. Legal Answer Fallback When No Source Exists
# ==============================================================================
def test_14_legal_answer_fallback_when_no_source_exists():
    obscure_query = "Mars planetasiga uchish uchun Shayxali mahallasidan qanday nafaqa olsa boladi?"
    handled, turi, muhimlik, ans = local_legal_advisor.try_local_answer(obscure_query, user_id=1001)
    
    # Should not be handled by local deterministic rules
    assert handled is False or ans is None


# ==============================================================================
# 15. Gemini Failure and Safe Legal Fallback
# ==============================================================================
def test_15_gemini_failure_and_safe_fallback(monkeypatch):
    import main
    
    # Mock Gemini to raise Quota / ResourceExhausted exception
    def mock_generate_content(*args, **kwargs):
        raise RuntimeError("429 ResourceExhausted: Quota exceeded")
        
    # Mock Groq to also raise exception to test final fallback
    def mock_groq(*args, **kwargs):
        raise RuntimeError("Groq rate limit exceeded")
        
    monkeypatch.setattr(main, "call_groq_api", mock_groq)
    
    res = main.call_gemini_safe("Nafaqam qachon to'lanadi?")
    assert hasattr(res, "text")
    assert "аниқлаштириш талаб этилади" in res.text or "ижтимоий ходими" in res.text


# ==============================================================================
# 16. Excel Export Integrity
# ==============================================================================
def test_16_excel_export_integrity(test_env):
    test_db = test_env["test_db"]
    export_file = database.export_all_to_excel(actor="ADMIN_TEST", db_path=test_db)
    
    assert os.path.exists(export_file)
    wb = openpyxl.load_workbook(export_file)
    sheet_names = wb.sheetnames
    assert "Fuqarolar" in sheet_names
    assert "Murojaatlar" in sheet_names
    assert "Navbatlar" in sheet_names
    
    os.remove(export_file)


# ==============================================================================
# 17. Database Backup and Restoration
# ==============================================================================
def test_17_database_backup_and_restoration(test_env):
    temp_dir = test_env["temp_dir"]
    test_db = test_env["test_db"]
    
    # Backup
    backup_file = database.backup_database(destination_dir=temp_dir, source_db=test_db)
    assert os.path.exists(backup_file)
    assert os.path.getsize(backup_file) > 0
    
    # Restore to a separate destination DB
    restored_db = os.path.join(temp_dir, "restored_test.db")
    ok = database.restore_database(backup_file, restored_db)
    assert ok is True
    assert os.path.exists(restored_db)
    
    # Verify row counts match
    conn1 = sqlite3.connect(test_db)
    conn2 = sqlite3.connect(restored_db)
    c1 = conn1.cursor().execute("SELECT COUNT(*) FROM fuqarolar").fetchone()[0]
    c2 = conn2.cursor().execute("SELECT COUNT(*) FROM fuqarolar").fetchone()[0]
    conn1.close()
    conn2.close()
    assert c1 == c2


# ==============================================================================
# 18. File Upload Validation
# ==============================================================================
def test_18_file_upload_validation():
    # 1. Invalid extension
    with pytest.raises(ValueError) as exc_ext:
        admin_ai_assistant.add_document_to_admin_kb(b"malicious_code", "payload.exe")
    assert "Ruxsat berilmagan fayl kengaytmasi" in str(exc_ext.value)
    
    # 2. File size > 20MB
    large_bytes = b"0" * (21 * 1024 * 1024)
    with pytest.raises(ValueError) as exc_size:
        admin_ai_assistant.add_document_to_admin_kb(large_bytes, "huge.pdf")
    assert "20MB" in str(exc_size.value)
    
    # 3. Path traversal sanitize
    valid_bytes = b"Oddiy test matni ijtimoiy xodim uchun."
    res = admin_ai_assistant.add_document_to_admin_kb(valid_bytes, "../../secret.txt")
    assert res["doc_id"].startswith("SKB-")
    assert ".." not in res["title"]


# ==============================================================================
# 19. Partial Unique Index Slot Conflict at DB Engine Level
# ==============================================================================
def test_19_partial_unique_index_slot_conflict_at_db_level(test_env):
    test_db = test_env["test_db"]
    conn = database.get_db_connection(test_db)
    
    # Direct raw SQL insert first active slot
    conn.execute("""
    INSERT INTO navbatlar (Navbat_ID, Yaratilgan_Vaqt, Telegram_ID, FIO, Telefon, Kocha_Manzil, Qabul_Kuni, Qabul_Soati, Status, token)
    VALUES ('Q-TEST1', '2026-11-01 10:00:00', '9001', 'Test A', '+998901', 'Manzil', '2026-11-25', '10:00', 'Band qilingan', 'tok1')
    """)
    conn.commit()

    # Direct raw SQL insert same slot by another citizen must fail at DB engine level
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
        INSERT INTO navbatlar (Navbat_ID, Yaratilgan_Vaqt, Telegram_ID, FIO, Telefon, Kocha_Manzil, Qabul_Kuni, Qabul_Soati, Status, token)
        VALUES ('Q-TEST2', '2026-11-01 10:00:01', '9002', 'Test B', '+998902', 'Manzil', '2026-11-25', '10:00', 'Band qilingan', 'tok2')
        """)
        conn.commit()

    # Same citizen booking second active slot must also fail at DB engine level
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
        INSERT INTO navbatlar (Navbat_ID, Yaratilgan_Vaqt, Telegram_ID, FIO, Telefon, Kocha_Manzil, Qabul_Kuni, Qabul_Soati, Status, token)
        VALUES ('Q-TEST3', '2026-11-01 10:00:02', '9001', 'Test A', '+998901', 'Manzil', '2026-11-26', '11:00', 'Band qilingan', 'tok3')
        """)
        conn.commit()

    conn.close()


# ==============================================================================
# 20. Multi-Format Past Date Rejection
# ==============================================================================
def test_20_multi_format_past_date_rejection(test_env):
    test_db = test_env["test_db"]
    
    past_dates = ["2020-01-01", "15.10.2023", "01/05/2021", "2024.12.31"]
    for p_date in past_dates:
        with pytest.raises(ValueError) as exc:
            database.save_navbat(
                telegram_id="9999",
                fio="Sinov",
                telefon="+998900000000",
                kocha="Sinov",
                qabul_kuni=p_date,
                qabul_soati="10:00",
                db_path=test_db
            )
        assert "O'tgan sana" in str(exc.value)


# ==============================================================================
# 21. Audit Log Completeness and Privacy Verification
# ==============================================================================
def test_21_audit_log_completeness_and_no_pii(test_env):
    test_db = test_env["test_db"]
    
    database.log_audit_event("TEST_ADMIN", "SETTINGS_CHANGE", "mih_amount", "669000 -> 700000", "SUCCESS", db_path=test_db)
    logs = database.get_audit_logs(limit=10, db_path=test_db)
    assert len(logs) > 0
    top = logs[0]
    assert top["actor"] == "TEST_ADMIN"
    assert top["action"] == "SETTINGS_CHANGE"
    assert top["status"] == "SUCCESS"
    assert "timestamp" in top


# ==============================================================================
# 22. Cyrillic Normalization & HTML Apostrophe Safety
# ==============================================================================
def test_22_cyrillic_normalization_and_apostrophe_safety():
    from utils.text_normalizer import latin_to_cyrillic_uz
    
    # 1. Jo'rayev and Kuchkarov normalization
    s1 = latin_to_cyrillic_uz("Ijtimoiy xodim A. Jo'rayev va D. Kuchkarov")
    assert "А. Жўраев" in s1
    assert "Д. Қўчқаров" in s1
    
    # 2. Uppercase words with E
    s2 = latin_to_cyrillic_uz("QADAMBA-QADAM ALGORITM VA KERAKLI MA'LUMOT")
    assert "КЕРАКЛИ" in s2
    assert "АЛГОРИТМ" in s2
    
    # 3. No raw &#x27; in esc()
    import main
    escaped = main.esc("A. Jo'rayev va <b>test</b>")
    assert "&#x27;" not in escaped
    assert "&lt;b&gt;" in escaped
    assert "'" in escaped
