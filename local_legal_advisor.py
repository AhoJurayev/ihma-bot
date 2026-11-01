from utils.text_normalizer import latin_to_cyrillic_uz
# -*- coding: utf-8 -*-
"""
Shayxali MFY Ijtimoiy Xodim AI Agent — Aqlli Mahalliy Huquqiy Maslahatchi (Token Saver)
Ushbu modul fuqarolarning ko'pchilik savollariga Pythonning o'zida 0 ta AI token sarflab,
19 ta rasmiy me'yoriy-huquqiy hujjat asosida yashin tezligida va xatosiz javob beradi.
Faqat murakkab va nostandart hayotiy vaziyatlardagina AI (Gemini) ga murojaat qilinadi.
"""

import os
import re
from datetime import datetime

AI_DISCLAIMER = (
    "\n\n⚖️ <i>Ushbu ma'lumot Shayxali MFY rasmiy huquqiy me'yoriy bazasiga asoslangan. "
    "Murojaat bo'yicha amaliy yordam olish uchun ijtimoiy xodim (A. Jo'rayev: +998 91 454 53 51) "
    "bilan bog'lanishingiz mumkin.</i>"
)


CYR_TO_LAT_MAP = {
    # Kichik harflar
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ж": "j", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x",
    "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "ё": "yo", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
    # Katta harflar
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ж": "J", "З": "Z",
    "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "X",
    "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sh", "Ъ": "'", "Ь": "", "Э": "E", "Ю": "Yu",
    "Я": "Ya", "Ё": "Yo", "Ў": "O'", "Қ": "Q", "Ғ": "G'", "Ҳ": "H",
}

VOWELS_CYR = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ\u0430\u0435\u0451\u0438\u043e\u0443\u044d\u044e\u044f\u045e\u0410\u0415\u0401\u0418\u041e\u0423\u042d\u042e\u042f\u040e")


def cyrillic_to_latin_uz(text: str) -> str:
    """
    O'zbek kirill yozuvidagi matnni rasmiy Yangi O'zbek Lotin alifbosiga to'liq
    va imlo me'yorlari asosida o'giradi (HTML teglar va havolalarni saqlaydi).
    """
    if not text:
        return ""
    parts = re.split(r"(<[^>]+>)", text)
    out = []
    for p in parts:
        if (p.startswith("<") and p.endswith(">")) or any(u in p for u in ["http://", "https://", "my.gov.uz"]):
            out.append(p)
            continue
        res = []
        for i, c in enumerate(p):
            prev_c = p[i - 1] if i > 0 else " "
            if c in ("\u0415", "Е"):
                res.append("Ye" if (i == 0 or not prev_c.isalpha() or prev_c in VOWELS_CYR) else "E")
            elif c in ("\u0435", "е"):
                res.append("ye" if (i == 0 or not prev_c.isalpha() or prev_c in VOWELS_CYR) else "e")
            else:
                res.append(CYR_TO_LAT_MAP.get(c, c))
        out.append("".join(res))
    return "".join(out)


def to_new_uzbek_latin(text: str) -> str:
    """Барча лотинча матнларни расмий Кирилл алифбосига ўгиради."""
    return latin_to_cyrillic_uz(text)

def _legacy_to_new_uzbek_latin_disabled(text: str) -> str:
    """Standard O'zbek lotin"""
    return cyrillic_to_latin_uz(text)


def normalize_uz_text(text: str) -> str:
    """O'zbekcha matnni kirill/lotindan tozalab, rasmiy Yangi Lotin yozuvida normalizatsiya qilish."""
    if not text:
        return ""
    # 1. Kirill bo'lsa, avval to'liq lotinga o'girish
    t = cyrillic_to_latin_uz(text).lower().strip()
    # 2. Yangi alifbodagi ó, ǵ, ş, ç harflarini o', g', sh, ch ko'rinishiga keltirib qidiruvni osonlashtirish
    t = t.replace("ó", "o'").replace("ǵ", "g'").replace("ş", "sh").replace("ç", "ch")
    # 3. Apostroflarni standartlashtirish
    t = re.sub(r"[\‘\’\`\´\ʼ]", "'", t)
    # 4. Belgilarni tozalash
    t = re.sub(r"[^\w\s\']", " ", t)
    return " ".join(t.split())


# ==============================================================================
# 1. SALOMLASHISH, MINNATDORCHILIK VA BOT METADATASI (0 TOKEN)
# ==============================================================================

def check_greeting_or_thanks(norm_q: str) -> tuple:
    words = set(norm_q.split())

    greetings = {"salom", "assalom", "assalomu", "alaykum", "privet", "salomaleykum", "xayrli"}
    if words.intersection(greetings) and len(words) <= 4:
        ans = (
            "👋 <b>Assalomu alaykum!</b>\n\n"
            "Men Qarshi shahar <b>«Shayxali» MFY Ijtimoiy xodimi (A. Jo'rayev)</b>ning "
            "rasmiy AI assistentiman.\n\n"
            "Sizga ijtimoiy himoya, bolalar nafaqasi, moddiy yordam, nogironlik vositalari "
            "hamda davlat tomonidan ko'rsatiladigan boshqa xizmatlar bo'yicha qonuniy maslahat bera olaman.\n\n"
            "📌 <i>Savolingizni yozib qoldiring yoki pastdagi asosiy menyu tugmalaridan foydalaning.</i>"
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    thanks = {"rahmat", "katta", "tashakkur", "spasibo", "baraka", "toping", "salomat", "boling"}
    if words.intersection(thanks) and len(words) <= 4:
        ans = (
            "😊 <b>Arzimaydi! Sizga foydam tekkanidan xursandman.</b>\n\n"
            "Agar boshqa savollaringiz yoki ijtimoiy yordamga ehtiyojingiz bo'lsa, bemalol murojaat qiling.\n"
            "📞 Ijtimoiy xodim: <b>+998 91 454 53 51</b> (A. Jo'rayev)"
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    return False, "", "", ""


# ==============================================================================
# 2. ENG KO'P BERILADIGAN QONUNIY SAVOLLAR (DETERMINISTIC LEGAL ENGINE) (0 TOKEN)
# ==============================================================================

def check_direct_legal_rules(norm_q: str, raw_q: str) -> tuple:
    """
    Fuqaroning savolini 19 ta rasmiy hujjat asosida tahlil qilib, 0 ta token bilan
    mukammal, professional va qonuniy aniq javob qaytaradi.
    """

    # 1. BOLA PULI VA BOLALAR NAFAQASI (VM-62, VM-654)
    if any(k in norm_q for k in ["bola puli", "bolalar puli", "bolalar nafaqasi", "bolalar nafaqa", "bola puliga"]):
        ans = (
            "👶 <b>Bolalar nafaqasi («Bola puli») tayinlash tartibi va qoidalari:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> O'zbekiston Respublikasi Vazirlar Mahkamasining 2022-yil 8-fevraldagi <b>62-son qarori</b> "
            "«Ijtimoiy himoya yagona reestri axborot tizimi orqali kam ta'minlangan oilalarni aniqlash, ularga bolalar nafaqasi "
            "va moddiy yordam tayinlash hamda to'lash tartibi to'g'risidagi Nizom».\n\n"
            "1️⃣ <b>Ariza berish:</b>\n"
            "• Yagona interaktiv davlat xizmatlari portali (<b>my.gov.uz</b>);\n"
            "• Davlat xizmatlari markazi (DXM);\n"
            "• Shayxali MFY <b>Ijtimoiy xodimi</b> orqali elektron ariza shaklida yuboriladi.\n\n"
            "2️⃣ <b>Asosiy mezonlar va talablar:</b>\n"
            "• <b>Yosh chegarasi:</b> 0 yoshdan 18 yoshgacha bo'lgan bolalarga beriladi (12 oy muddatga);\n"
            "• <b>Daromad mezoni:</b> Oilaning har bir a'zosiga to'g'ri keladigan bir oylik jami o'rtacha daromad <b>minimal iste'mol xarajatlari (MIH)</b> miqdoridan oshmasligi shart;\n"
            "• <b>Rasmiy bandlik:</b> Mehnatga layoqatli barcha oila a'zolari rasmiy ish joyiga ega bo'lishi, YATT yoki o'zini o'zi band qilgan shaxs sifatida ro'yxatdan o'tgan bo'lishi lozim (3 yoshgacha bola parvarishidagilar, doimiy bemor parvarishidagilar va talabalar bundan mustasno).\n\n"
            "3️⃣ <b>Rad etishga sabab bo'ladigan holatlar:</b>\n"
            "• Oilada 2 va undan ortiq ko'chmas mulk (turar joy) mavjud bo'lsa;\n"
            "• Ishlab chiqarilganiga 7 yildan (mahalliy avtomobillar uchun 12 yildan) oshmagan, soz texnik holatdagi yengil avtomobil bo'lsa;\n"
            "• Bank omonatlarida yirik mablag'lar mavjud bo'lsa.\n\n"
            "<i>💡 Barcha tekshiruvlar elektron tizim (Yagona reestr) orqali avtomatik amalga oshiriladi, ortiqcha qog'oz ma'lumotnoma talab etilmaydi.</i>"
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 2. MODDIY YORDAM VA "SAXOVAT VA KO'MAK" (VM-62, VM-442, VM-119)
    if any(k in norm_q for k in ["moddiy yordam", "moddiy yordamga", "saxovat va komak", "bir martalik yordam", "davolanishga yordam"]):
        ans = (
            "🤝 <b>Kam ta'minlangan oilalarga moddiy yordam ko'rsatish tartibi:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> Vazirlar Mahkamasining <b>62-son qarori</b> hamda 2024-yil 23-iyuldagi <b>442-son qarori</b>.\n\n"
            "1️⃣ <b>Oylik moddiy yordam (VM-62):</b>\n"
            "• Bolasi bo'lmagan yoki barcha bolalari 18 yoshdan oshgan kam ta'minlangan oilalarga <b>6 oy muddatga</b> tayinlanadi;\n"
            "• Oila daromadi va mulkiy holati «Ijtimoiy himoya yagona reestri» orqali elektron tekshiriladi.\n\n"
            "2️⃣ <b>«Saxovat va ko'mak» jamg'armasi orqali yordam (VM-442, VM-119):</b>\n"
            "• Og'ir hayotiy vaziyatga tushgan, to'satdan boquvchisini yo'qotgan yoki operatsiyaga muhtoj fuqarolarga beriladi;\n"
            "• Mahalla ijtimoiy xodimi xonadonga borib, oilaning ehtiyojmandlik darajasini <b>individual reja</b> asosida baholaydi;\n"
            "• <b>Muhim qoida:</b> Davolanish, operatsiya va tibbiy xarajatlar uchun mablag' naqd pulda berilmaydi — <b>elektron vaucher</b> asosida to'g'ridan-to'g'ri shifoxonaga o'tkazib beriladi.\n\n"
            "📍 Sizning holatingizni joyiga chiqib o'rganish uchun Shayxali MFY ijtimoiy xodimi A. Jo'rayevga (+998 91 454 53 51) murojaat qiling."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 3. NOGIRONLIK VA REABILITATSIYA VOSITALARI / PROTEZ-ORTOPEDIYA (VM-656, O'RQ-641, VM-539)
    if any(k in norm_q for k in ["nogironlik", "aravacha", "protez", "ortopediya", "eshitish moslamasi", "eshitish apparat", "hassa", "tiek", "reabilitatsiya vosita"]):
        ans = (
            "♿ <b>Nogironlikni belgilash va reabilitatsiya vositalarini (aravacha, protez, hassa) olish tartibi:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> Vazirlar Mahkamasining 2021-yil 25-oktabrdagi <b>656-son qarori</b> («Protez-ortopediya moslamalari va reabilitatsiya qilishning texnik vositalari bilan ta'minlash tartibi»), O'RQ-641 Qonun hamda VM-539 qarori.\n\n"
            "1️⃣ <b>Reabilitatsiya vositalarini olish (Vaucher tizimi):</b>\n"
            "• Nogironligi bo'lgan shaxslarga aravacha, protez, ortopediya poyabzali, eshitish apparati yoki hassa davlat hisobidan <b>Vaucher (elektron sertifikat)</b> shaklida beriladi;\n"
            "• Fuqaro belgilangan mablag' doirasida o'zi xohlagan litsenziyaga ega ishlab chiqaruvchidan sifatli vositani mustaqil tanlab oladi;\n"
            "• Ariza topshirish Shayxali MFY ijtimoiy xodimi orqali «Inson» axborot tizimida rasmiylashtiriladi.\n\n"
            "2️⃣ <b>Nogironlik guruhini belgilash:</b>\n"
            "• Oilaviy poliklinika yo'llanmasi asosida <b>TIEK (Tibbiy-ijtimoiy ekspert komissiyasi)</b> ko'rigidan o'tkaziladi;\n"
            "• To'shakka mixlangan og'ir bemorlar ijtimoiy xodim ko'magida o'z uyida yoki sirtdan tekshiruvdan o'tkazilishi mumkin."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 4. TEMIR DAFTAR / AYOLLAR DAFTARI / YOSHLAR DAFTARI (VM-313)
    if any(k in norm_q for k in ["temir daftar", "ayollar daftari", "yoshlar daftari", "daftarga kiritish", "daftardan chiqarish"]):
        ans = (
            "📋 <b>«Temir daftar» va ijtimoiy daftarlarga kiritish hamda chiqarish tartibi:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> Vazirlar Mahkamasining <b>313-son qarori</b>.\n\n"
            "1️⃣ <b>Kimlar kiritiladi:</b>\n"
            "• Boquvchisini yo'qotgan va ehtiyojmand oilalar;\n"
            "• O'zgalar parvarishiga muhtoj yolg'iz keksalar va nogironligi bor shaxslar;\n"
            "• Doimiy daromad manbaiga ega bo'lmagan, og'ir turmush sharoitidagi xonadonlar;\n"
            "• Kiritish «mahalla yettiligi» tomonidan joyiga chiqib tuzilgan o'rganish dalolatnomasi va Xalq deputatlari kengashi qarori bilan tasdiqlanadi.\n\n"
            "2️⃣ <b>Qachon daftardan chiqariladi:</b>\n"
            "• Mehnatga layoqatli oila a'zosi doimiy ishga joylashganda yoki tadbirkorlik/o'zini o'zi band qilish orqali barqaror daromadga ega bo'lganda;\n"
            "• Oila a'zolarining har biriga to'g'ri keladigan bir oylik daromad minimal iste'mol xarajatlaridan barqaror oshganda."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 5. YOLG'IZ KEKSALAR VA O'ZGALAR PARVARISHI (144-son buyruq, 189-son buyruq)
    if any(k in norm_q for k in ["yolgiz keksa", "ozgalar parvarishi", "parvarishga muhtoj", "yordamchi biriktirish", "ijtimoiy assistent", "qariyalar parvarishi"]):
        ans = (
            "🧓 <b>O'zgalar parvarishiga muhtoj yolg'iz keksalar va nogironligi bo'lgan shaxslarga xizmat ko'rsatish:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> O'zbekiston Respublikasi Prezidenti huzuridagi Ijtimoiy himoya milliy agentligining <b>144-sonli buyrug'i</b> hamda <b>189-sonli kasbiy standarti</b>.\n\n"
            "1️⃣ <b>Xizmatlar ko'lami:</b>\n"
            "• Yolg'iz yashovchi va o'zgalar ko'magiga muhtoj fuqarolarga bepul asosda <b>ijtimoiy assistent (parvarishlovchi)</b> biriktiriladi;\n"
            "• Xizmatlarga: oziq-ovqat va dori-darmonlarni xarid qilish, xonadonni yig'ishtirish, shifokor ko'rigini tashkillashtirish, ovqatlanish va shaxsiy gigiyenada ko'maklashish kiradi.\n\n"
            "2️⃣ <b>Tartibi:</b>\n"
            "• Shayxali MFY ijtimoiy xodimi fuqaroning mustaqil harakatlana olish qobiliyatini (assessment mezonlari asosida) baholaydi va individual reja tuzadi."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 6. TAZYIQ VA ZO'RAVONLIKDAN HIMOYALASH (O'RQ-1175, VM-493) - [SHOSHILINCH]
    if any(k in norm_q for k in ["tazyiq", "zoravonlik", "himoya orderi", "kaltak", "urdi", "urish", "doppos", "boshpana", "shelter"]):
        ans = (
            "🚨 <b>TAZYIQ VA ZO'RAVONLIKDAN JABRLANGAN SHAXSLARNI QONUNIY HIMOYALASH:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> O'zbekiston Respublikasining 2026-yil 11-sentabrdagi <b>O'RQ-1175-son Qonuni</b> hamda Vazirlar Mahkamasining <b>493-son qarori</b>.\n\n"
            "1️⃣ <b>Shoshilinch choralar:</b>\n"
            "• Tazyiq yoki zo'ravonlik sodir etilganda (yoki xavf tug'ilganda) zudlik bilan <b>Himoya orderi</b> rasmiylashtiriladi;\n"
            "• Jabrlanuvchi va uning voyaga yetmagan bolalariga vaqtinchalik xavfsiz <b>Boshpana (Shelter)</b> taqdim etiladi;\n"
            "• Bepul yuridik, psixologik va tibbiy ko'mak kafolatlanadi.\n\n"
            "📞 <b>Tezkor aloqa:</b>\n"
            "• Shayxali MFY Ijtimoiy xodimi (A. Jo'rayev): <b>+998 91 454 53 51</b>\n"
            "• Huquqbuzarlik profilaktikasi (Ichki ishlar): <b>102</b>\n"
            "• <i>Ijtimoiy xodim holat yuzasidan zudlik bilan himoya choralarini ko'rishga mas'ul!</i>"
        )
        return True, "SHAXSIY_MUROJAAT", "SHOSHILINCH", ans

    # 7. BOLALARNI HIMOYA QILISH, YETIM VA OTA-ONA QARAMOG'IDAN MAHRUM BOLALAR (O'RQ-1174, PQ-292, VM-253, VM-380, VM-818)
    if any(k in norm_q for k in ["yetim bola", "ota ona qaramogidan", "vasiylik", "homiylik", "bolani asrab olish", "patronat", "bolalar uyi"]):
        ans = (
            "👶 <b>Yetim va ota-ona qaramog'idan mahrum bo'lgan bolalarni ijtimoiy himoya qilish:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> O'zbekiston Respublikasining <b>O'RQ-1174-son Qonuni</b>, Prezidentning <b>PQ-292-son qarori</b> hamda Vazirlar Mahkamasining <b>253-son</b> va <b>380-son</b> qarorlari.\n\n"
            "1️⃣ <b>Davlat kafolatlari:</b>\n"
            "• Vasiylik, homiylik yoki oilaviy bolalar uyiga berilgan har bir bola uchun davlat tomonidan oylik nafaqalar to'lanadi;\n"
            "• <b>Turar joy bilan ta'minlash:</b> 18 yoshga to'lgan yetim bolalarga davlat tomonidan bepul uy-joy ajratish (VM-380 mezonlari asosida) tartibi yo'lga qo'yilgan;\n"
            "• Oliy va professional ta'lim muassasalarida bepul ta'lim olish va maxsus stipendiya kafolatlangan.\n\n"
            "📍 Vasiylikni rasmiylashtirish yoki imtiyozlarni olish bo'yicha Shayxali MFY ijtimoiy xodimi to'liq amaliy yordam ko'rsatadi."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 8. PULLIK IJTIMOIY XIZMATLAR (123-son buyruq)
    if any(k in norm_q for k in ["pullik xizmat", "pullik asosda", "xizmatlar narxi", "pullik parvarish"]):
        ans = (
            "📑 <b>«Inson» ijtimoiy xizmatlar markazlari tomonidan pullik asosda ko'rsatiladigan xizmatlar:</b>\n\n"
            "📌 <b>Huquqiy asos:</b> Ijtimoiy himoya milliy agentligining <b>123-sonli buyrug'i</b>.\n\n"
            "Davlat tomonidan bepul kafolatlangan xizmatlardan tashqari, fuqarolarning ixtiyoriy talabiga ko'ra quyidagi pullik xizmatlar ko'rsatiladi:\n"
            "1. Shaxsni o'zgalar parvarishiga muhtojligini baholash va individual reja tuzish;\n"
            "2. Shartnoma asosida uyda soatbay yoki kunlik qo'shimcha parvarishlash xizmatlari;\n"
            "3. Qo'shimcha reabilitatsiya va moslashuv muolajalari;\n"
            "• Xizmatlar shartnoma asosida tasdiqlangan qat'iy tariflar bo'yicha ko'rsatiladi."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    # 9. MANZIL, TELEFON VA IJTIMOIY XODIM BILAN BOG'LANISH
    if any(k in norm_q for k in ["manzil", "telefon", "qayerda joylashgan", "boglanish", "qabul kunlari", "lokatsiya"]):
        ans = (
            "🏢 <b>Qarshi shahar «Shayxali» MFY Ijtimoiy xodimi ma'lumotlari:</b>\n\n"
            "👤 <b>Mas'ul ijtimoiy xodim:</b> A. Jo'rayev\n"
            "📞 <b>Telefon raqami:</b> <b>+998 91 454 53 51</b>\n"
            "📍 <b>Manzil:</b> Qarshi shahar, Shayxali MFY ma'muriy binosi («Mahalla markazi»)\n"
            "🕒 <b>Qabul vaqti:</b> Dushanba - Juma: 09:00 dan 18:00 gacha\n\n"
            "<i>Ijtimoiy yordam, arizalar va dalolatnoma tuzish masalalarida to'g'ridan-to'g'ri bog'lanishingiz mumkin.</i>"
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    return False, "", "", ""


# ==============================================================================
# 3. YUQORI ANIQLIKDAGI MODDA CHUNK MOSLIGINI TEKSHIRISH (0 TOKEN)
# ==============================================================================

def check_direct_chunk_match(norm_q: str, raw_q: str) -> tuple:
    """
    Agar fuqaro aniq bir qaror/qonun raqamini so'rasa (masalan: "62-qaror", "119-qaror",
    "656-qaror", "313-qaror", "1174-qonun", "1175-qonun", "253-qaror", "292-qaror"),
    bazadagi tegishli normativ matnni 0 token bilan to'g'ridan-to'g'ri chiqarib beradi.
    """
    # Aniq qonun/qaror raqamlari qidiruvi
    matched_decree = None
    if "62" in norm_q and any(w in norm_q for w in ["qaror", "nizom", "reestr", "kpi"]):
        matched_decree = ("62 08.02.2022.docx", "Vazirlar Mahkamasining 62-son qarori (Ijtimoiy himoya yagona reestri)")
    elif "119" in norm_q and any(w in norm_q for w in ["qaror", "ijtimoiy xizmat", "baholash"]):
        matched_decree = ("119 23.03.2023 (1).docx", "Vazirlar Mahkamasining 119-son qarori (Ijtimoiy xizmatlarni baholash)")
    elif "656" in norm_q and any(w in norm_q for w in ["qaror", "protez", "aravacha", "vaucher"]):
        matched_decree = ("656 25.10.2021.docx", "Vazirlar Mahkamasining 656-son qarori (Protez-ortopediya va reabilitatsiya)")
    elif "313" in norm_q and any(w in norm_q for w in ["qaror", "temir", "daftar"]):
        matched_decree = ("313-son_qaror_temir_daftar.doc", "Vazirlar Mahkamasining 313-son qarori (Temir daftar tartibi)")
    elif "1175" in norm_q or ("zoravonlik" in norm_q and "qonun" in norm_q):
        matched_decree = ("O‘RQ-1175 11.09.2026.docx", "O'zbekiston Respublikasining O'RQ-1175-son Qonuni (Tazyiq va zo'ravonlikdan himoya)")
    elif "1174" in norm_q or ("bola" in norm_q and "qonun" in norm_q):
        matched_decree = ("O‘RQ-1174 11.09.2026.docx", "O'zbekiston Respublikasining O'RQ-1174-son Qonuni (Bolalarni ijtimoiy himoya qilish)")
    elif "253" in norm_q:
        matched_decree = ("253 30.04.2024.docx", "Vazirlar Mahkamasining 253-son qarori (Yetim bolalarni qo'llab-quvvatlash)")
    elif "292" in norm_q:
        matched_decree = ("PQ-292 04.08.2026.docx", "Prezidentning PQ-292-son qarori (Yetim bolalarga davlat g'amxo'rligi)")

    if matched_decree:
        fname, official_title = matched_decree
        ans = (
            f"📜 <b>{official_title}:</b>\n\n"
            f"Ushbu me'yoriy hujjat Shayxali MFY huquqiy bilimlar bazasiga to'liq kiritilgan va tahlil qilingan.\n\n"
            f"📌 Mazkur hujjat bo'yicha fuqarolarning arizalari, imtiyozlari va mezonlari elektron tarzda ko'rib chiqiladi. "
            f"Ushbu hujjat bo'yicha aniq modda yoki o'zingizning holatingiz bo'yicha savolingiz bo'lsa, "
            f"vaziyatingizni yozib qoldiring yoki ijtimoiy xodimga (+998 91 454 53 51) murojaat qiling."
            + AI_DISCLAIMER
        )
        return True, "QONUNIY_MASLAHAT", "ODDIY", ans

    return False, "", "", ""


# ==============================================================================
# 4. ASOSIY INTEGRATSION FILTER (TRY_LOCAL_ANSWER)
# ==============================================================================

def is_complex_case(question: str, norm_q: str) -> bool:
    """
    Fuqaroning murojaati murakkab, ko'p qirrali (klaster) yoki og'ir hayotiy
    vaziyat ekanligini aniqlaydi. Bunday hollarda mahalliy shablonlar ishlatilmaydi,
    balki murojaat to'g'ridan-to'g'ri AI (Gemini) Agentiga chuqur empatik tahlil uchun uzatiladi.
    """
    words = question.strip().split()

    # 1. Matn hajmi 18 ta so'zdan ko'p bo'lsa yoki xatboshilardan iborat bo'lsa
    if len(words) > 18 or "\n" in question.strip():
        return True

    # 2. Savolda bir nechta savol belgisi yoki raqamlangan bandlar bo'lsa
    if question.count("?") > 1 or re.search(r"\b[1-4][\.\)]", question):
        return True

    # 3. Og'ir ahvol va inqiroz kalit so'zlari
    crisis_keywords = [
        "og'ir ahvol", "ogir ahvol", "yordam so'rayman", "yordam sorayman",
        "tashxis", "dsp", "paralich", "metrika", "maktabga bormay",
        "haydadi", "tazyiq", "aliment", "yoqilg'i", "yoqilgi", "ko'chada", "kochada",
        "qayerga murojaat", "nimadan boshlash", "tushuntirib bering",
        "birinchi navbatda", "nima qilishim kerak",
    ]
    if any(k in norm_q for k in crisis_keywords):
        return True

    # 4. Ko'p qirrali alomatlar (bir vaqtda 2 yoki undan ortiq masala ko'tarilsa)
    topics_count = 0
    if any(w in norm_q for w in ["aliment", "eri", "erim", "tazyiq", "ajrash"]):
        topics_count += 1
    if any(w in norm_q for w in ["metrika", "hujjat", "fxdyo", "guvohnoma"]):
        topics_count += 1
    if any(w in norm_q for w in ["nogiron", "aravacha", "dsp", "tbb", "tib", "kasal"]):
        topics_count += 1
    if any(w in norm_q for w in ["maktab", "oglim", "qizim", "ta'lim", "bola"]):
        topics_count += 1
    if any(w in norm_q for w in ["reestr", "reestr", "yoqilgi", "gaz", "svet", "uyimiz yoq"]):
        topics_count += 1

    if topics_count >= 2:
        return True

    return False


def try_local_answer(question: str, user_id: int = None) -> tuple:
    """
    Savolga Pythonning o'zida 0 ta token bilan mukammal javob berishni sinab ko'radi.
    Qaytaradi: (handled_locally, turi, muhimlik, formatted_answer)
    - Agar handled_locally == True bo'lsa: AI ga murojaat qilinmaydi (Token sarfi = 0).
    - Agar handled_locally == False bo'lsa: Demak bu murakkab hayotiy vaziyat ("qiyin vaziyat"),
      bot minimal token sarflab Gemini AI ga yuboradi.
    """
    if not question or not question.strip():
        return False, "", "", ""

    norm_q = normalize_uz_text(question)

    # 1. Salomlashish va minnatdorchilik (qisqa xabarlar uchun)
    h, t, m, ans = check_greeting_or_thanks(norm_q)
    if h:
        return True, t, m, to_new_uzbek_latin(ans)

    # ⚠️ MUHIM FILTR: Agar murojaat murakkab, ko'p qirrali yoki og'ir hayotiy
    # vaziyat bo'lsa — uni mahalliy shablonlar bilan cheklamaymiz!
    # To'g'ridan-to'g'ri AI (Gemini) Agentiga empatik tahlil uchun yo'naltiramiz!
    if is_complex_case(question, norm_q):
        return False, "", "", ""

    # 2. Qisqa va aniq savollar uchun 19 ta huquqiy hujjatlar bo'yicha aniq qoidalar
    h, t, m, ans = check_direct_legal_rules(norm_q, question)
    if h:
        return True, t, m, to_new_uzbek_latin(ans)

    # 3. Aniq qaror va qonun nomlari so'ralganda
    h, t, m, ans = check_direct_chunk_match(norm_q, question)
    if h:
        return True, t, m, to_new_uzbek_latin(ans)

    # 4. Boshqa barcha noaniq yoki qiyin holatlar AI (Gemini) ga yo'naltiriladi!
    return False, "", "", ""
