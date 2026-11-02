# -*- coding: utf-8 -*-
"""Tahlilda topilgan nosozliklar qayta paydo bo'lmasligi uchun regressiya testlari."""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from conftest import future_weekday, next_weekend_day
import database
import main
import webapp_server
from knowledge_base import CYR_TO_LAT_MAP, load_knowledge_index
from utils.text_normalizer import latin_to_cyrillic_uz
from utils.tma_auth import verify_telegram_init_data

ADMIN_UID = 7840350353


@pytest.fixture()
def client():
    webapp_server.app.config["TESTING"] = True
    webapp_server._rate_limits.clear()
    return webapp_server.app.test_client()


def _unique_uid():
    return str(int(datetime.now().timestamp() * 1000000))


def _callback(data, uid=ADMIN_UID):
    return SimpleNamespace(
        id="cb",
        data=data,
        from_user=SimpleNamespace(id=uid),
        message=SimpleNamespace(chat=SimpleNamespace(id=uid), message_id=1, text="Fuqaro <test>"),
    )


# ------------------------------------------------------------------ BAZA
def test_duplicate_question_within_a_minute_returns_same_id():
    uid = _unique_uid()
    first = database.save_murojaat(uid, "Bir xil savol", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    second = database.save_murojaat(uid, "Bir xil savol", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    assert first == second


def test_same_question_after_a_minute_creates_new_appeal():
    uid = _unique_uid()
    first = database.save_murojaat(uid, "Takroriy savol", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    old = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    with database.get_db_connection() as conn:
        conn.execute("UPDATE murojaatlar SET Sana = ? WHERE Murojaat_ID = ?", (old, first))
    assert database.save_murojaat(uid, "Takroriy savol", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi") != first


def test_appeal_ids_do_not_collide_after_gap():
    uid = _unique_uid()
    first = database.save_murojaat(uid, "Birinchi", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM murojaatlar WHERE Murojaat_ID = (SELECT MIN(Murojaat_ID) FROM murojaatlar)")
    second = database.save_murojaat(uid, "Ikkinchi", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    assert first != second


def test_auto_answered_question_stays_out_of_review_queue():
    uid = _unique_uid()
    m_id = database.save_murojaat(uid, "Umumiy savol", "javob", "QONUNIY_MASLAHAT", "ODDIY", "AI orqali javob berildi")
    assert database.get_murojaat_by_id(m_id)["Status"] == "AI orqali javob berildi"
    assert m_id not in [a["Murojaat_ID"] for a in database.get_pending_appeals(limit=1000)]
    assert database.normalize_application_status("Mahalliy baza orqali javob berildi") == "Mahalliy baza orqali javob berildi"
    assert len(database.APPLICATION_STATUSES) == 8


def test_overdue_query_finds_only_old_open_appeals():
    uid = _unique_uid()
    m_id = database.save_murojaat(uid, "Eski murojaat", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    fresh = database.save_murojaat(uid, "Yangi murojaat", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    old = (datetime.now() - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
    with database.get_db_connection() as conn:
        conn.execute("UPDATE murojaatlar SET Sana = ? WHERE Murojaat_ID = ?", (old, m_id))
    ids = [a["Murojaat_ID"] for a in database.get_overdue_appeals(hours=24)]
    assert m_id in ids and fresh not in ids


def test_weekend_and_unknown_slot_are_rejected():
    with pytest.raises(ValueError, match="Shanba"):
        database.save_navbat(_unique_uid(), "F", "T", "K", next_weekend_day(), "10:00")
    with pytest.raises(ValueError, match="qabul vaqti"):
        database.save_navbat(_unique_uid(), "F", "T", "K", future_weekday(4), "23:59")
    far = (datetime.now() + timedelta(days=database.QUEUE_MAX_DAYS_AHEAD + 5))
    while far.weekday() >= 5:
        far += timedelta(days=1)
    with pytest.raises(ValueError, match="oldindan"):
        database.save_navbat(_unique_uid(), "F", "T", "K", far.strftime("%Y-%m-%d"), "10:00")


def test_same_slot_in_different_formats_cannot_be_double_booked():
    day_iso = future_weekday(5)
    day_dotted = datetime.strptime(day_iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    database.save_navbat(_unique_uid(), "A", "T", "K", day_iso, "09:00")
    with pytest.raises(ValueError, match="band qilingan"):
        database.save_navbat(_unique_uid() + "1", "B", "T", "K", day_dotted, "09:00 - 10:00")
    assert "09:00" in database.get_booked_slots(day_dotted)


def test_legacy_rows_are_migrated_conservatively(tmp_path):
    db = str(tmp_path / "legacy.db")
    database.init_database(db)
    conn = sqlite3.connect(db)
    insert = (
        "INSERT INTO murojaatlar (Murojaat_ID, Sana, Oy_Yil, Telegram_ID, Savol, AI_Javobi, Turi, Muhimlik, Status, Admin_Izohi)"
        " VALUES (?, '2026-01-01 10:00:00', '01-2026', '1', 'q', ?, ?, ?, 'Yangi', ?)"
    )
    conn.execute(insert, ("M-1", "javob", "QONUNIY_MASLAHAT", "ODDIY", ""))
    conn.execute(insert, ("M-2", "", "QONUNIY_MASLAHAT", "ODDIY", ""))
    conn.execute(insert, ("M-3", "javob", "QONUNIY_MASLAHAT", "SHOSHILINCH", ""))
    conn.execute(insert, ("M-4", "javob", "Boshqa masala", "ODDIY", "Mini App orqali yuborildi"))
    # Eski baza holati: migratsiya hali bajarilmagan
    conn.execute("DELETE FROM system_settings WHERE key = 'legacy_rows_migrated'")
    conn.commit()
    conn.close()

    database.init_database(db)

    conn = sqlite3.connect(db)
    rows = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT Murojaat_ID, Status, Admin_Izohi FROM murojaatlar")}
    conn.close()
    assert rows["M-1"][0] == "AI orqali javob berildi"
    assert rows["M-2"][0] == "Yangi"
    assert rows["M-3"][0] == "Yangi"
    assert rows["M-4"] == ("Yangi", "")


def test_old_backups_are_pruned(tmp_path):
    for i in range(5):
        (tmp_path / f"ihma_database_backup_2026010{i}.db").write_text("x")
    assert database.prune_old_backups(str(tmp_path), keep=2) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "ihma_database_backup_20260103.db", "ihma_database_backup_20260104.db",
    ]


def test_excel_export_neutralizes_formulas_and_is_removed_after_send():
    uid = _unique_uid()
    database.save_murojaat(uid, '=HYPERLINK("http://x")', "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    sent = {}

    def _capture(chat_id, f_obj, **kwargs):
        import openpyxl
        sheet = openpyxl.load_workbook(f_obj.name)["Murojaatlar"]
        sent["values"] = [c.value for row in sheet.iter_rows() for c in row]
        sent["path"] = f_obj.name

    with patch.object(main.bot, "send_document", side_effect=_capture):
        main.send_full_excel_report(ADMIN_UID)
    assert "'=HYPERLINK(\"http://x\")" in sent["values"]
    assert not os.path.exists(sent["path"])


# ------------------------------------------------------------------ BOT
def test_admin_can_approve_citizen_with_button():
    uid = _unique_uid()
    database.save_or_update_citizen(uid, "Sinov Fuqaro", "+998901230000", status="Kutmoqda")
    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "edit_message_text") as edit, \
            patch.object(main.bot, "send_message"):
        main.handle_admin_panel_callbacks(_callback(f"adm_appr_cit_{uid}"))
    assert database.get_citizen_by_tg_id(uid)["Status"] == "Tasdiqlangan"
    assert "&lt;test&gt;" in edit.call_args[0][0]


def test_admin_stats_button_reads_database():
    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "send_message") as send:
        main.handle_admin_panel_callbacks(_callback("adm_stats"))
    assert "СТАТИСТИКАСИ" in send.call_args[0][1]


def test_citizen_status_button_works():
    uid = int(_unique_uid()[-9:])
    database.save_or_update_citizen(uid, "Holat Fuqaro", "+998931112299", status="Tasdiqlangan")
    m_id = database.save_murojaat(uid, "Holat savoli", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    message = SimpleNamespace(
        text="🔍 Мурожаатим ҳолати",
        content_type="text",
        from_user=SimpleNamespace(id=uid, first_name="A", last_name="", username=""),
        chat=SimpleNamespace(id=uid),
        message_id=1,
    )
    with patch.object(main.bot, "send_message") as send, patch.object(main, "send_split_message") as split:
        main.handle_user_questions(message)
    assert not send.called
    assert m_id in split.call_args.kwargs["text"]


def test_voice_message_reaches_question_pipeline():
    uid = int(_unique_uid()[-9:])
    message = SimpleNamespace(
        content_type="voice",
        voice=SimpleNamespace(file_id="f"),
        from_user=SimpleNamespace(id=uid, first_name="A", last_name="", username=""),
        chat=SimpleNamespace(id=uid),
        message_id=1,
    )
    # autospec: mavjud bo'lmagan argument berilsa TypeError ko'taradi (eski xato aynan shu edi)
    with patch.object(main, "transcribe_audio_bytes", autospec=True, return_value="salom") as transcribe, \
            patch.object(main, "process_and_dispatch_question") as dispatch, \
            patch.object(main.bot, "send_chat_action"), \
            patch.object(main.bot, "reply_to", return_value=SimpleNamespace(message_id=2)), \
            patch.object(main.bot, "get_file", return_value=SimpleNamespace(file_path="p")), \
            patch.object(main.bot, "download_file", return_value=b"ogg"):
        main.handle_voice_message(message)
    assert transcribe.called
    assert "[ОВОЗЛИ ХАБАР]" in dispatch.call_args.kwargs["original_question"]


def test_bot_slot_booking_goes_to_database():
    uid = int(_unique_uid()[-9:])
    day_iso = future_weekday(6)
    day_dotted = datetime.strptime(day_iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    call = _callback(f"qslot_{day_dotted}_10:00 - 11:00", uid=uid)
    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "edit_message_text"), \
            patch.object(main.bot, "send_message"):
        main.handle_queue_slot_select(call)
    ticket = database.get_citizen_active_navbat(uid)
    assert ticket["Qabul_Kuni"] == day_iso
    assert ticket["Qabul_Soati"] == "10:00"


def test_csat_rejects_other_citizens_appeal_and_bad_score():
    owner = _unique_uid()
    m_id = database.save_murojaat(owner, "Baho savoli", "", "SHAXSIY_MUROJAAT", "ODDIY", "Hal etildi")
    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "edit_message_text"):
        main.handle_csat_callback(_callback(f"csat_{m_id}_5", uid=999))
        main.handle_csat_callback(_callback(f"csat_{m_id}_99", uid=int(owner)))
    assert database.get_murojaat_by_id(m_id).get("Baho") in (None, "")


def test_ai_outage_puts_question_into_review_queue():
    with patch.object(main, "call_ai_strict", side_effect=RuntimeError("down")), \
            patch.object(main, "search_knowledge_base", return_value=[]):
        raw = main.generate_grounded_ai_output("Murakkab savol", "uz_cyr")
    turi, _, _ = main.parse_ai_output(raw, "Murakkab savol")
    assert turi == "SHAXSIY_MUROJAAT"


def test_russian_question_reaches_ai_untransliterated():
    captured = {}

    def _fake(prompt):
        captured["prompt"] = prompt
        return main.SafeAIResponse("[TURI: QONUNIY_MASLAHAT]\n[MUHIMLIK: ODDIY]\n---\nОтвет")

    with patch.object(main, "call_ai_strict", side_effect=_fake), patch.object(main, "search_knowledge_base", return_value=[]):
        main.generate_grounded_ai_output("Какие документы нужны?", "ru")
    assert "Какие документы нужны" in captured["prompt"]


def _doc_message(uid=ADMIN_UID, file_name="qaror.pdf"):
    return SimpleNamespace(
        content_type="document",
        text=None,
        caption=None,
        document=SimpleNamespace(file_id="file-1", file_name=file_name),
        from_user=SimpleNamespace(id=uid),
        chat=SimpleNamespace(id=uid),
        message_id=1,
    )


def test_unexpected_admin_document_needs_confirmation():
    main.admin_state.pop(ADMIN_UID, None)
    with patch.object(main.bot, "reply_to") as reply, patch.object(main, "_ingest_legal_document") as ingest:
        main.handle_admin_document_upload(_doc_message())
    assert not ingest.called
    assert reply.call_args.kwargs["reply_markup"] is not None

    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "edit_message_text"), \
            patch.object(main, "_ingest_legal_document") as ingest:
        main.handle_kb_document_confirmation(_callback("kbdoc_no"))
        assert not ingest.called
        # Bekor qilingan hujjatni keyin tasdiqlab bo'lmaydi
        main.handle_kb_document_confirmation(_callback("kbdoc_yes"))
        assert not ingest.called


def test_confirmed_or_requested_admin_document_is_ingested():
    main.admin_state.pop(ADMIN_UID, None)
    with patch.object(main.bot, "reply_to"), patch.object(main, "_ingest_legal_document"):
        main.handle_admin_document_upload(_doc_message())
    with patch.object(main.bot, "answer_callback_query"), patch.object(main.bot, "edit_message_text"), \
            patch.object(main, "_ingest_legal_document") as ingest:
        main.handle_kb_document_confirmation(_callback("kbdoc_yes"))
    assert ingest.call_args[0][3:] == ("file-1", "qaror.pdf")

    main.admin_state[ADMIN_UID] = {"waiting_for": "legal_document"}
    with patch.object(main.bot, "reply_to", return_value=SimpleNamespace(message_id=9)), \
            patch.object(main, "_ingest_legal_document") as ingest:
        main.handle_admin_document_upload(_doc_message())
    assert ingest.called
    main.admin_state.pop(ADMIN_UID, None)


def test_other_citizen_cannot_confirm_document():
    main.admin_state[ADMIN_UID] = {"pending_kb_doc": {"file_id": "f", "file_name": "n"}}
    with patch.object(main.bot, "answer_callback_query"), patch.object(main, "_ingest_legal_document") as ingest:
        main.handle_kb_document_confirmation(_callback("kbdoc_yes", uid=999))
    assert not ingest.called
    main.admin_state.pop(ADMIN_UID, None)


def test_admin_reply_keeps_appeal_open_and_escapes_text():
    uid = int(_unique_uid()[-9:])
    m_id = database.save_murojaat(uid, "Javob kutilmoqda", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    main.admin_state[ADMIN_UID] = {"reply_murojaat_id": m_id}
    msg = SimpleNamespace(text="Pasport nusxasi kerak <b>", from_user=SimpleNamespace(id=ADMIN_UID), chat=SimpleNamespace(id=ADMIN_UID))
    with patch.object(main, "send_split_message") as split, patch.object(main.bot, "send_message") as send:
        main.process_admin_direct_reply(msg)
    row = database.get_murojaat_by_id(m_id)
    assert row["Status"] == "O'rganilmoqda"
    assert row["Admin_Izohi"] == "Pasport nusxasi kerak <b>"
    assert "&lt;b&gt;" in split.call_args.kwargs["text"]
    assert send.call_args.kwargs["reply_markup"] is not None
    assert m_id in [a["Murojaat_ID"] for a in database.get_pending_appeals(limit=1000)]


def test_admin_reply_does_not_reopen_closed_appeal():
    uid = int(_unique_uid()[-9:])
    m_id = database.save_murojaat(uid, "Yopilgan savol", "", "SHAXSIY_MUROJAAT", "ODDIY", "Rad etildi")
    main.admin_state[ADMIN_UID] = {"reply_murojaat_id": m_id}
    msg = SimpleNamespace(text="Qo'shimcha izoh", from_user=SimpleNamespace(id=ADMIN_UID), chat=SimpleNamespace(id=ADMIN_UID))
    with patch.object(main, "send_split_message"), patch.object(main.bot, "send_message"):
        main.process_admin_direct_reply(msg)
    assert database.get_murojaat_by_id(m_id)["Status"] == "Rad etildi"


def test_everyday_words_are_not_flagged_as_violence():
    import local_legal_advisor
    handled, _, muhimlik, _ = local_legal_advisor.try_local_answer("Ro'yxatda turish uchun nima kerak", 1)
    assert not (handled and muhimlik == "SHOSHILINCH")
    handled, turi, muhimlik, _ = local_legal_advisor.try_local_answer("Eri meni urdi", 1)
    assert handled and turi == "SHAXSIY_MUROJAAT" and muhimlik == "SHOSHILINCH"


# ------------------------------------------------------------------ MATN VA AUTENTIFIKATSIYA
def test_conversion_keeps_entities_ids_and_code():
    out = latin_to_cyrillic_uz("Salom &lt;b&gt; <code>/xisobot 10-2026</code> M-1001 my.gov.uz")
    assert "&lt;" in out and "&gt;" in out
    assert "<code>/xisobot 10-2026</code>" in out
    assert "M-1001" in out and "my.gov.uz" in out
    assert "Салом" in out


def test_non_ascii_hash_does_not_crash_auth():
    ok, _, _ = verify_telegram_init_data("auth_date=1&hash=ҳэш&user=%7B%7D", "123:x")
    assert ok is False


def test_knowledge_map_and_index_cache():
    assert CYR_TO_LAT_MAP["к"] == "k" and CYR_TO_LAT_MAP["н"] == "n" and CYR_TO_LAT_MAP["о"] == "o"
    assert load_knowledge_index() is load_knowledge_index()


# ------------------------------------------------------------------ MINI APP API
def _h(uid):
    return {"X-Test-User-Id": str(uid), "Content-Type": "application/json"}


def test_appeal_endpoint_notifies_admin_and_has_no_fake_admin_reply(client):
    uid = _unique_uid()
    bot = MagicMock()
    webapp_server.set_bot_instance(bot)
    try:
        res = client.post("/api/appeal", headers=_h(uid), json={
            "category": "<b>x</b>", "text": "Yordam kerak <script>", "priority": "<i>YOLG'ON</i>",
        })
    finally:
        webapp_server.set_bot_instance(None)
    assert res.status_code == 200
    assert res.get_json()["appeal"]["priority"] == "ODDIY"
    alert = bot.send_message.call_args[0][1]
    assert "<script>" not in alert and "<i>YOLG" not in alert
    appeal = client.get("/api/citizen", headers=_h(uid)).get_json()["appeals"][0]
    assert appeal["admin_response"] == ""


def test_verify_validates_input_and_duplicates(client):
    existing = _unique_uid()
    database.save_or_update_citizen(existing, "Mavjud Fuqaro", "+998900000123", status="Tasdiqlangan")
    uid = _unique_uid()
    good = {"fio": "Ali Valiyev", "phone": "+998 93 777 11 22", "address": "Navoiy 1"}

    assert client.post("/api/verify", headers=_h(uid), json={**good, "phone": "abc"}).status_code == 400
    assert client.post("/api/verify", headers=_h(uid), json={**good, "fio": "A"}).status_code == 400
    assert client.post("/api/verify", headers=_h(uid), json={**good, "passport_or_jshshir": "123"}).status_code == 400
    assert client.post("/api/verify", headers=_h(uid), json={**good, "phone": "+998900000123"}).status_code == 409
    assert client.post("/api/verify", headers=_h(uid), json=good).status_code == 200

    # Tasdiqlangan fuqaro maqomi "Kutmoqda" ga tushib ketmaydi
    res = client.post("/api/verify", headers=_h(existing), json={**good, "phone": "+998900000123"})
    assert res.get_json()["already_verified"] is True
    assert database.get_citizen_by_tg_id(existing)["Status"] == "Tasdiqlangan"


def test_bad_input_returns_4xx_not_500(client):
    uid = _unique_uid()
    m_id = database.save_murojaat(uid, "Baho", "", "SHAXSIY_MUROJAAT", "ODDIY", "Yangi")
    assert client.post("/api/rate", headers=_h(uid), json={"appeal_id": m_id, "score": "abc"}).status_code == 400
    assert client.post("/api/rate", headers=_h(uid), json={"appeal_id": m_id, "score": 99}).status_code == 400
    assert client.post("/api/rate", headers=_h(uid), json={"appeal_id": m_id, "score": 5}).status_code == 400  # hali ochiq
    assert client.post("/api/appeal", headers=_h(uid), data="[1,2]").status_code == 400
    assert client.get("/api/admin/audit_logs?limit=abc", headers=_h(ADMIN_UID)).status_code == 200


def test_rating_only_once_after_resolution(client):
    uid = _unique_uid()
    m_id = database.save_murojaat(uid, "Baho 2", "", "SHAXSIY_MUROJAAT", "ODDIY", "Hal etildi")
    assert client.post("/api/rate", headers=_h(uid), json={"appeal_id": m_id, "score": 4}).status_code == 200
    assert client.post("/api/rate", headers=_h(uid), json={"appeal_id": m_id, "score": 1}).status_code == 409


def test_test_auth_bypass_needs_flask_testing_flag(client, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    webapp_server.app.config["TESTING"] = False
    try:
        assert client.get("/api/citizen", headers=_h(1)).status_code == 401
    finally:
        webapp_server.app.config["TESTING"] = True


def test_init_data_in_url_is_not_accepted(client):
    assert client.get("/api/citizen?initData=abc").status_code == 401
    assert "initData" not in (client.get("/api/citizen?initData=abc").get_json().get("citizen") or {})


def test_spoofed_forwarded_header_does_not_bypass_rate_limit(client):
    webapp_server.app.config["TESTING"] = True
    environ = {"REMOTE_ADDR": "203.0.113.9"}
    codes = [
        client.get("/api/settings", headers={"X-Forwarded-For": f"10.0.0.{i}", "CF-Connecting-IP": f"10.1.0.{i}"},
                   environ_overrides=environ).status_code
        for i in range(101)
    ]
    assert codes[-1] == 429


def test_cors_rejects_unknown_tunnel_origin_and_headers_are_valid(client):
    res = client.get("/api/settings", headers={"Origin": "https://evil.trycloudflare.com"})
    assert "Access-Control-Allow-Origin" not in res.headers
    assert "X-Frame-Options" not in res.headers
    assert "unsafe-eval" not in res.headers["Content-Security-Policy"]
    assert "X-Test-User-Id" not in res.headers["Access-Control-Allow-Headers"]
    ok = client.get("/api/settings", headers={"Origin": "https://web.telegram.org"})
    assert ok.headers["Access-Control-Allow-Origin"] == "https://web.telegram.org"


def test_queue_slots_endpoint_reports_booked_without_pii(client):
    day = future_weekday(7)
    database.save_navbat(_unique_uid(), "Maxfiy Ism", "+998", "K", day, "11:00")
    res = client.get(f"/api/queue/slots?date={day}", headers=_h(_unique_uid()))
    assert res.status_code == 200
    body = res.get_json()
    assert "11:00" in body["booked"] and "17:00" not in body["slots"]
    assert "Maxfiy" not in json.dumps(body)
    assert client.get("/api/queue/slots?date=nope", headers=_h(1)).status_code == 400


def test_ticket_qr_encodes_token_and_verify_page_has_no_pii(client):
    uid = _unique_uid()
    assert client.get("/api/queue/qr", headers=_h(uid)).status_code == 404

    database.save_navbat(uid, "Maxfiy Ism", "+998931110000", "Maxfiy manzil", future_weekday(8), "15:00")
    res = client.get("/api/queue/qr", headers=_h(uid))
    assert res.status_code == 200 and res.mimetype == "image/svg+xml"
    assert b"<svg" in res.data
    assert client.get("/api/queue/qr").status_code == 401

    token = database.get_citizen_active_navbat(uid)["token"]
    page = client.get(f"/api/queue/verify_qr?token={token}", headers={"Accept": "text/html"})
    text = page.get_data(as_text=True)
    assert page.mimetype == "text/html" and "фаол" in text and "15:00" in text
    assert "Maxfiy" not in text and "+998" not in text

    bad = client.get("/api/queue/verify_qr?token=<script>", headers={"Accept": "text/html"}).get_data(as_text=True)
    assert "топилмади" in bad and "<script>" not in bad
    assert client.get(f"/api/queue/verify_qr?token={token}").get_json()["verification"]["is_active"] is True


def test_ai_chat_uses_injected_backend_and_has_per_user_limit(client):
    backend = MagicMock(return_value={"answer": "<b>Javob</b>", "source": "ai"})
    webapp_server.set_ai_backend(backend)
    uid = _unique_uid()
    try:
        first = client.post("/api/ai_chat", headers=_h(uid), json={"message": "Savol"})
        codes = [client.post("/api/ai_chat", headers=_h(uid), json={"message": "Savol"}).status_code for _ in range(10)]
    finally:
        webapp_server.set_ai_backend(None)
    assert first.get_json()["reply"] == "<b>Javob</b>"
    assert codes[-1] == 429


def test_web_layer_does_not_import_main():
    source = open(webapp_server.__file__, encoding="utf-8").read()
    assert "import main" not in source
