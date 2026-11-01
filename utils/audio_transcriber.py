# -*- coding: utf-8 -*-
"""
Ovozli xabarlar (Voice / Audio) transkripsiya moduli.
Telegramdan kelgan .ogg/.mp3 ovozli xabarlarni Groq Whisper va Gemini API
orqali yuqori aniqlikda o'zbekcha matnga aylantiradi.
"""

import os
import requests
import google.generativeai as genai

def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "voice.ogg", mime_type: str = "audio/ogg") -> str:
    """
    Ovozli xabar baytlarini matnga aylantiradi.
    1-bosqich: Groq Whisper API (whisper-large-v3) orqali tezkor transkripsiya.
    2-bosqich: Agar Groq da xatolik bo'lsa, Google Gemini Multimodal Audio orqali transkripsiya.
    """
    if not audio_bytes:
        return ""

    # 1. Groq Whisper orqali transkripsiya qilish
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        for model in ["whisper-large-v3", "whisper-large-v3-turbo"]:
            try:
                url = "https://api.groq.com/openai/v1/audio/transcriptions"
                headers = {"Authorization": f"Bearer {groq_key}"}
                files = {"file": (filename, audio_bytes, mime_type)}
                data = {
                    "model": model,
                    "language": "uz",
                    "temperature": "0.0",
                    "response_format": "json"
                }
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=35)
                if resp.status_code == 200:
                    res_json = resp.json()
                    transcribed = res_json.get("text", "").strip()
                    if transcribed:
                        return transcribed
            except Exception as ge:
                print(f"Groq Whisper ({model}) ogohlantirish:", ge)
                continue

    # 2. Zaxira: Google Gemini Multimodal Audio orqali transkripsiya
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        keys = [k.strip() for k in gemini_key.split(",") if k.strip()]
        for i in range(2, 6):
            extra = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if extra and extra not in keys:
                keys.append(extra)

        for g_k in keys:
            try:
                genai.configure(api_key=g_k)
                for m_name in ["gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-3.5-flash"]:
                    try:
                        model = genai.GenerativeModel(
                            model_name=m_name,
                            system_instruction=(
                                "Sen aniq va xolis audio transkriptorsan. "
                                "Ushbu ovozli xabardagi o'zbek tilidagi nutqni so'zma-so'z to'liq matnga aylantir. "
                                "Hech qanday qo'shimcha izoh, kirish yoki xulosa yozma, faqat eshitilgan matnni qaytar."
                            )
                        )
                        audio_part = {
                            "mime_type": mime_type,
                            "data": audio_bytes
                        }
                        r = model.generate_content(["Iltimos, ushbu ovozli xabarni matnga o'giring:", audio_part])
                        if hasattr(r, "text") and r.text.strip():
                            return r.text.strip()
                    except Exception:
                        continue
            except Exception as g_err:
                print("Gemini audio transkripsiya xatosi:", g_err)
                continue

    return ""
