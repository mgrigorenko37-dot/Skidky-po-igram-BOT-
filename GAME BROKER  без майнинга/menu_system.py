import sqlite3
import logging
import time
import threading
from telebot import types
import config
import utils
import database
import games_system  # ✅ Оставляем только систему игр
from datetime import datetime # 🔥 ДОБАВЛЕНО ДЛЯ ПРОВЕРКИ VIP
from bot_init import bot # 🔥 ДОБАВЛЕНО ДЛЯ РАБОТЫ REGISTER_NEXT_STEP_HANDLER

logger = logging.getLogger(__name__)

# ==========================================
# ⚙️ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def get_user_stores(user_id):
    """
    Возвращает список ID магазинов, выбранных пользователем.
    """
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            rows = conn.execute("SELECT store_id FROM user_stores WHERE user_id = ?", (user_id,)).fetchall()

            if not rows: 
                return list(config.SUPPORTED_STORES.keys())

            if len(rows) == 1 and str(rows[0][0]) == '-1':
                return []

            return [str(r[0]) for r in rows]
    except: 
        return list(config.SUPPORTED_STORES.keys())

def settings_kbrd(user_id):
    with sqlite3.connect(config.DB_FILE) as conn:
        try:
            row = conn.execute("SELECT want_news, want_freebies, currency FROM user_news_prefs WHERE user_id = ?", (user_id,)).fetchone()
            n, f, curr = (row[0], row[1], row[2]) if row else (1, 1, 'USD')
        except: n, f, curr = (1, 1, 'USD')
    mk = types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        types.InlineKeyboardButton(f"{'✅' if n else '❌'} Игровые новости", callback_data="tgl_news"),
        types.InlineKeyboardButton(f"{'✅' if f else '❌'} Уведомления о халяве", callback_data="tgl_freebies"),
        types.InlineKeyboardButton(f"💱 Валюта: {curr}", callback_data="change_currency"),
        types.InlineKeyboardButton("🏬 Магазины (Фильтр)", callback_data="manage_stores_0")
    )
    return mk

def currency_kbrd():
    mk = types.InlineKeyboardMarkup(row_width=3)
    btns = [types.InlineKeyboardButton(f"{c} {s}", callback_data=f"set_curr_{c}") for c, s in config.CURRENCY_SIGNS.items()]
    mk.add(*btns)
    mk.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings"))
    return mk

# --- ОБРАБОТКА ПОИСКА ИГРЫ ---
def process_search_step(message):
    """Шаг 2: Получаем название игры от пользователя и ищем"""
    if not message.text or message.text in ["❌ Отмена", "/start"]:
        utils.safe_send_message(message.chat.id, "🔎 Поиск отменен.", reply_markup=utils.main_kbrd(message.chat.id))
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id) # Очищаем состояние
        return

    try:
        games_system.search_game(message.chat.id, message.text)
        utils.safe_send_message(message.chat.id, "✅", reply_markup=utils.main_kbrd(message.chat.id)) # Возвращаем обычную клаву
    except Exception as e:
        logger.error(f"Search Error: {e}")
        utils.safe_send_message(message.chat.id, "⚠️ Ошибка поиска.", reply_markup=utils.main_kbrd(message.chat.id))

# ==========================================
# 🔥 МАСТЕР НАСТРОЙКИ ВСТРОЕННОЙ РЕКЛАМЫ (АДМИН)
# ==========================================

def process_ad_days(message, ad_text):
    if message.text == "❌ Отмена":
        utils.safe_send_message(message.chat.id, "Отменено.", reply_markup=utils.main_kbrd(message.chat.id))
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
        return

    try:
        days = int(message.text)
        if days <= 0: raise ValueError

        database.set_active_ad(ad_text, days)
        utils.safe_send_message(message.chat.id, f"✅ **Реклама успешно запущена на {days} дней!**\nТеперь она будет показываться обычным игрокам под результатами поиска и скидками.", parse_mode='Markdown', reply_markup=utils.main_kbrd(message.chat.id))
    except ValueError:
        msg = utils.safe_send_message(message.chat.id, "❌ Пожалуйста, введите только число (например: 7). Попробуйте еще раз:")
        bot.register_next_step_handler(msg, process_ad_days, ad_text)

def process_ad_text(message):
    if message.text == "❌ Отмена":
        utils.safe_send_message(message.chat.id, "Отменено.", reply_markup=utils.main_kbrd(message.chat.id))
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
        return

    ad_text = message.text

    cancel_km = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_km.add("❌ Отмена")

    msg = utils.safe_send_message(message.chat.id, "⏳ На сколько дней запускаем рекламу? (Напишите просто число, например: 7)", reply_markup=cancel_km)
    bot.register_next_step_handler(msg, process_ad_days, ad_text)


# ==========================================
# 🎮 ХЕНДЛЕРЫ МЕНЮ (ПОИСКОВИК)
# ==========================================

def register_handlers(bot_instance):
    # Используем глобальный bot для декораторов, а не переданный bot_instance,
    # чтобы избежать путаницы с областями видимости

    # --- 🔥 1. О БОТЕ (ИСПРАВЛЕНО: КОНФЛИКТ С ДОНАТОМ УБРАН) ---
    @bot.message_handler(func=lambda m: m.text in ["ℹ️ О боте", "ℹ️ О проекте", "О боте", "📜 Правила"]) 
    @bot.message_handler(func=lambda m: "проект" in m.text.lower() and "поддержать" not in m.text.lower())
    @bot.message_handler(regexp=r"(?i).*(о боте|about|правила).*")
    def about_project_handler(m):
        text = (
            "🚀 **GAME BROKER: О БОТЕ** 🌌\n\n"
            "Привет! Я — продвинутый поисковый бот. Я помогаю геймерам находить любимые игры по самым низким ценам.\n\n"
            "💎 **ЧТО Я УМЕЮ?**\n"
            "🔎 **Глобальный Поиск:**\n"
            "Я сканирую цены в Steam, Epic Games, (GGsel, Eneba и др.). Ты увидишь все варианты в одном месте.\n\n"
            "📉 **Сравнение Цен:**\n"
            "Зачем платить $60, если в соседнем магазине скидка 90%? Я покажу, где дешевле.\n\n"
            "🎁 **Радар Халявы:**\n"
            "Как только EGS, Steam и другие начинают раздавать игры бесплатно — я пришлю уведомление.\n\n"
            "📋 **Умный Вишлист:**\n"
            "Нашел крутую игру, но дорого? Добавь её в «Шорт-лист». Это твой личный список желаемого.\n\n"
            "➖➖➖➖➖➖➖\n"
            "🕹 **КАК ПОЛЬЗОВАТЬСЯ?**\n"
            "1️⃣ Жми **«🔎 Поиск игры»** в меню.\n"
            "2️⃣ Пиши название (например: *GTA V*).\n"
            "3️⃣ Выбирай лучшее предложение!\n\n"
            "💸 *Хватит переплачивать! Покупай с умом.*"
        )
        utils.safe_send_message(m.chat.id, text, parse_mode='Markdown')

    # --- 🔎 2. ПОИСК ИГРЫ ---
    @bot.message_handler(func=lambda m: m.text and ("Поиск игры" in m.text or "Отследить игру" in m.text or "🔎" in m.text))
    def menu_search_game(m):
        cancel_kbrd = types.ReplyKeyboardMarkup(resize_keyboard=True)
        cancel_kbrd.add("❌ Отмена")

        msg = utils.safe_send_message(m.chat.id, "🔎 **Напишите название игры:**\n\n(Я найду цены в Steam, EGS и других магазинах )", parse_mode='Markdown', reply_markup=cancel_kbrd)
        bot.register_next_step_handler(msg, process_search_step)

    # --- 🔥 3. ТОП СКИДОК ---
    @bot.message_handler(func=lambda m: m.text and any(x in m.text for x in ["Скидки", "Discounts", "Deals", "🔥"]))
    def menu_discounts(m):
        games_system.show_top_deals(m.chat.id)

    # --- 🎭 4. ЖАНРЫ ---
    @bot.message_handler(func=lambda m: m.text and any(x in m.text for x in ["Жанры", "Genres", "Категории", "🎭"]))
    def menu_genres(m):
        mk = types.InlineKeyboardMarkup(row_width=2)
        btns = [types.InlineKeyboardButton(k, callback_data=f"genre_{k}_0") for k in games_system.STEAM_TAGS.keys()]
        mk.add(*btns)
        utils.safe_send_message(m.chat.id, "🎯 **Выберите категорию:**", parse_mode='Markdown', reply_markup=mk)

    # --- 📋 5. ВИШЛИСТ ---
    @bot.message_handler(func=lambda m: m.text and "Шорт-лист" in m.text)
    def menu_wishlist(m):
        games_system.show_my_wishlist(m.chat.id, m.from_user.id)

    # --- ⚙️ 6. НАСТРОЙКИ ---
    @bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
    @bot.message_handler(regexp=r"(?i).*настройки.*")
    def settings_menu(m):
        utils.safe_send_message(m.chat.id, "⚙️ **Настройки бота:**", parse_mode='Markdown', reply_markup=settings_kbrd(m.chat.id))

    # --- 🤝 7. ПАРТНЕРКА (Инфо) ---
    @bot.message_handler(func=lambda m: m.text == "🤝 Партнерка")
    @bot.message_handler(regexp=r"(?i).*партнерка.*")
    def referral_menu(m):
        bot_username = utils.get_bot_username(m)
        ref_link = f"https://t.me/{bot_username}?start=ref{m.chat.id}"
        text = (
            "🤝 **ПАРТНЕРСКАЯ ПРОГРАММА**\n\n"
            "Понравился бот? Поделись с друзьями!\n\n"
            "🔗 **Твоя ссылка:**\n"
            f"`{ref_link}`\n\n"
            "Чем больше нас, тем быстрее мы развиваемся! ❤️"
        )
        utils.safe_send_message(m.chat.id, text, parse_mode='Markdown')

    # --- 💬 8. СООБЩЕСТВО ---
    @bot.message_handler(func=lambda m: m.text == "💬 Сообщество")
    @bot.message_handler(regexp=r"(?i).*сообщество.*")
    def community(m):
        url = f"https://t.me/{config.CHANNEL_ID.replace('@', '')}"
        mk = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✈️ Перейти в канал", url=url))
        utils.safe_send_message(m.chat.id, "🌐 **GAME BROKER COMMUNITY**\n\n"
                                "Хочешь ловить халяву быстрее всех? Залетай в наш канал! 👇\n\n"
                                "🔥 Горячие раздачи — узнавай о бесплатных играх первым.\n"
                                "⚡ Баги цен — успевай покупать хиты за копейки, пока магазины не заметили.\n"
                                "📰 Инсайды — только важные новости игровой индустрии без спама.\n\n"
                                "🚀 Жми кнопку ниже и будь в теме!", reply_markup=mk)

    # --- ⭐ 9. ПОДДЕРЖКА (ОБНОВЛЕНО: МЕНЮ ВЫБОРА) ---
    @bot.message_handler(func=lambda m: m.text == "⭐ Поддержать проект")
    def donate_menu(m):
        mk = types.InlineKeyboardMarkup(row_width=2)
        # Кнопки с разным количеством звезд
        btns = [
            types.InlineKeyboardButton("⭐ 50", callback_data="pay_stars_50"),
            types.InlineKeyboardButton("⭐ 100", callback_data="pay_stars_100"),
            types.InlineKeyboardButton("⭐ 250", callback_data="pay_stars_250"),
            types.InlineKeyboardButton("⭐ 500", callback_data="pay_stars_500")
        ]
        mk.add(*btns)
        utils.safe_send_message(m.chat.id, "🙏 **Выберите сумму поддержки:**\n\nВаши звезды помогут оплачивать серверы и развивать бота! ❤️", parse_mode='Markdown', reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("pay_stars_"))
    def send_donation_invoice(c):
        try:
            amount = int(c.data.split('_')[2])
            prices = [types.LabeledPrice(label=f"Донат {amount} ⭐", amount=amount)]

            bot.send_invoice(
                c.message.chat.id,
                title="Поддержать Game Broker",
                description=f"Пожертвование {amount} звезд на развитие.",
                invoice_payload=f"donate_{amount}",
                provider_token="",  # Для Telegram Stars токен оставляем пустым
                currency="XTR",
                prices=prices,
                start_parameter="donate_support"
            )
            bot.answer_callback_query(c.id)
        except Exception as e:
            logger.error(f"Invoice error: {e}")
            bot.answer_callback_query(c.id, "⚠️ Ошибка создания счета")

    @bot.pre_checkout_query_handler(func=lambda query: True)
    def checkout(pre_checkout_query):
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

    @bot.message_handler(content_types=['successful_payment'])
    def got_payment(message):
        # Получаем сумму из информации о платеже
        total = message.successful_payment.total_amount
        utils.safe_send_message(message.chat.id, f"⭐ **СПАСИБО!** Получено {total} звезд! Ваша поддержка бесценна! ❤️", parse_mode='Markdown')

    # --- 📢 10. АДМИНКА (УПРАВЛЕНИЕ РЕКЛАМОЙ) ---
    @bot.message_handler(regexp=r"(?i).*реклама.*")
    def admin_ads(m):
        if str(m.chat.id) != str(config.ADMIN_ID): return

        active_ad = database.get_active_ad()

        if active_ad:
            # Реклама уже есть
            text = f"📢 **Активная реклама:**\n\n_{active_ad['text']}_\n\n"
            if active_ad['expires_at']:
                # Считаем, сколько дней осталось
                delta = active_ad['expires_at'] - datetime.utcnow()
                days_left = delta.days
                if days_left < 0: days_left = 0
                text += f"⏳ **Осталось дней:** {days_left}"
            else:
                text += "⏳ **Осталось дней:** Безлимит"

            mk = types.InlineKeyboardMarkup()
            mk.add(types.InlineKeyboardButton("🛑 Отключить рекламу", callback_data="stop_ad"))
            utils.safe_send_message(m.chat.id, text, parse_mode='Markdown', reply_markup=mk)

        else:
            # Рекламы нет, предлагаем создать
            cancel_km = types.ReplyKeyboardMarkup(resize_keyboard=True)
            cancel_km.add("❌ Отмена")
            msg = bot.send_message(m.chat.id, "📢 **Настройка рекламы**\n\nВстроенная реклама не показывается VIP-пользователям.\nОтправь текст рекламного сообщения (можно с ссылками):", reply_markup=cancel_km)
            bot.register_next_step_handler(msg, process_ad_text)

    @bot.callback_query_handler(func=lambda c: c.data == "stop_ad")
    def stop_active_ad(c):
        if str(c.message.chat.id) != str(config.ADMIN_ID): return
        database.set_active_ad(None)
        bot.answer_callback_query(c.id, "Реклама отключена")
        utils.safe_edit_message_text("✅ Рекламная кампания остановлена.", c.message.chat.id, c.message.message_id)

    # --- CALLBACKS ---
    @bot.callback_query_handler(func=lambda c: c.data.startswith("tgl_"))
    def toggle_setting(c):
        col = 'want_news' if c.data == 'tgl_news' else 'want_freebies'
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("INSERT OR IGNORE INTO user_news_prefs (user_id) VALUES (?)", (c.message.chat.id,))
            conn.execute(f"UPDATE user_news_prefs SET {col} = 1 - {col} WHERE user_id = ?", (c.message.chat.id,))
            conn.commit()
        utils.safe_edit_message_text("⚙️ **Настройки:**", c.message.chat.id, c.message.message_id, parse_mode='Markdown', reply_markup=settings_kbrd(c.message.chat.id))

    @bot.callback_query_handler(func=lambda c: c.data == "change_currency")
    def h_cc(c):
        utils.safe_answer_callback(c.id)
        utils.safe_edit_message_text("💱 **Выберите валюту:**", c.message.chat.id, c.message.message_id, parse_mode='Markdown', reply_markup=currency_kbrd())

    @bot.callback_query_handler(func=lambda c: c.data.startswith("set_curr_"))
    def set_currency(c):
        curr = c.data.split('_')[2]
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("INSERT OR IGNORE INTO user_news_prefs (user_id) VALUES (?)", (c.message.chat.id,))
            conn.execute("UPDATE user_news_prefs SET currency = ? WHERE user_id = ?", (curr, c.message.chat.id))
            conn.commit()
        utils.safe_answer_callback(c.id, f"✅ Валюта изменена на {curr}")
        utils.safe_edit_message_text("⚙️ **Настройки:**", c.message.chat.id, c.message.message_id, parse_mode='Markdown', reply_markup=settings_kbrd(c.message.chat.id))

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_settings")
    def back_settings(c):
        utils.safe_answer_callback(c.id)
        utils.safe_edit_message_text("⚙️ **Настройки:**", c.message.chat.id, c.message.message_id, parse_mode='Markdown', reply_markup=settings_kbrd(c.message.chat.id))

    # --- МАГАЗИНЫ ---
    @bot.callback_query_handler(func=lambda c: c.data.startswith("manage_stores"))
    def manage_stores_menu(c):
        user_id = c.message.chat.id
        try: page = int(c.data.split('_')[2])
        except: page = 0
        ITEMS_PER_PAGE = 10
        all_stores = list(config.SUPPORTED_STORES.items())
        total_pages = (len(all_stores) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        current_stores = all_stores[start:end]
        u_s = get_user_stores(user_id)
        mk = types.InlineKeyboardMarkup(row_width=2)
        for sid, name in current_stores:
            status = "✅" if sid in u_s else "❌"
            mk.add(types.InlineKeyboardButton(f"{status} {name}", callback_data=f"st_{sid}_{page}"))
        nav_btns = []
        if page > 0: nav_btns.append(types.InlineKeyboardButton("⬅️", callback_data=f"manage_stores_{page-1}"))
        if page < total_pages - 1: nav_btns.append(types.InlineKeyboardButton("➡️", callback_data=f"manage_stores_{page+1}"))
        if nav_btns: mk.row(*nav_btns)
        mk.add(types.InlineKeyboardButton("✅ Включить все", callback_data=f"all_on_{page}"),
               types.InlineKeyboardButton("❌ Выключить все", callback_data=f"all_off_{page}"))
        mk.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_settings"))
        utils.safe_edit_message_text(f"🏬 **Магазины (Стр. {page+1}/{total_pages}):**", c.message.chat.id, c.message.message_id, parse_mode='Markdown', reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("st_"))
    def toggle_store(c):
        parts = c.data.split('_')
        store_id, page = parts[1], parts[2]
        user_id = c.message.chat.id
        current_selection = get_user_stores(user_id)
        if store_id in current_selection: current_selection.remove(store_id)
        else: current_selection.append(store_id)
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM user_stores WHERE user_id=?", (user_id,))
            all_keys = list(config.SUPPORTED_STORES.keys())
            if len(current_selection) == len(all_keys): pass
            elif not current_selection: conn.execute("INSERT INTO user_stores (user_id, store_id) VALUES (?, ?)", (user_id, "-1"))
            else:
                for s in current_selection: conn.execute("INSERT INTO user_stores (user_id, store_id) VALUES (?, ?)", (user_id, s))
            conn.commit()
        c.data = f"manage_stores_{page}"
        manage_stores_menu(c)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("all_"))
    def toggle_all_stores(c):
        parts = c.data.split('_')
        action, page = parts[1], parts[2]
        user_id = c.message.chat.id
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM user_stores WHERE user_id=?", (user_id,))
            if action == "off": conn.execute("INSERT INTO user_stores (user_id, store_id) VALUES (?, ?)", (user_id, "-1"))
            conn.commit()
        c.data = f"manage_stores_{page}"
        manage_stores_menu(c)