# 🏛 Qarshi shahar «Shayx-Ali» MFY Ijtimoiy Xodim AI Agent Boti (IHMA BOT)

Oʻzbekiston Respublikasi Ijtimoiy himoya milliy agentligi (IHMA) "Inson" ijtimoiy xizmatlar markazi hamda Qarshi shahar «Shayx-Ali» MFY ijtimoiy xodimi (A. Jo'rayev) uchun maxsus ishlab chiqilgan rasmiy va aqlli raqamli assistent.

---

## 🌟 Tizim Imkoniyatlari va Xususiyatlari
1. **Ikki tomonlama interfeys (Telegram Bot + Telegram Mini App):** Fuqarolar xohishiga ko'ra an'anaviy Telegram chat tugmalaridan yoki zamonaviy, interaktiv **Telegram Mini App (TMA)** dasturidan foydalana oladilar.
2. **Telegram Mini App (TMA):** WebApp texnologiyasi asosida qurilgan maxsus UI:
   - Profil va O'RQ-547 bo'yicha tezkor tasdiqlash nishoni (`Tasdiqlangan ✓`);
   - Interaktiv Nafaqa Kalkulyatori (MIH 669 000 so'm chegarasi, chorva va avtomobil tekshiruvi);
   - AI Maslahatchi chat interfeysi (0-token mahalliy tahlil + Gemini/Groq);
   - Elektron Navbat olish va faol talon (QR-kodli chipta) ko'rinishi;
   - Murojaatlar tarixi monitori va 5 yulduzli CSAT baholash vidjeti;
   - MFY manzillari va tezkor aloqa oynalari.
3. **Soddalashtirilgan ro'yxatdan o'tish (O'RQ-547):** Qog'ozbozlik, xonadon rasmi yoki dumaloq video talabi butunlay bekor qilingan. Atigi 4 ta toza qadam (F.I.Sh., Telefon, Pasport/JShShIR, Manzil).
4. **0 Tokenli Mahalliy Huquqiy Maslahatchi (`local_legal_advisor.py`):** Fuqarolarning ko'pchilik savollariga (bola puli, moddiy yordam, nogironlik vositalari, aliment, vaucherlar) 19 ta rasmiy normativ hujjat asosida Pythonning o'zida 0 ta token sarflab yashin tezligida javob beradi.
5. **Smart Multi-API Failover (Gemini + Groq):** Gemini 3.5 Flash asosiy model sifatida ishlaydi. Agar kvota tugasa (429 xatosi), tizim avtomatik zaxira Groq (GPT-OSS-120B) ga ulanadi.
6. **RAG Bilimlar Bazasi (`knowledge_base.py`):** 19+ ta rasmiy qonun, qaror va nizomlarni (PDF, DOC, DOCX, XLSX, Rasmlar) chuqur semantik tahlil qiladi va savollarga moddama-modda asoslangan javob qaytaradi.
7. **🗄️ SQLite + Avtomatik Excel Eksport (`database.py`):** Excel fayl bloklanishi (PermissionError) ning oldini olish uchun asosiy baza sifatida SQLite (`ihma_database.db`) ishlatiladi. Admin paneldan 1 tugmada barcha jadvallar birlashtirilgan yangi `.xlsx` hisoboti yuklab olinadi.
8. **📄 Admin uchun 1 tugmada Word (.docx) Dalolatnoma:** Murojaat bildirishnomasi ostidagi `[📄 Dalolatnoma (.docx)]` tugmasi orqali Shayx-Ali MFY rasmiy o'rganish dalolatnomasi avtomatik shakllantiriladi.
9. **⭐ Fuqaro roziligini baholash (CSAT):** Murojaat qanoatlantirilganda fuqaroga 5 yulduzli baholash yuboriladi va oylik hisobotda KPI aks etadi.
10. **🛡️ Anti-Spam (Rate Limiter):** Foydalanuvchilarga 1 daqiqada maksimum 3 ta savol cheklovi o'rnatilgan (Admin cheklovsiz).

---

## 📁 Fayllar Tuzilmasi

```text
IHMA BOT/
├── main.py                     # Botning asosiy boshqaruv kodi va Telegram handlerlari
├── webapp_server.py            # Telegram Mini App (TMA) REST API va Flask veb-serveri
├── webapp/                     # Telegram Mini App foydalanuvchi interfeysi (UI)
│   ├── index.html              # Barcha bo'limlar uchun zamonaviy SPA sahifasi
│   ├── style.css               # iOS / Telegram dizayn tizimiga moslashtirilgan stillar
│   └── app.js                  # Telegram WebApp SDK, jonli kalkulyator va API boshqaruvi
├── database.py                 # SQLite ma'lumotlar bazasi, Word (.docx) va Excel eksport moduli
├── local_legal_advisor.py      # 0 ta token sarflovchi mahalliy huquqiy tahlilchi
├── knowledge_base.py           # Barcha turdagi normativ hujjatlarni tahlil qilish (RAG)
├── knowledge_index.json        # 19 ta huquqiy hujjatdan ajratilgan 151+ ta qonuniy moddalar indeksi
├── ihma_database.db            # SQLite tranzaksiyaviy ma'lumotlar bazasi (fuqarolar, murojaatlar, navbatlar)
├── fuqarolar.xlsx              # Fuqarolar reyestri Excel nusxasi
├── murojaatlar.xlsx            # Murojaatlar jurnali Excel nusxasi
├── navbatlar.xlsx              # Elektron navbatlar Excel nusxasi
├── dalolatnomalar/             # Avtomatik shakllantirilgan rasmiy Word (.docx) dalolatnomalar
├── hujjatlar/                  # 19 ta rasmiy qonun, qaror va me'yoriy hujjatlar (DOCX, PDF)
│   └── .ocr_cache/             # Skaner va rasmli hujjatlarning kesh matnlari
├── .env                        # Maxfiy sozlamalar (API kalitlar, Bot token, Admin ID, WEB_APP_URL)
├── .env.example                # Namuna sozlamalar fayli
├── requirements.txt            # Kerakli Python kutubxonalari
└── README.md                   # Loyiha qo'llanmasi
```

---

## 💻 Boshqa kompyuterda ishga tushirish (O'rnatish qo'llanmasi)

### 1-qadam: Python-ni tekshiring
Kompyuterda **Python 3.10 yoki undan yuqori** versiya o'rnatilgan bo'lishi kerak:
```bash
python --version   # yoki python3 --version
```

### 2-qadam: Virtual muhit (venv) yaratish va faollashtirish
Loyihaning asosiy papkasiga kiring:
```bash
cd "IHMA BOT"
```

Virtual muhit yarating:
* **Windows uchun:**
  ```cmd
  python -m venv venv
  venv\Scripts\activate
  ```
* **macOS / Linux uchun:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 3-qadam: Kutubxonalarni o'rnatish
```bash
pip install -r requirements.txt
```

### 4-qadam: `.env` sozlamalarini tekshirish
`.env` faylida quyidagi parametrlar to'g'ri ko'rsatilganiga ishonch hosil qiling:
```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
ADMIN_ID=YOUR_TELEGRAM_ID_HERE
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
GEMINI_MODEL_NAME=gemini-2.5-flash
GROQ_API_KEY=YOUR_GROQ_API_KEY_HERE
```

Ixtiyoriy parametrlar:
* `WEBAPP_HOST` — Mini App serveri manzili. Standart `127.0.0.1` (cloudflared shu manzilga ulanadi). Tashqi tarmoqqa to'g'ridan-to'g'ri ochish kerak bo'lsagina `0.0.0.0` bering.
* `IHMA_DATA_DIR` — baza, zaxira va dalolatnomalar saqlanadigan papka. Standart: loyiha papkasi.
* `ADMIN_TELEGRAPH_PUBLISH=1` — admin keys tahlilini ommaviy Telegraph sahifasida nashr qilish. Standart o'chiq, chunki sahifani havolasi bor har kim o'qiy oladi va niqoblash ism yoki manzilni yashirmaydi.

### 5-qadam: Botni ishga tushirish
* **Windows uchun:**
  ```cmd
  python main.py
  ```
* **macOS / Linux uchun:**
  ```bash
  python3 main.py
  ```

Bot ishga tushganda terminalda quyidagi yozuv chiqadi:
```text
✅ Shayxali MFY Ijtimoiy Xodim AI Agent boti to'liq ishga tushdi...
```

---

## 👨‍💻 Ma'muriy boshqaruv (Admin buyruqlari)
* `/admin` — Boshqaruv panelini ochish (Statistika, Hujjatlar bazasi, Rassilka, Hisobotlar, Excel yuklab olish).
* `/qidiruv FIO yoki Ko'cha` — Fuqaroni bazadan tezkor topish.
* `/xisobot 10-2026` — Belgilangan oy bo'yicha sun'iy intellekt tahliliy hisoboti va CSAT reytingini olish.

---

## 📱 Telegram Mini App (TMA) ni sozlash va ishga tushirish

Bot ishga tushganda uning ichki Flask veb-serveri avtomatik ravishda `http://127.0.0.1:5001` manzilida ishlay boshlaydi.

Telegram mobil va desktop ilovasi xavfsizlik talablariga ko'ra Mini App lardan faqat **HTTPS** protokoli orqali ochilishini talab qiladi.

### Mini App ni Telegramga ulashning eng oson 2 ta usuli:

#### 1-usul: Bepul Cloudflare Tunnel orqali (Tavsiya etiladi)
1. Terminalda quyidagi buyruqni bering:
   ```bash
   cloudflared tunnel --url http://localhost:5001
   ```
2. Terminalda berilgan `https://...trycloudflare.com` havolasini nusxalang.
3. `.env` faylidagi `WEB_APP_URL=` qatoriga qo'ying:
   ```env
   WEB_APP_URL=https://sizning-tunnelingiz.trycloudflare.com
   ```
4. Botni qayta ishga tushiring (`python3 main.py`). Endi fuqarolar Telegramda bot menyusi yoki `[📱 Mini App (Ijtimoiy Xizmat)]` tugmasini bosganda to'g'ridan-to'g'ri Telegram ichida chiroyli dastur ochiladi!

#### 2-usul: ngrok orqali
```bash
ngrok http 5001
```
Hosil bo'lgan `https://...ngrok-free.app` manzilini `.env` faylida `WEB_APP_URL` ga yozing.

---

## 🗄️ Ma'lumotlar bazasini zaxiralash va tiklash (Backup & Restore)

### Zaxira nusxa (Backup) olish:
Bot ishlab turganda kuniga bir marta `backups/` jildiga vaqt tamg'ali nusxa oladi va eng yangi 30 tasini saqlab, eskilarini o'chiradi. Zaxiralar shu kompyuterda turadi: disk ishdan chiqsa ular ham yo'qoladi, shuning uchun vaqti-vaqti bilan `/backup` buyrug'i orqali tashqariga ham oling.
Qo'lda tezkor zaxira olish:
```bash
python3 -c "import database; print('Zaxira yaratildi:', database.backup_database())"
```

### Zaxiradan tiklash (Restore):
Zaxiradan alohida bazaga yoki mavjud bazaga xavfsiz tiklash:
```bash
python3 -c "import database; database.restore_database('backups/ihma_database_backup_YYYYMMDD_HHMMSS.db', 'ihma_database.db')"
```

---

## 🧪 Avtomatlashtirilgan testlarni ishga tushirish

Loyihada xavfsizlik, ma'lumotlar yaxlitligi va funksional sinovlarni o'z ichiga olgan Pytest test to'plami mavjud:
```bash
python3 -m pytest tests
```
`tests/conftest.py` testlarni vaqtinchalik papkaga yo'naltiradi: haqiqiy baza, token va `.env` kerak emas. Telegram, Gemini va Groq bilan haqiqiy aloqa testlarda tekshirilmaydi.


