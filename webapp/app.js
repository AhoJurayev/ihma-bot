/**
 * ШАЙХ-АЛИ МФЙ TELEGRAM MINI APP — CLIENT LOGIC (app.js)
 * Rasmiy "Inson" ijtimoiy xizmatlar markazi raqamli assistenti
 * Расмий тил: Ўзбек Кирилл ва Рус тиллари
 */

// --- I18N TRANSLATIONS DICTIONARY ---
const I18N = {
  uz_cyr: {
    "app_title": "Шайх-Али МФЙ",
    "app_subtitle": "Ижтимоий ходим AI ассистенти",
    "status_open": "Очиқ кириш",
    "status_pending": "Текширилмоқда ⏳",
    "status_verified": "Тасдиқланган ✓",
    "welcome_label": "Хуш келибсиз,",
    "citizen_default_name": "Ҳурматли фуқаро",
    "citizen_default_address": "Қарши шаҳар, Шайхали МФЙ",
    "verify_btn_unverified": "<span class=\"icon\">📝</span> Тасдиқлаш",
    "verify_btn_pending": "<span>⏳</span> Кутилмоқда",
    "verify_btn_verified": "<span>✅</span> Профиль фаол",
    "emergency_title": "Шошилинч ҳуқуқий ёрдам",
    "emergency_desc": "Тазйиқ, зўравонлик ёки оғир касаллик ҳолатларида тезкор чора кўриш",
    "services_title": "Асосий Хизматлар",
    "services_count": "5 та йўналиш",
    "card_calc_title": "Нафақа Калькулятори",
    "card_calc_desc": "Бола пули ва моддий ёрдам мезонларини ҳисоблаш",
    "card_ai_title": "AI Маслаҳатчи",
    "card_ai_desc": "19 та қонун асосида ҳуқуқий таҳлил олиш",
    "card_queue_title": "Электрон Навбат",
    "card_queue_desc": "Ижтимоий ходим қабулига онлайн ёзилиш",
    "card_appeal_title": "Расмий Мурожаат",
    "card_appeal_desc": "Ижтимоий ходимга бевосита ариза юбориш",
    "card_status_title": "Мурожаатим Ҳолати",
    "card_status_desc": "Аризалар тарихи ва ижро ҳолатини кузатиш",
    "card_contact_title": "Манзил ва Ишонч",
    "card_contact_desc": "МФЙ идораси, ишонч рақамлари ва қабул вақти",
    "faq_header": "Энг Кўп Бериладиган Саволлар",
    "nav_home": "Асосий",
    "nav_calc": "Калькулятор",
    "nav_ai": "AI Ёрдам",
    "nav_queue": "Навбат",
    "nav_appeals": "Аризаларим",
    "calc_header_title": "🧮 Нафақа ва Моддий Ёрдам Калькулятори",
    "calc_header_desc": "Ўзбекистон Республикаси ВМ-62 ва ВМ-654 қарорлари асосида эҳтимолий натижани ҳисоблаш",
    "calc_q1": "1. Оиланинг барча аъзолари сони:",
    "calc_q2": "2. Оила аъзоларининг 1 ойлик жами расмий даромади (сўмда):",
    "calc_q2_ph": "Масалан: 2000000 (даромад йўқ бўлса 0)",
    "calc_q3": "3. 18 ёшдан катта, узрсиз расмий ишламайдиган аъзолар сони:",
    "calc_q3_help": "Талабалар, 3 ёшгача бола парваришидагилар ва I–II гуруҳ ногиронлари киритилмайди.",
    "calc_q4": "4. Уй хўжалигида чорва моллари мавжудми?",
    "calc_q4_help": "Қорамол, от, қўй ёки парранда",
    "calc_q5": "5. Деҳқон хўжалиги ва томорқа ер майдони (сотихда):",
    "calc_q6": "6. Оила аъзолари номида автотранспорт борми?",
    "calc_q6_help": "Фойдаланишда ёки номидаги енгил автомобил",
    "calc_car_year_label": "Ишлаб чиқарилган йили:",
    "calc_btn_calc": "⚡ Мезонларни ҳисоблаш",
    "ai_header_title": "IHMA Ақлли Маслаҳатчи",
    "ai_header_desc": "19 та расмий ҳужжат асосида фаол",
    "ai_welcome_msg": "Ассалому алайкум! Мен Шайхали МФЙ ижтимоий хизмати AI ассистентиман. Ижтимоий нафақалар, бола пули, моддий кўмак ёки ногиронлик воситалари бўйича саволларингиз бўлса, марҳамат, ёзинг.",
    "ai_input_ph": "Ҳуқуқий саволингизни ёзинг...",
    "queue_header_title": "📅 Қабулга Онлайн Ёзилиш",
    "queue_header_desc": "Шайхали МФЙ ижтимоий ходими (А. Жўраев) қабулига навбат олиш",
    "queue_step1": "1. Қабул кунини танланг:",
    "queue_step2": "2. Бўш қабул вақтини танланг:",
    "queue_btn_confirm": "🎟 Навбатни тасдиқлаш",
    "appeals_header_title": "🔍 Менинг Мурожаатларим",
    "appeals_btn_new": "+ Янги мурожаат",
    "appeals_empty_text": "Ҳозирча юборилган расмий мурожаатларингиз мавжуд эмас.",
    "appeals_empty_btn": "Янги мурожаат йўллаш",
    "verify_modal_title": "📝 Шахсни Тасдиқлаш",
    "verify_modal_hint": "ЎРҚ-547 қонуни бўйича ҳеч қандай фотосурат ёки видео талаб этилмайди. Атиги 4 та маълумот кифоя:",
    "verify_label_fio": "Тўлиқ исм-шарифингиз (Ф.И.Ш.):",
    "verify_ph_fio": "Эшматов Тошмат Алиевич",
    "verify_label_phone": "Телефон рақамингиз:",
    "verify_label_doc": "Паспорт серия ёки 14 хонали ЖШШИР:",
    "verify_label_addr": "Шайхали МФЙ даги яшаш манзилингиз:",
    "verify_ph_addr": "Навбаҳор кўчаси, 12-уй",
    "verify_btn_submit": "✅ Тасдиқлаш ва Сақлаш",
    "appeal_modal_title": "👨‍💼 Ижтимоий Ходимга Мурожаат",
    "appeal_label_cat": "Мурожаат тоифаси:",
    "appeal_label_text": "Мурожаат матни:",
    "appeal_ph_text": "Вазиятингизни батафсил тушунтириб беринг...",
    "appeal_label_priority": "Муҳимлик даражаси:",
    "appeal_prio_normal": "Оддий",
    "appeal_prio_medium": "Ўрта",
    "appeal_prio_urgent": "Шошилинч 🚨",
    "appeal_btn_submit": "📨 Юбориш",
    "contacts_modal_title": "📍 Шайхали МФЙ Манзиллари",
    "lang_modal_title": "🌐 Тилни танланг / Выберите язык",
    "toast_lang_changed": "✅ Мулоқот тили муваффақиятли ўзгартирилди!"
},
  ru: {
    "app_title": "МСГ «Шайх-Али»",
    "app_subtitle": "AI ассистент соцработника",
    "status_open": "Открытый доступ",
    "status_pending": "На проверке ⏳",
    "status_verified": "Подтверждён ✓",
    "welcome_label": "Добро пожаловать,",
    "citizen_default_name": "Уважаемый гражданин",
    "citizen_default_address": "г. Карши, МСГ Шайхали",
    "verify_btn_unverified": "<span class=\"icon\">📝</span> Подтвердить",
    "verify_btn_pending": "<span>⏳</span> Ожидание",
    "verify_btn_verified": "<span>✅</span> Профиль активен",
    "emergency_title": "Экстренная правовая помощь",
    "emergency_desc": "Оперативные меры при насилии, давлении или тяжелых болезнях",
    "services_title": "Основные Услуги",
    "services_count": "5 направлений",
    "card_calc_title": "Калькулятор пособий",
    "card_calc_desc": "Расчёт критериев детских пособий и матпомощи",
    "card_ai_title": "AI Консультант",
    "card_ai_desc": "Правовой анализ на основе 19 законов",
    "card_queue_title": "Электронная очередь",
    "card_queue_desc": "Онлайн-запись на приём к соцработнику",
    "card_appeal_title": "Официальное обращение",
    "card_appeal_desc": "Прямая отправка заявления соцработнику",
    "card_status_title": "Статус обращений",
    "card_status_desc": "История заявлений и отслеживание статуса",
    "card_contact_title": "Адрес и контакты",
    "card_contact_desc": "Здание МСГ, горячая линия и часы приёма",
    "faq_header": "Часто задаваемые вопросы",
    "nav_home": "Главная",
    "nav_calc": "Калькулятор",
    "nav_ai": "AI Помощь",
    "nav_queue": "Очередь",
    "nav_appeals": "Обращения",
    "calc_header_title": "🧮 Калькулятор пособий и матпомощи",
    "calc_header_desc": "Предварительный расчёт на основе ПКМ №62 и ПКМ №654",
    "calc_q1": "1. Общее количество членов семьи:",
    "calc_q2": "2. Ежемесячный совокупный официальный доход (в сумах):",
    "calc_q2_ph": "Например: 2000000 (если нет дохода 0)",
    "calc_q3": "3. Трудоспособные члены семьи без официальной занятости:",
    "calc_q3_help": "Студенты, лица по уходу за ребёнком до 3 лет и инвалиды I–II групп не учитываются.",
    "calc_q4": "4. Имеется ли в домохозяйстве скот?",
    "calc_q4_help": "Крупный/мелкий рогатый скот, лошади или птица",
    "calc_q5": "5. Площадь приусадебного/дехканского участка (в сотках):",
    "calc_q6": "6. Имеется ли автотранспорт на имя членов семьи?",
    "calc_q6_help": "Легковой автомобиль в собственности или пользовании",
    "calc_car_year_label": "Год выпуска:",
    "calc_btn_calc": "⚡ Рассчитать критерии",
    "ai_header_title": "Умный консультант IHMA",
    "ai_header_desc": "Работает на основе 19 нормативных документов",
    "ai_welcome_msg": "Здравствуйте! Я цифровой AI-ассистент социальной службы МСГ «Шайх-Али». Задайте вопрос о детских пособиях, матпомощи или средствах реабилитации.",
    "ai_input_ph": "Введите ваш правовой вопрос...",
    "queue_header_title": "📅 Онлайн-запись на приём",
    "queue_header_desc": "Запись на приём к соцработнику МСГ «Шайх-Али» (А. Жураев)",
    "queue_step1": "1. Выберите день приёма:",
    "queue_step2": "2. Выберите свободное время:",
    "queue_btn_confirm": "🎟 Подтвердить запись",
    "appeals_header_title": "🔍 Мои обращения",
    "appeals_btn_new": "+ Новое обращение",
    "appeals_empty_text": "У вас пока нет отправленных официальных обращений.",
    "appeals_empty_btn": "Отправить обращение",
    "verify_modal_title": "📝 Подтверждение личности",
    "verify_modal_hint": "По закону ЗРУ-547 фото и видео не требуются. Достаточно 4 пунктов:",
    "verify_label_fio": "Полное Ф.И.О.:",
    "verify_ph_fio": "Эшматов Тошмат Алиевич",
    "verify_label_phone": "Номер телефона:",
    "verify_label_doc": "Серия паспорта или 14-значный ПИНФЛ:",
    "verify_label_addr": "Адрес проживания в МСГ «Шайх-Али»:",
    "verify_ph_addr": "ул. Навбахор, дом 12",
    "verify_btn_submit": "✅ Подтвердить и сохранить",
    "appeal_modal_title": "👨‍💼 Обращение к соцработнику",
    "appeal_label_cat": "Категория обращения:",
    "appeal_label_text": "Текст обращения:",
    "appeal_ph_text": "Подробно опишите вашу жизненную ситуацию...",
    "appeal_label_priority": "Срочность обращения:",
    "appeal_prio_normal": "Обычный",
    "appeal_prio_medium": "Средний",
    "appeal_prio_urgent": "Срочный 🚨",
    "appeal_btn_submit": "📨 Отправить",
    "contacts_modal_title": "📍 Контакты МСГ «Шайх-Али»",
    "lang_modal_title": "🌐 Выберите язык / Tilni tanlang",
    "toast_lang_changed": "✅ Язык общения успешно изменён!"
}
};

I18N.uz_lat = I18N.uz_cyr;

// --- FAQ LOCALIZED DATA ---
const FAQ_I18N = {
  uz_cyr: [
    {
      catIcon: "👶",
      category: "Бола пули (ВМ-62)",
      q: "Бола пули ва моддий ёрдам кимларга берилади?",
      a: "Ҳар бир оила аъзосига тўғри келадиган бир ойлик ўртача даромад белгиланган минимал истеъмол харажатлари (МИҲ) мезонидан ошмаган эҳтиёжманд оилаларга тайинланади (ВМ-62-сон қарор). Ҳисоблашда оила аъзолари сони, расмий даромадлар ва мулк мезонлари ҳисобга олинади.",
      actionText: "🧮 Мезонларни ҳисоблаш",
      actionTab: "calc"
    },
    {
      catIcon: "♿",
      category: "Реабилитация ва ТББ",
      q: "Ногиронлик аравачаси ёки протез олиш учун қаерга мурожаат қилиш керак?",
      a: "ТББ (Тиббий-маслаҳат комиссияси) хулосаси олингач, 'Инсон' ижтимоий хизматлар маркази орқали бепул эҳтиёжмандлик ваучери берилади. Янги шаффоф тизим бўйича фуқаро ўзига маъқул келган аравача ёки протез воситасини эркин танлаб олиш ҳуқуқига эга.",
      actionText: "🤖 AI Маслаҳат олиш",
      actionTab: "ai"
    },
    {
      catIcon: "🛡️",
      category: "Ҳуқуқий ҳимоя (ЎРҚ-561)",
      q: "Зўравонлик ёки тазйиққа учраганда қандай ҳимояланиш мумкин?",
      a: "Ички ишлар органи ёки 102/112 рақамлари орқали 30 кунлик муддатга зудлик билан 'Ҳимоя ордери' расмийлаштирилади. Шунингдек, Шайх-Али МФЙ ижтимоий ходими ва хотин-қизлар фаоли томонидан ҳуқуқий, психологик ва ижтимоий кўмак кўрсатилади.",
      actionText: "🚨 Шошилинч ёрдам",
      actionModal: "emergency"
    },
    {
      catIcon: "📅",
      category: "Қабул ва навбат",
      q: "Ижтимоий ходим қабулига олдиндан ёзилиш мажбурийми?",
      a: "Мажбурий эмас, лекин 'Электрон Навбат' орқали олдиндан вақт банд қилсангиз, маҳалла идорасида навбат кутмасдан, шахсий ажратилган вақтда қабул қилинасиз ҳамда мурожаатингиз биринчи навбатда ўрганилади.",
      actionText: "📅 Навбат олиш",
      actionTab: "queue"
    }
  ],
  ru: [
    {
      catIcon: "👶",
      category: "Детские пособия (ПКМ №62)",
      q: "Кому назначаются детские пособия и материальная помощь?",
      a: "Назначаются малообеспеченным семьям, среднедушевой доход которых не превышает минимальные потребительские расходы (669 000 сум) в соответствии с ПКМ №62. Учитываются доходы всех членов семьи и имущественные критерии.",
      actionText: "🧮 Рассчитать критерии",
      actionTab: "calc"
    },
    {
      catIcon: "♿",
      category: "Реабилитация и ТББ",
      q: "Как получить инвалидную коляску или средства реабилитации?",
      a: "После заключения врачебной комиссии центр 'Инсон' оформляет бесплатный ваучер. Гражданин самостоятельно выбирает подходящее сертифицированное изделие у поставщиков.",
      actionText: "🤖 Спросить AI",
      actionTab: "ai"
    },
    {
      catIcon: "🛡️",
      category: "Защитный ордер (ЗРУ-561)",
      q: "Как защититься при притеснении или насилии?",
      a: "Немедленно обратитесь по номеру 102/112 или к инспектору профилактики для оформления охранного ордера на 30 дней. Соцработник махалли окажет правовую и психологическую помощь.",
      actionText: "🚨 Экстренная помощь",
      actionModal: "emergency"
    },
    {
      catIcon: "📅",
      category: "Прием и очередь",
      q: "Обязательна ли предварительная запись на прием к соцработнику?",
      a: "Не обязательна, но электронная запись через Mini App гарантирует индивидуальный прием без ожидания в очереди в точно назначенное время.",
      actionText: "📅 Записаться на прием",
      actionTab: "queue"
    }
  ]
};

// --- XSS PROTECTION & HTML ESCAPING ---
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Helper to provide secure Telegram WebApp auth headers
function getAuthHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (state.tg && state.tg.initData) {
    headers['X-Telegram-Init-Data'] = state.tg.initData;
    headers['Authorization'] = 'tma ' + state.tg.initData;
  }
  return headers;
}

// --- GLOBAL STATE ---
const state = {
  tg: window.Telegram ? window.Telegram.WebApp : null,
  lang: 'uz_cyr',
  user: {
    id: null,
    first_name: "Ҳурматли фуқаро",
    username: "",
    is_verified: false,
    status: "",
    fio: "",
    phone: "",
    address: "Қарши шаҳар, Шайх-Али МФЙ"
  },
  currentTab: 'home',
  selectedDate: null,
  selectedSlot: null,
  activeTicket: null,
  appeals: [],
  ratingAppealId: null,
  isApiAvailable: true,
  settings: {
    mih_amount: 669000,
    queue_open: true,
    queue_closed_reason: ""
  }
};

function getMihLimit() {
  return (state && state.settings && state.settings.mih_amount) ? state.settings.mih_amount : 669000;
}

// Helper for i18n lookup
function t(key, fallback = "") {
  const l = state.lang || 'uz_cyr';
  if (I18N[l] && I18N[l][key] !== undefined) return I18N[l][key];
  if (I18N['uz_cyr'] && I18N['uz_cyr'][key] !== undefined) return I18N['uz_cyr'][key];
  return fallback;
}

// --- INITIALIZATION ---
document.addEventListener("DOMContentLoaded", () => {
  initTelegram();
  initProfile();
  initQueueDates();
  loadCitizenData();
});

function initTelegram() {
  if (state.tg) {
    try {
      state.tg.ready();
      state.tg.expand();
      if (state.tg.enableClosingConfirmation) {
        state.tg.enableClosingConfirmation();
      }

      // 1. Read user data from Telegram
      if (state.tg.initDataUnsafe && state.tg.initDataUnsafe.user) {
        const u = state.tg.initDataUnsafe.user;
        state.user.id = u.id;
        state.user.first_name = u.first_name || "Фуқаро";
        state.user.username = u.username || "";
        if (u.last_name) {
          state.user.first_name += " " + u.last_name;
        }
      }

      // 2. Read query parameters (?lang=...)
      try {
        const urlParams = new URLSearchParams(window.location.search);
        const qLang = urlParams.get('lang');
        if (qLang && ['uz_cyr', 'uz_lat', 'ru'].includes(qLang)) {
          applyLanguage(qLang);
        }
      } catch (e) {}

      // Adapt theme colors
      if (state.tg.themeParams) {
        document.documentElement.style.setProperty('--bg-primary', state.tg.themeParams.bg_color || '#f4f6fa');
        document.documentElement.style.setProperty('--bg-card', state.tg.themeParams.secondary_bg_color || '#ffffff');
        document.documentElement.style.setProperty('--text-primary', state.tg.themeParams.text_color || '#1a1e28');
        document.documentElement.style.setProperty('--text-secondary', state.tg.themeParams.hint_color || '#707579');
        document.documentElement.style.setProperty('--accent-text', state.tg.themeParams.button_text_color || '#ffffff');
      }
    } catch (e) {
      console.warn("Telegram WebApp init warning:", e);
    }
  }
}

function haptic(type = 'light') {
  if (state.tg && state.tg.HapticFeedback) {
    try {
      if (type === 'success' || type === 'warning' || type === 'error') {
        state.tg.HapticFeedback.notificationOccurred(type);
      } else {
        state.tg.HapticFeedback.impactOccurred(type);
      }
    } catch (e) {}
  }
}

function initProfile() {
  const nameEl = document.getElementById('citizenName');
  const avatarEl = document.getElementById('userAvatar');
  if (nameEl) nameEl.textContent = state.user.first_name;
  if (avatarEl) avatarEl.textContent = (state.user.first_name || "Ф").charAt(0).toUpperCase();
}

// Fetch citizen profile and appeals from backend API
async function loadCitizenData() {
  try {
    const res = await fetch('/api/citizen', {
      headers: getAuthHeaders(),
      cache: 'no-store'
    });
    if (res.status === 401) {
      console.warn("Telegram WebApp autentifikatsiyasi talab qilinadi");
      return;
    }
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok' && data.citizen) {
        state.user.id = data.citizen.telegram_id;
        state.user.status = data.citizen.status || "";
        state.user.is_verified = data.citizen.is_verified || false;
        state.user.fio = data.citizen.fio || state.user.first_name;
        state.user.phone = data.citizen.phone || "";
        state.user.address = data.citizen.address || state.user.address;

        const nameEl = document.getElementById('citizenName');
        const avatarEl = document.getElementById('userAvatar');
        if (nameEl && state.user.fio) nameEl.textContent = state.user.fio;
        if (avatarEl && state.user.fio) avatarEl.textContent = state.user.fio.charAt(0).toUpperCase();

        // Apply language from database or localStorage
        const userLang = data.citizen.lang || localStorage.getItem('ihma_lang') || 'uz_cyr';
        applyLanguage(userLang);

        if (data.settings) {
          state.settings = data.settings;
          checkQueueBanner();
        }

        if (data.appeals && Array.isArray(data.appeals)) {
          state.appeals = data.appeals;
          renderAppealsList();
        }
        if (data.active_ticket) {
          state.activeTicket = data.active_ticket;
          renderActiveTicket();
        }
        return;
      }
    }
    // Fallback if citizen object not ok
    const fallbackLang = localStorage.getItem('ihma_lang') || 'uz_cyr';
    applyLanguage(fallbackLang);
  } catch (err) {
    console.log("Local API not connected, running in independent client mode:", err);
    state.isApiAvailable = false;
    const fallbackLang = localStorage.getItem('ihma_lang') || 'uz_cyr';
    applyLanguage(fallbackLang);
  }
}

function checkQueueBanner() {
  let banner = document.getElementById('queueClosedBanner');
  if (state.settings && state.settings.queue_open === false) {
    const reason = state.settings.queue_closed_reason || "Ijtimoiy xodim mahallada xonadonma-xonadon o'rganishda bo'lganligi sababli bugungi qabul vaqtincha to'xtatilgan.";
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'queueClosedBanner';
      banner.className = 'queue-closed-banner';
      banner.style.cssText = 'background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 12px; padding: 12px; margin-bottom: 14px; color: #fca5a5; font-size: 13px; line-height: 1.4;';
      const bookingForm = document.querySelector('.queue-card');
      if (bookingForm && bookingForm.parentNode) {
        bookingForm.parentNode.insertBefore(banner, bookingForm);
      }
    }
    banner.innerHTML = `⚠️ <b>Қабул вақтинча тўхтатилган:</b><br>${escapeHtml(reason)}`;
    const submitBtn = document.getElementById('confirmBookingBtn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.style.opacity = '0.5';
    }
  } else if (banner) {
    banner.remove();
    const submitBtn = document.getElementById('confirmBookingBtn');
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.style.opacity = '1';
    }
  }
}

// --- LANGUAGE SWITCHING & DOM LOCALIZATION ---
function applyLanguage(lang) {
  if (!['uz_cyr', 'ru'].includes(lang)) lang = 'uz_cyr';
  state.lang = lang;
  try { localStorage.setItem('ihma_lang', lang); } catch (e) {}

  // Update header label
  const labelEl = document.getElementById('currentLangLabel');
  if (labelEl) {
    labelEl.textContent = (lang === 'ru') ? 'Ру' : 'Ўз';
  }

  // Update checkmarks in modal
  ['uz_cyr', 'ru'].forEach(l => {
    const chk = document.getElementById(`check-${l}`);
    const btn = document.getElementById(`langOpt-${l}`);
    if (chk) chk.textContent = (l === lang) ? '✓' : '';
    if (btn) btn.classList.toggle('active', l === lang);
  });

  // Update all data-i18n elements
  const dict = I18N[lang] || I18N['uz_cyr'];
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const k = el.getAttribute('data-i18n');
    if (dict[k] !== undefined) {
      el.textContent = dict[k];
    }
  });

  // Update all data-i18n-placeholder elements
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const k = el.getAttribute('data-i18n-placeholder');
    if (dict[k] !== undefined) {
      el.placeholder = dict[k];
    }
  });

  // Update verification badge / subtext
  updateVerificationBadge(state.user.is_verified, state.user.status);

  // Re-render FAQ
  renderFaq();

  // Re-render dates and slots
  initQueueDates();

  // Re-render active ticket if present
  if (state.activeTicket) {
    renderActiveTicket();
  }

  // Re-render appeals list
  renderAppealsList();
}

function openLangModal() {
  haptic('light');
  openModal('langModal');
}

async function selectLanguage(lang) {
  haptic('selection');
  applyLanguage(lang);
  closeModal('langModal');
  showToast((lang === 'ru' ? '✅ Язык общения успешно изменён!' : '✅ Мулоқот тили муваффақиятли ўзгартирилди!'));

  // Sync with backend database & bot
  try {
    await fetch('/api/set_lang', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ lang: lang })
    });
  } catch (e) {
    console.warn("Could not sync lang to server:", e);
  }
}

function renderFaq() {
  const container = document.getElementById('homeFaqList');
  if (!container) return;
  const lang = (state.lang === 'ru') ? 'ru' : 'uz_cyr';
  const list = FAQ_I18N[lang] || FAQ_I18N['uz_cyr'];

  container.innerHTML = list.map((item, idx) => `
    <div class="faq-card" id="faqCard-${idx}" onclick="toggleFaq(${idx})">
      <div class="faq-card-header">
        <div class="faq-header-left">
          <div class="faq-cat-badge">
            <span class="faq-cat-icon">${item.catIcon}</span>
            <span>${item.category}</span>
          </div>
          <h4 class="faq-question-text">${item.q}</h4>
        </div>
        <div class="faq-toggle-circle" id="faqChevron-${idx}">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </div>
      </div>
      <div class="faq-card-body" id="faqBody-${idx}">
        <div class="faq-answer-inner">
          <p class="faq-answer-text">${item.a}</p>
          ${item.actionText ? `
            <div class="faq-action-row">
              <button class="faq-action-btn" onclick="handleFaqAction(event, '${item.actionTab || ''}', '${item.actionModal || ''}')">
                <span>${item.actionText}</span>
                <span class="faq-btn-arrow">→</span>
              </button>
            </div>
          ` : ''}
        </div>
      </div>
    </div>
  `).join('');
}

function toggleFaq(idx) {
  haptic('light');
  const card = document.getElementById(`faqCard-${idx}`);
  if (!card) return;

  const isOpen = card.classList.contains('open');

  // Close all other FAQ cards smoothly
  document.querySelectorAll('.faq-card').forEach(c => {
    if (c !== card) c.classList.remove('open');
  });

  if (!isOpen) {
    card.classList.add('open');
  } else {
    card.classList.remove('open');
  }
}

function handleFaqAction(event, tab, modal) {
  event.stopPropagation();
  haptic('selection');
  if (tab) {
    switchTab(tab);
  } else if (modal === 'emergency') {
    openModal('emergencyModal');
  }
}

function updateVerificationBadge(isVerified, status = "") {
  const pill = document.getElementById('userStatusPill');
  const text = document.getElementById('userStatusText');
  const verifyBtn = document.getElementById('quickVerifyBtn');
  const addressEl = document.getElementById('citizenAddress');
  const lang = state.lang || 'uz_cyr';

  if (addressEl && state.user.address) {
    addressEl.textContent = state.user.address;
  }

  if (isVerified || status === 'Tasdiqlangan') {
    if (pill) pill.className = 'user-status-pill verified';
    if (text) text.textContent = t('user_status_verified', 'Tasdiqlangan ✓');
    if (verifyBtn) {
      verifyBtn.innerHTML = `<span>✅</span> ${t('verify_btn_active', 'Profil faol')}`;
      verifyBtn.classList.add('verified-btn');
      verifyBtn.onclick = () => showToast((lang === 'ru' ? 'Ваш профиль подтверждён.' : 'Шахсингиз тасдиқланган ва профиль тўлиқ фаол.'));
    }
  } else if (status === 'Kutmoqda') {
    if (pill) pill.className = 'user-status-pill pending';
    if (text) text.textContent = (lang === 'ru' ? 'На проверке ⏳' : 'Текширилмоқда ⏳');
    if (verifyBtn) {
      verifyBtn.innerHTML = `<span>⏳</span> ${t('verify_btn_pending', 'Kutilmoqda')}`;
      verifyBtn.classList.remove('verified-btn');
      verifyBtn.onclick = () => showToast((lang === 'ru' ? 'Данные на проверке у администратора.' : 'Маълумотларингиз админ текширувида. Тасдиқланиши билан фаоллашади.'));
    }
  } else {
    if (pill) pill.className = 'user-status-pill';
    if (text) text.textContent = (lang === 'ru' ? 'Открытый доступ' : 'Очиқ кириш');
    if (verifyBtn) {
      verifyBtn.innerHTML = `<span class="icon">📝</span> ${(lang === 'ru' ? 'Подтвердить' : 'Тасдиқлаш')}`;
      verifyBtn.classList.remove('verified-btn');
      verifyBtn.onclick = () => openVerifyModal();
    }
  }
}

// --- TAB NAVIGATION ---
function switchTab(tabId) {
  if (tabId === 'queue') tabId = 'appeals';
  haptic('selection');
  state.currentTab = tabId;

  // Update tab buttons
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
  });

  // Update tab panes
  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.remove('active');
  });

  const activePane = document.getElementById(`tab-${tabId}`);
  if (activePane) {
    activePane.classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// --- FAQ ACCORDION ---


// --- NAFAQA KALKULYATORI ---
function toggleCarDetails() {
  const hasCar = document.getElementById('calcHasCar').value === '1';
  const group = document.getElementById('carYearGroup');
  if (group) {
    group.style.display = hasCar ? 'block' : 'none';
  }
}

function calculateBenefit() {
  haptic('medium');
  const familySize = parseInt(document.getElementById('familySize').value) || 1;
  const childUnder3 = parseInt(document.getElementById('childUnder3').value) || 0;
  const child3to18 = parseInt(document.getElementById('child3to18').value) || 0;
  const totalSalary = parseFloat(document.getElementById('totalSalary').value) || 0;
  const totalOther = parseFloat(document.getElementById('totalOther').value) || 0;
  const unemployed = parseInt(document.getElementById('unemployedMembers').value) || 0;
  const hasCar = document.getElementById('calcHasCar').value === '1';

  const totalMonthly = totalSalary + totalOther;
  const perCapita = Math.round(totalMonthly / Math.max(familySize, 1));

  let passed = true;
  const reasons = [];

  const lang = state.lang || 'uz_cyr';

  // Cheklov 1: Ishsiz a'zolar
  if (unemployed > 0) {
    passed = false;
    if (lang === 'ru') {
      reasons.push(`В семье есть трудоспособные неработающие граждане (${unemployed} чел.), высокий риск отказа по критериям ПКМ №62`);
    } else {
      reasons.push(`Оилада расмий банд бўлмаган (${unemployed} нафар) меҳнатга лаёқатли аъзо бор (ВМ-62 мезонларига асосан рад этилиш эҳтимоли юқори)`);
    }
  }

  // Cheklov 2: Avtomobil
  if (hasCar) {
    const carYear = parseInt(document.getElementById('carYear').value) || 2018;
    const currentYear = new Date().getFullYear();
    if ((currentYear - carYear) < 7) {
      passed = false;
      if (lang === 'ru') {
        reasons.push(`Имеется автотранспортное средство со сроком выпуска менее 7 лет (${carYear} г.)`);
      } else {
        reasons.push(`Ишлаб чиқарилганига 7 йилдан кам бўлган автотранспорт воситаси мавжуд (${carYear}-йил)`);
      }
    }
  }

  // Cheklov 3: MIH mezon daromadi (Dinamik sozlamalardan olinadi)
  const currentMih = getMihLimit();
  if (perCapita > currentMih) {
    passed = false;
    if (lang === 'ru') {
      reasons.push(`Доход на одного члена семьи (${perCapita.toLocaleString()} сум) превышает порог МПР (${currentMih.toLocaleString()} сум)`);
    } else {
      reasons.push(`Оила аъзоси бошига даромад (${perCapita.toLocaleString()} сўм) минимал харажат чегараси (${currentMih.toLocaleString()} сўм)дан юқори`);
    }
  }

  renderCalcResult({
    passed,
    perCapita,
    totalMonthly,
    familySize,
    reasons,
    mih: currentMih
  });
}

function renderCalcResult(res) {
  const card = document.getElementById('calcResultCard');
  if (!card) return;

  const lang = state.lang || 'uz_cyr';
  const statusClass = res.passed ? 'status-pass' : 'status-fail';
  const statusIcon = res.passed ? '✅' : '⚠️';

  let statusTitle = "";
  let statusDesc = "";
  let reasonsHeader = "";
  let perCapitaLabel = "";
  let mihLabel = "";
  let totalIncomeLabel = "";
  let appealBtnText = "";
  let aiBtnText = "";
  let somText = "";

  if (lang === 'ru') {
    statusTitle = res.passed ? "Высокая вероятность одобрения" : "Не полностью соответствует критериям";
    statusDesc = res.passed
      ? "Введенные данные соответствуют требованиям Единого реестра социальной защиты (ПКМ №62)."
      : "Имеются факторы риска автоматического отказа по следующим причинам:";
    reasonsHeader = "Обратите внимание:";
    perCapitaLabel = "Доход на одного члена:";
    mihLabel = "Порог МПР (критерий):";
    totalIncomeLabel = "Общий семейный доход:";
    appealBtnText = "👨‍💼 Подать официальное обращение соцработнику";
    aiBtnText = "🤖 Получить AI-консультацию";
    somText = "сум";
  } else {
    statusTitle = res.passed ? "Эҳтимоллик Юқори (Тавсия этилади)" : "Мезонларга Тўлиқ Тушмади";
    statusDesc = res.passed
      ? "Киритилган маълумотлар ВМ-62 қароридаги 'Ижтимоий ҳимоя ягона реестри' талабларига мос келади."
      : "Қуйидаги омиллар сабабли аризанинг автоматик рад этилиш хавфи мавжуд:";
    reasonsHeader = "Эътибор қаратиш зарур:";
    perCapitaLabel = "Жон бошига даромад:";
    mihLabel = "МИҲ мезони (чегара):";
    totalIncomeLabel = "Жами ҳисобланган даромад:";
    appealBtnText = "👨‍💼 Ижтимоий ходимга расмий мурожаат қилиш";
    aiBtnText = "🤖 AI Маслаҳат олиш";
    somText = "сўм";
  }

  let reasonsHtml = '';
  if (res.reasons.length > 0) {
    reasonsHtml = `
      <div class="result-reasons">
        <strong>${reasonsHeader}</strong>
        <ul>
          ${res.reasons.map(r => `<li>${r}</li>`).join('')}
        </ul>
      </div>
    `;
  }

  card.className = `calc-result-card ${statusClass}`;
  card.innerHTML = `
    <div class="result-header">
      <span class="res-icon">${statusIcon}</span>
      <div>
        <h4>${statusTitle}</h4>
        <p>${statusDesc}</p>
      </div>
    </div>

    <div class="result-metrics">
      <div class="metric-item">
        <span class="metric-label">${perCapitaLabel}</span>
        <span class="metric-val ${res.perCapita <= res.mih ? 'text-green' : 'text-red'}">
          ${res.perCapita.toLocaleString()} ${somText}
        </span>
      </div>
      <div class="metric-item">
        <span class="metric-label">${mihLabel}</span>
        <span class="metric-val">${res.mih.toLocaleString()} ${somText}</span>
      </div>
      <div class="metric-item">
        <span class="metric-label">${totalIncomeLabel}</span>
        <span class="metric-val">${res.totalMonthly.toLocaleString()} ${somText} / oy</span>
      </div>
    </div>

    ${reasonsHtml}

    <div class="result-actions">
      <button class="btn-primary" onclick="openAppealModal('Bolalar nafaqasi va moddiy yordam')">
        <span>${appealBtnText}</span>
      </button>
      <button class="btn-outline" onclick="switchTab('ai'); setAiInput('${aiBtnText}: ' + ${res.perCapita} + ' ${somText}')">
        <span>${aiBtnText}</span>
      </button>
    </div>
  `;

  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  haptic(res.passed ? 'success' : 'warning');
}

// --- AI ASSISTENT CHAT LOGIKASI ---
function setAiInput(text) {
  const input = document.getElementById('chatInput');
  if (input) {
    input.value = text;
    input.focus();
  }
}

function sendQuickPrompt(prompt) {
  const input = document.getElementById('chatInput');
  if (input) {
    input.value = prompt;
    sendChatMessage();
  }
}

function handleChatEnter(e) {
  if (e.key === 'Enter') {
    sendChatMessage();
  }
}

async function sendChatMessage() {
  const input = document.getElementById('chatInput');
  const text = (input ? input.value : "").trim();
  if (!text) return;

  haptic('light');
  input.value = "";

  appendChatMessage(text, 'user');

  // Loading typing message
  const loadingId = 'loading-' + Date.now();
  appendChatMessage(t('ai_loading_msg', 'Savolingiz normativ hujjatlar bazasi asosida tahlil qilinmoqda...'), 'bot', loadingId, true);

  try {
    const res = await fetch('/api/ai_chat', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        message: text,
        lang: state.lang
      })
    });

    removeChatMessage(loadingId);

    if (res.ok) {
      const data = await res.json();
      if (data.status === 'ok' && data.reply) {
        appendChatMessage(data.reply, 'bot');
        haptic('light');
      } else {
        appendChatMessage((state.lang === 'ru' ? 'Извините, произошла ошибка. Пожалуйста, обратитесь к соцработнику.' : 'Кечирасиз, жавоб олишда хатолик юз берди. Илтимос, қайта уриниб кўринг ёки ижтимоий ходимга мурожаат қилинг.'), 'bot');
      }
    } else if (res.status === 429) {
      const data = await res.json().catch(() => ({}));
      appendChatMessage(data.message || (state.lang === 'ru' ? 'Слишком много запросов. Попробуйте через минуту.' : 'Жуда кўп сўров юборилди. Бир дақиқадан сўнг қайта уриниб кўринг.'), 'bot');
    } else {
      fallbackLocalAnswer(text);
    }
  } catch (err) {
    removeChatMessage(loadingId);
    fallbackLocalAnswer(text);
  }
}

function fallbackLocalAnswer(query) {
  const lower = query.toLowerCase();
  let answer = "";
  const lang = state.lang || 'uz_cyr';

  if (lang === 'ru') {
    if (lower.includes("дет") || lower.includes("пособ") || lower.includes("выплат")) {
      answer = "👶 **Детские пособия и материальная помощь:**\nСогласно ПКМ №62 доход на каждого члена семьи не должен превышать 669 000 сум в месяц. Все трудоспособные члены семьи должны иметь официальную занятость.";
    } else if (lower.includes("инвалид") || lower.includes("коляск") || lower.includes("ваучер")) {
      answer = "♿ **Реабилитация и инвалидность (Ваучер):**\nНа основании постановления ПП-107 предоставляется электронный ваучер для бесплатного приобретения протезно-ортопедических изделий.";
    } else if (lower.includes("насили") || lower.includes("притесн") || lower.includes("ордер")) {
      answer = "🚨 **Защита от насилия:**\nСрочно звоните 102 или обратитесь к инспектору профилактики для оформления охранного ордера на 30 дней. Соцработник обеспечит правовую и кризисную поддержку.";
    } else {
      answer = "Уважаемый гражданин! Сервер сейчас недоступен, поэтому ваш вопрос не сохранён. Для точной информации отправьте заявку через раздел 'Официальное обращение' или позвоните по номеру: +998 91 454 53 51.";
    }
  } else {
    // uz_cyr
    if (lower.includes("бола") || lower.includes("нафақа") || lower.includes("пул")) {
      answer = "👶 **Болалар нафақаси ва моддий ёрдам:**\nВМ-62-сон қарорига асосан оиланинг ҳар бир аъзосига тўғри келадиган ойлик жами даромад белгиланган минимал истеъмол харажатлари (МИҲ) мезонидан ошмаган бўлиши лозим. Шунингдек, оилада меҳнатга лаёқатли барча аъзолар расмий банд бўлиши шарт.";
    } else if (lower.includes("ногирон") || lower.includes("арава") || lower.includes("ваучер")) {
      answer = "♿ **Ногиронлик ва реабилитация (Ваучер тизими):**\nЎзбекистон Республикаси Президентининг ПҚ-107 қарорига асосан ТББ хулосаси асосида бепул ваучер тақдим этилади.";
    } else if (lower.includes("тазйиқ") || lower.includes("зўравонлик") || lower.includes("ҳимоя") || lower.includes("ордер")) {
      answer = "🚨 **Тазйиқ ва зўравонликдан ҳимоя:**\nЗудлик билан 102 ёки ҳудудий профилактика инспекторига хабар беринг. ЎРҚ-561 қонуни асосида 30 кунлик 'Ҳимоя ордери' расмийлаштирилади.";
    } else {
      answer = "Ҳурматли фуқаро! Сервер ҳозир жавоб бермаяпти, шу сабабли саволингиз сақланмади. Ушбу масала бўйича аниқ маълумот олиш учун 'Расмий Мурожаат' бўлими орқали Шайх-Али МФЙ ижтимоий ходимига сўров юборишингизни тавсия этамиз.";
    }
  }

  appendChatMessage(answer, 'bot');
}

function appendChatMessage(text, sender = 'bot', elementId = null, isLoading = false) {
  const container = document.getElementById('chatMessages');
  if (!container) return;

  const msgDiv = document.createElement('div');
  msgDiv.className = `message msg-${sender}`;
  if (elementId) msgDiv.id = elementId;

  const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  // XSS Himoyasi: Matnni oldindan to'liq escape qilish
  let safeText = escapeHtml(text);
  if (sender === 'bot') {
    // Server javobi Telegram HTML formatida keladi: escape dan keyin faqat xavfsiz teglar tiklanadi
    safeText = safeText
      .replace(/&lt;(\/?)(b|strong|i|em|u|code|pre|blockquote)(?: expandable(?:=&quot;&quot;)?)?&gt;/g, '<$1$2>')
      .replace(/&lt;a href=&quot;(https:\/\/(?:[^&\s]|&amp;)+?)&quot;&gt;/g, '<a href="$1" target="_blank" rel="noopener noreferrer">')
      .replace(/&lt;\/a&gt;/g, '</a>');
  }
  let formatted = safeText
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');

  msgDiv.innerHTML = `
    <div class="msg-bubble ${isLoading ? 'loading-bubble' : ''}">
      ${isLoading ? '<div class="typing-dots"><span></span><span></span><span></span></div>' : ''}
      <div>${formatted}</div>
    </div>
    <div class="msg-time">${timeStr}</div>
  `;

  container.appendChild(msgDiv);
  container.scrollTop = container.scrollHeight;
}

function removeChatMessage(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function clearChat() {
  const container = document.getElementById('chatMessages');
  if (container) {
    const clearText = (state.lang === 'ru') ? 'Чат очищен. Можете задать новый вопрос.' : 'Суҳбат тозаланди. Янги ҳуқуқий саволингизни беришингиз мумкин.';
    container.innerHTML = `
      <div class="message msg-bot">
        <div class="msg-bubble">
          ${clearText}
        </div>
        <div class="msg-time">Hozir</div>
      </div>
    `;
  }
}

// --- ELEKTRON NAVBAT (QUEUE) LOGIKASI ---
function initQueueDates() {
  const daysContainer = document.getElementById('queueDaysContainer');
  const slotsContainer = document.getElementById('queueSlotsContainer');
  if (!daysContainer) return;

  const lang = state.lang || 'uz_cyr';
  const weekDaysMap = {
    uz_cyr: ['Як', 'Душ', 'Сеш', 'Чор', 'Пай', 'Жум', 'Шан'],
    ru: ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
  };
  const monthNamesMap = {
    uz_cyr: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'],
    ru: ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
  };

  const weekDays = weekDaysMap[lang] || weekDaysMap['uz_cyr'];
  const monthNames = monthNamesMap[lang] || monthNamesMap['uz_cyr'];

  const days = [];
  const now = new Date();
  let count = 0;
  let offset = 0;
  while (count < 7) {
    const d = new Date(now);
    d.setDate(now.getDate() + offset);
    offset++;
    if (d.getDay() === 0 || d.getDay() === 6) continue; // Qabul faqat Dushanba-Juma

    // toISOString UTC sanani beradi: Toshkentda yarim tundan keyin bir kun orqada qolardi
    const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    days.push({
      dateStr: dateStr,
      dayName: weekDays[d.getDay()],
      dayNum: d.getDate(),
      monthName: monthNames[d.getMonth()]
    });
    count++;
  }

  daysContainer.innerHTML = days.map((d, i) => `
    <div class="day-chip ${i === 0 ? 'selected' : ''}" onclick="selectQueueDate('${d.dateStr}', this)">
      <span class="day-label">${d.dayName}</span>
      <span class="day-num">${d.dayNum}</span>
      <span class="day-month">${d.monthName}</span>
    </div>
  `).join('');

  state.selectedDate = days[0].dateStr;
  loadQueueSlots(days[0].dateStr);
}

// Tanlangan sana uchun vaqtlarni serverdagi haqiqiy bandlik bilan chizadi
async function loadQueueSlots(dateStr) {
  const slotsContainer = document.getElementById('queueSlotsContainer');
  if (!slotsContainer) return;

  const lang = state.lang || 'uz_cyr';
  let slots = ['09:00', '10:00', '11:00', '14:00', '15:00', '16:00'];
  let booked = [];
  try {
    const res = await fetch(`/api/queue/slots?date=${encodeURIComponent(dateStr)}`, { headers: getAuthHeaders() });
    if (res.ok) {
      const data = await res.json();
      slots = data.slots || slots;
      booked = data.booked || [];
    }
  } catch (e) {
    // Tarmoq xatosida ham ro'yxat ko'rinadi: band vaqtni baribir server rad etadi
  }
  if (state.selectedDate !== dateStr) return; // Javob kelguncha boshqa sana tanlangan

  const now = new Date();
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const nowTime = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const isUnavailable = (s) => booked.includes(s) || (dateStr === todayStr && s <= nowTime);
  const firstFree = slots.find(s => !isUnavailable(s)) || null;

  const freeLabel = lang === 'ru' ? 'Свободно' : 'Бўш';
  const busyLabel = lang === 'ru' ? 'Занято' : 'Банд';
  const pastLabel = lang === 'ru' ? 'Прошло' : 'Ўтган';
  slotsContainer.innerHTML = slots.map(s => {
    const safeSlot = escapeHtml(s);
    if (isUnavailable(s)) {
      const label = booked.includes(s) ? busyLabel : pastLabel;
      return `
    <div class="time-slot" style="opacity: 0.45; pointer-events: none;">
      <span class="slot-time">${safeSlot}</span>
      <span class="slot-status">${label}</span>
    </div>`;
    }
    return `
    <div class="time-slot ${s === firstFree ? 'selected' : ''}" data-slot="${safeSlot}" onclick="selectQueueSlot(this.getAttribute('data-slot'), this)">
      <span class="slot-time">${safeSlot}</span>
      <span class="slot-status">${freeLabel}</span>
    </div>`;
  }).join('');

  state.selectedSlot = firstFree;
}

function selectQueueDate(dateStr, el) {
  haptic('selection');
  state.selectedDate = dateStr;
  state.selectedSlot = null;
  document.querySelectorAll('.day-chip').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  loadQueueSlots(dateStr);
}

function selectQueueSlot(slot, el) {
  haptic('selection');
  state.selectedSlot = slot;
  document.querySelectorAll('.time-slot').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
}

async function confirmBooking() {
  if (!state.selectedDate || !state.selectedSlot) {
    showToast(t('queue_select_error', 'Илтимос, сана ва вақтни танланг!'));
    return;
  }

  haptic('medium');
  const btn = document.getElementById('confirmBookingBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = (state.lang === 'ru') ? "Оформление..." : "Банд қилинмоқда...";
  }

  const payload = {
    date: state.selectedDate,
    time_slot: state.selectedSlot,
    purpose: "Ижтимоий ёрдам ва ҳужжатлаштириш масаласида қабул"
  };

  try {
    const res = await fetch('/api/queue', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      state.activeTicket = data.ticket;
      renderActiveTicket();
      showToast(t('queue_success_toast', 'Қабулга навбат муваффақиятли банд қилинди! ✅'));
      haptic('success');
    } else {
      const errMsg = (data && data.message) ? data.message : "Навбат олишда хатолик юз берди";
      showToast("❌ " + errMsg);
      haptic('error');
      loadQueueSlots(state.selectedDate); // Boshqa fuqaro band qilgan bo'lishi mumkin
    }
  } catch (e) {
    showToast("❌ Сервер билан алоқада хатолик");
    haptic('error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = t('queue_btn_confirm', '🎟 Навбатни тасдиқлаш');
    }
  }
}

async function cancelActiveTicket(ticketNumber) {
  if (!confirm("Ҳақиқатан ҳам ушбу қабул навбатини бекор қилмоқчимисиз?")) return;
  haptic('warning');
  try {
    const res = await fetch('/api/queue/cancel', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ ticket_number: ticketNumber, reason: "Fuqaro TMA orqali bekor qildi" })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      state.activeTicket = null;
      const card = document.getElementById('activeTicketCard');
      if (card) card.style.display = 'none';
      showToast(t('ticket_cancelled_toast', 'Қабул навбати бекор қилинди ва вақт слоти бўшатилди ✅'));
      haptic('success');
      loadCitizenData();
    } else {
      showToast("❌ " + (data.message || 'Хатолик юз берди'));
      haptic('error');
    }
  } catch (e) {
    showToast('❌ Сервер билан боғланишда хатолик');
  }
}

function renderActiveTicket() {
  const card = document.getElementById('activeTicketCard');
  if (!card || !state.activeTicket) return;

  const lang = state.lang || 'uz_cyr';
  let badgeText = "ФАОЛ НАВБАТ ТАЛОНИ";
  let citizenLabel = "Фуқаро:";
  let dateTimeLabel = "Қабул санаси ва вақти:";
  let officerLabel = "Қабул қилувчи:";
  let addressLabel = "Манзил:";
  let noteText = "Илтимос, белгиланган вақтдан 10 дақиқа олдин шахсингизни тасдиқловчи ҳужжат билан ташриф буюринг.";
  let cancelBtnText = "Навбатни бекор қилиш";

  if (lang === 'ru') {
    badgeText = "АКТИВНЫЙ ТАЛОН ОЧЕРЕДИ";
    citizenLabel = "Гражданин:";
    dateTimeLabel = "Дата и время приема:";
    officerLabel = "Специалист:";
    addressLabel = "Адрес:";
    noteText = "Пожалуйста, приходите за 10 минут до назначенного времени с документом, удостоверяющим личность.";
    cancelBtnText = "Отменить запись";
  }

  const safeNum = escapeHtml(state.activeTicket.ticket_number);
  const safeFio = escapeHtml(state.activeTicket.fio || state.user.first_name);
  const safeDate = escapeHtml(state.activeTicket.date);
  const safeTime = escapeHtml(state.activeTicket.time_slot);

  card.innerHTML = `
    <div class="ticket-header">
      <div>
        <span class="ticket-badge">${badgeText}</span>
        <h3 class="ticket-num">${safeNum}</h3>
      </div>
      <div class="ticket-qr-mock" title="Рақамли талон">
        <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7"></rect>
          <rect x="14" y="3" width="7" height="7"></rect>
          <rect x="14" y="14" width="7" height="7"></rect>
          <rect x="3" y="14" width="7" height="7"></rect>
        </svg>
      </div>
    </div>
    <div class="ticket-body">
      <div class="ticket-row">
        <span>${citizenLabel}</span>
        <strong>${safeFio}</strong>
      </div>
      <div class="ticket-row">
        <span>${dateTimeLabel}</span>
        <strong class="text-green">${safeDate} — ${safeTime}</strong>
      </div>
      <div class="ticket-row">
        <span>${officerLabel}</span>
        <span>А. Жўраев (Ижтимоий ходим)</span>
      </div>
      <div class="ticket-row">
        <span>${addressLabel}</span>
        <span>Шайх-Али МФЙ идораси</span>
      </div>
    </div>
    <div class="ticket-footer">
      <div id="ticketQrBox" style="text-align: center; margin-bottom: 12px;"></div>
      <p>${noteText}</p>
      <div style="margin-top: 12px; text-align: center;">
        <button class="btn-cancel-ticket" onclick="cancelActiveTicket('${safeNum}')" style="background: rgba(239,68,68,0.1); border: 1px solid #ef4444; color: #ef4444; border-radius: 8px; padding: 6px 14px; font-size: 12px; cursor: pointer; font-weight: 500;">
          ❌ ${cancelBtnText}
        </button>
      </div>
    </div>
  `;
  card.style.display = 'block';
  card.scrollIntoView({ behavior: 'smooth' });
  loadTicketQr();
}

// QR rasmi avtorizatsiya sarlavhasi bilan olinadi, shuning uchun <img src> ga to'g'ridan-to'g'ri berilmaydi
async function loadTicketQr() {
  const box = document.getElementById('ticketQrBox');
  if (!box) return;
  try {
    const res = await fetch('/api/queue/qr', { headers: getAuthHeaders() });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const img = document.createElement('img');
    img.alt = 'QR';
    img.style.cssText = 'width: 160px; height: 160px; background: #fff; padding: 8px; border-radius: 12px;';
    img.onload = () => URL.revokeObjectURL(url);
    img.src = url;
    box.replaceChildren(img);
  } catch (e) {
    // QR bo'lmasa ham talon raqami bilan qabulga kirish mumkin
  }
}

// --- RASMIY MUROJAAT (APPEALS) LOGIKASI ---
function openAppealModal(presetCategory = null) {
  haptic('light');
  if (presetCategory) {
    const sel = document.getElementById('appealCategory');
    if (sel) sel.value = presetCategory;
  }
  openModal('appealModal');
}

async function submitOfficialAppeal() {
  const cat = document.getElementById('appealCategory').value;
  const text = document.getElementById('appealText').value.trim();
  const priorityRadio = document.querySelector('input[name="appealPriority"]:checked');
  const priority = priorityRadio ? priorityRadio.value : 'ODDIY';

  if (!text) {
    showToast(t('appeal_text_empty_toast', 'Илтимос, мурожаат матнини ёзинг!'));
    return;
  }

  haptic('medium');
  const btn = document.querySelector('#appealModal button[onclick*="submitOfficialAppeal"]') || document.querySelector('#appealModal .btn-primary');
  if (btn) {
    btn.disabled = true;
    btn.textContent = (state.lang === 'ru') ? "Отправка..." : "Юборилмоқда...";
  }

  const payload = {
    category: cat,
    text: text,
    priority: priority
  };

  try {
    const res = await fetch('/api/appeal', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      closeModal('appealModal');
      document.getElementById('appealText').value = "";
      showToast(t('appeal_sent_toast', 'Мурожаатингиз ижтимоий ходимга муваффақиятли юборилди! 📨'));
      haptic('success');
      if (data.appeal) {
        state.appeals.unshift(data.appeal);
        renderAppealsList();
        switchTab('appeals');
      }
    } else {
      const errMsg = (data && data.message) ? data.message : "Мурожаат юборишда хатолик юз берди";
      showToast("❌ " + errMsg);
      haptic('error');
    }
  } catch (e) {
    showToast("❌ Сервер билан алоқада хатолик");
    haptic('error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = (state.lang === 'ru') ? "Отправить обращение" : "Мурожаатни юбориш";
    }
  }
}

function renderAppealsList() {
  const container = document.getElementById('appealsListContainer');
  if (!container) return;

  const lang = state.lang || 'uz_cyr';

  if (state.appeals.length === 0) {
    const emptyMsg = (lang === 'ru') ? 'У вас пока нет отправленных официальных обращений.' : 'Ҳозирча юборилган расмий мурожаатларингиз мавжуд эмас.';
    const emptyBtn = (lang === 'ru') ? 'Отправить обращение' : 'Янги мурожаат йўллаш';
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📭</div>
        <p>${emptyMsg}</p>
        <button class="btn-outline" onclick="openAppealModal()">${emptyBtn}</button>
      </div>
    `;
    return;
  }

  container.innerHTML = state.appeals.map(a => {
    let statusClass = 'badge-new';
    const st = String(a.status || '');
    if (st.includes('O\'rganilmoqda') || st.includes('Ўрганилмоқда') || st.includes('Jarayonda') || st.includes('процессе')) statusClass = 'badge-in-progress';
    if (st.includes('Hal etildi') || st.includes('Ҳал этилди') || st.includes('Qanoatlantirildi') || st.includes('Удовлетворено')) statusClass = 'badge-done';
    if (st.includes('Rad etildi') || st.includes('Рад этилди') || st.includes('Отклонено')) statusClass = 'badge-rejected';

    const canRate = (statusClass === 'badge-done' && !a.rating);
    const rateBtnText = lang === 'ru' ? '⭐ Оценить' : '⭐ Баҳолаш';
    const ratedText = lang === 'ru' ? 'Оценка:' : 'Баҳоланган:';
    const urgentTag = lang === 'ru' ? '🚨 Срочно' : '🚨 Шошилинч';

    const safeCat = escapeHtml(a.category);
    const safeText = escapeHtml(a.text);
    const safeDate = escapeHtml(a.created_at || 'Яқинда');
    const safeId = escapeHtml(a.id);
    const safeStatus = escapeHtml(a.status);
    const ratingNum = Math.max(1, Math.min(5, parseInt(a.rating) || 5));

    return `
      <div class="appeal-item-card">
        <div class="appeal-item-header">
          <span class="appeal-cat">${safeCat}</span>
          <span class="status-badge ${statusClass}">${safeStatus}</span>
        </div>
        <p class="appeal-text">${safeText}</p>
        ${a.admin_response ? `
          <div class="appeal-admin-reply" style="margin-top: 10px; padding: 10px; background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; border-radius: 6px;">
            <div style="font-size: 12px; font-weight: 600; color: #10b981; margin-bottom: 4px;">👨‍💼 ${lang === 'ru' ? 'Ответ соцработника (А. Жўраев):' : 'Ижтимоий ходим (А. Жўраев) жавоби:'}</div>
            <div style="font-size: 13px; color: var(--text-color);">${escapeHtml(a.admin_response)}</div>
          </div>
        ` : ''}
        <div class="appeal-footer">
          <span class="appeal-date">📅 ${safeDate}</span>
          ${a.priority === 'SHOSHILINCH' ? `<span class="priority-tag red">${urgentTag}</span>` : ''}
          ${canRate ? `<button class="btn-rate-mini" data-id="${safeId}" onclick="openRatingModal(this.getAttribute('data-id'))">${rateBtnText}</button>` : ''}
          ${a.rating ? `<span class="rating-given">${ratedText} ${'⭐'.repeat(ratingNum)}</span>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

// --- SHAXSNI TEZKOR TASDIQLASH (O'RQ-547 NO PHOTOS) ---
function openVerifyModal() {
  haptic('light');
  if (state.user.fio) document.getElementById('vFio').value = state.user.fio;
  if (state.user.phone) document.getElementById('vPhone').value = state.user.phone;
  if (state.user.address) document.getElementById('vAddress').value = state.user.address;
  openModal('verifyModal');
}

async function submitVerification() {
  const fio = document.getElementById('vFio').value.trim();
  const phone = document.getElementById('vPhone').value.trim();
  const doc = document.getElementById('vDoc').value.trim();
  const address = document.getElementById('vAddress').value.trim();

  if (!fio || !phone || !address) {
    showToast(state.lang === 'ru' ? 'Пожалуйста, введите имя, телефон и адрес!' : 'Илтимос, исм, телефон ва манзилни тўлиқ киритинг!');
    return;
  }

  haptic('medium');

  const payload = {
    fio: fio,
    phone: phone,
    passport_or_jshshir: doc,
    address: address
  };

  try {
    const res = await fetch('/api/verify', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (res.ok && data.status === 'ok') {
      closeModal('verifyModal');
      if (data.already_verified) {
        showToast(data.message);
        return;
      }
      state.user.is_verified = false;
      state.user.status = 'Kutmoqda';
      state.user.fio = fio;
      state.user.phone = phone;
      state.user.address = address;
      updateVerificationBadge(false, 'Kutmoqda');
      showToast(state.lang === 'ru' ? 'Ваши данные отправлены на проверку ⏳' : 'Маълумотларингиз админга юборилди! Тасдиқланиши кутилмоқда ⏳');
      haptic('success');
    } else {
      // Xato bo'lsa oyna ochiq qoladi: fuqaro kiritganini qayta yozmasdan tuzatadi
      showToast("❌ " + (data.message || 'Хатолик юз берди'));
      haptic('error');
    }
  } catch (e) {
    closeModal('verifyModal');
    showToast("❌ Сервер билан алоқада хатолик");
    haptic('error');
  }
}

// --- CSAT RATING MODAL ---
function openRatingModal(appealId) {
  haptic('light');
  state.ratingAppealId = appealId;
  openModal('ratingModal');
}

async function submitRating(stars) {
  haptic('success');
  closeModal('ratingModal');

  if (!state.ratingAppealId) return;

  try {
    const res = await fetch('/api/rate', {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        appeal_id: state.ratingAppealId,
        score: stars
      })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      const app = state.appeals.find(a => String(a.id) === String(state.ratingAppealId));
      if (app) app.rating = stars;
      renderAppealsList();
      showToast(t('rate_thank_toast', 'Баҳо берганингиз учун ташаккур! ⭐'));
      haptic('success');
    } else {
      showToast("❌ " + (data.message || 'Баҳолашда хатолик'));
    }
  } catch (e) {
    showToast("❌ Сервер билан алоқада хатолик");
  }

  const lang = state.lang || 'uz_cyr';
  let thanksMsg = `Rahmat! Xizmat ${stars} yulduz bilan baholandi ⭐`;
  if (lang === 'uz_cyr') thanksMsg = `Раҳмат! Хизмат ${stars} юлдуз билан баҳоланди ⭐`;
  if (lang === 'ru') thanksMsg = `Спасибо! Оценка: ${stars} звезд ⭐`;
  showToast(thanksMsg);
}

// --- MODAL UTILS ---
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.add('open');
  }
}

function closeModal(id) {
  haptic('selection');
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.remove('open');
  }
}

function openContactsModal() {
  haptic('light');
  openModal('contactsModal');
}

// --- TOAST NOTIFICATIONS ---
let toastTimer = null;
function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;

  t.textContent = msg;
  t.classList.add('show');

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove('show');
  }, 3200);
}
