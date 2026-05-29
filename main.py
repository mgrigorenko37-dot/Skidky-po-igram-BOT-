import time
import threading
import logging
import sqlite3
import sys
import requests
import json
from datetime import datetime, timedelta
from telebot import types

# Импортируем настройки и базу
import config
import database
import utils
# 🔥 ДОБАВЛЕН ИМПОРТ start_backup_task
from bot_init import bot, start_backup_task 

# Импортируем системные модули
import menu_system
import games_system


# ==========================================
# 🛠 НАСТРОЙКА ЛОГОВ И КОДИРОВКИ
# ==========================================
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# 🔄 ФОНОВЫЕ ЗАДАЧИ
# ==========================================
def start_all_background_services():
    print("🔄 Запуск фоновых служб...")

    # 1. RSS Новости и Халява
    try:
        games_system.start_background_tasks()
    except Exception as e:
        logger.error(f"Error starting games RSS: {e}")

    # 2. 🔥 Авто-бэкап базы данных
    try:
        start_backup_task()
    except Exception as e:
        logger.error(f"Error starting DB backup task: {e}")


# ==========================================
# 👋 START
# ==========================================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.chat.id

    # 🔥 ОБНОВЛЯЕМ АКТИВНОСТЬ ДЛЯ DAU
    database.update_user_activity(user_id)

    args = message.text.split() if message.text else []
    referrer_id = None

    if len(args) > 1 and 'ref' in args[1]:
        try:
            possible_ref_id = int(args[1].replace('ref', ''))
            if possible_ref_id != user_id:
                referrer_id = possible_ref_id
        except ValueError:
            pass

    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT user_id FROM mining_users WHERE user_id = ?", (user_id,))
            existing_user = cursor.fetchone()

            if not existing_user:
                reg_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("""
                    INSERT INTO mining_users 
                    (user_id, reg_date, balance_usdt, bonus_balance, referrer_id) 
                    VALUES (?, ?, 0.0, 0.0, ?)
                """, (user_id, reg_date, referrer_id))
                conn.commit()

                if referrer_id:
                    utils.safe_send_message(referrer_id, f"🎉 **Новый партнер!**\nКто-то зарегистрировался по вашей ссылке.", parse_mode='Markdown')
                    logger.info(f"New Referral: {user_id} invited by {referrer_id}")

            # 🔥 ОБНОВЛЕННЫЙ ТЕКСТ ПРИВЕТСТВИЯ 🔥
            text = (
                "👋 Привет, геймер!\n\n"
                "Я Game Broker — твой личный поисковик выгодных цен.\n"
                "Больше не нужно мониторить десятки сайтов — я сделаю это за тебя.\n\n"
                "🎮 **БАЗОВАЯ ВЕРСИЯ (Бесплатно):**\n"
                "• Поиск минимальных цен на игры (Steam, EGS и др.).\n"
                "• Базовый шорт-лист (отслеживание до 5 игр).\n"
                "• Топ скидок на сегодня.\n\n"
                "💎 **VIP ВЕРСИЯ (Подписка):**\n"
                "• Элитные раздачи AAA-игр прямо в ЛС.\n"
                "• Безлимитный шорт-лист (до 100 игр).\n"
                "• Полное отключение рекламы (Ad-Free).\n\n"
                "Жми «🔎 Поиск игры» или просто отправь сообщение боту с названием игры!"
            )

            utils.safe_send_message(user_id, text, reply_markup=utils.main_kbrd(user_id))

    except Exception as e:
        logger.error(f"Start Error: {e}")

# ==========================================
# ⭐️ VIP ПОДПИСКА (ОПЛАТА ЗВЕЗДАМИ + АВТОПРОДЛЕНИЕ)
# ==========================================

def get_auto_renew_status(user_id):
    """Вспомогательная функция: получает статус автопродления (1 или 0)"""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            row = conn.execute("SELECT auto_renew FROM user_news_prefs WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else 0
    except: return 0

def send_vip_invoice(chat_id, is_subscription=False):
    """Отправляет счет. Если is_subscription=True, добавляет параметр автопродления"""
    # 2592000 секунд = 30 дней
    sub_period = 2592000 if is_subscription else None

    label_text = "VIP Подписка (Авто)" if is_subscription else "VIP Радар (30 дней)"
    desc = "Элитные раздачи топовых игр, безлимитный шорт-лист и полное отключение рекламы.\n\n"
    if is_subscription:
        desc += "🔄 Включено автопродление каждые 30 дней."
    else:
        desc += "Подписка на 30 дней."

    # 🔥 ИСПРАВЛЕНИЕ: ПРЯМОЙ ЗАПРОС К API TELEGRAM ДЛЯ ОБХОДА УСТАРЕВШЕГО TELEBOT
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendInvoice"

        payload = {
            "chat_id": chat_id,
            "title": "VIP Статус ⭐️",
            "description": desc,
            "payload": "vip_sub_30",
            "provider_token": "", # Пусто для Stars
            "currency": "XTR",
            "prices": json.dumps([{"label": label_text, "amount": 100}]) # 100 звезд
        }

        # Если включено автопродление, добавляем параметр
        if is_subscription:
            payload["subscription_period"] = sub_period

        response = requests.post(url, data=payload)

        if not response.json().get('ok'):
            logger.error(f"API Invoice Error: {response.text}")
            utils.safe_send_message(chat_id, "❌ Не удалось создать счет. Попробуйте позже.")

    except Exception as e:
        logger.error(f"Invoice Request Error: {e}")
        utils.safe_send_message(chat_id, "❌ Ошибка соединения при создании счета.")


@bot.message_handler(func=lambda message: message.text in ["⭐️ VIP Подписка", "VIP Подписка"])
def handle_premium_button(message):
    database.update_user_activity(message.chat.id)
    premium_command(message)

@bot.message_handler(commands=['premium'])
def premium_command(message):
    chat_id = message.chat.id

    is_premium = False
    days_left = 0
    premium_until_str = ""

    with sqlite3.connect(config.DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row and row[0]:
            try:
                premium_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                if premium_until > datetime.utcnow():
                    is_premium = True
                    days_left = (premium_until - datetime.utcnow()).days
                    premium_until_str = premium_until.strftime('%Y-%m-%d %H:%M (UTC)')
            except: pass

    auto_renew = get_auto_renew_status(chat_id)

    mk = types.InlineKeyboardMarkup(row_width=1)

    if is_premium:
        auto_text = "♾ Включено" if auto_renew else "⏹ Выключено"
        text = (
            f"💎 **Твоя VIP-подписка активна!**\n\n"
            f"⏳ Осталось дней: **{days_left}**\n"
            f"📅 Действует до: `{premium_until_str}`\n"
            f"⚙️ Автопродление: **{auto_text}**\n\n"
            f"Бот продолжит присылать элитные раздачи игр тебе в личные сообщения и давать доступ к безлимитному шорт-листу."
        )

        toggle_label = "🔴 Выключить автопродление" if auto_renew else "🟢 Включить автопродление"
        mk.add(types.InlineKeyboardButton(toggle_label, callback_data="toggle_auto"))
        mk.add(types.InlineKeyboardButton("💎 Продлить (100 ⭐)", callback_data="buy_vip"))

        utils.safe_send_message(chat_id, text, parse_mode='Markdown', reply_markup=mk)
    else:
        auto_text = "♾ Включено" if auto_renew else "⏹ Выключено"
        # 🔥 ОБНОВЛЕННЫЙ ПРОДАЮЩИЙ ТЕКСТ 🔥
        text = (
            f"⭐️ **VIP Статус — Инструмент для тех, кто ценит выгоду!**\n\n"
            f"Заставь бота работать на себя и сэкономь тысячи рублей на покупке игр:\n\n"
            f"🎁 **Радар Элитной Халявы:**\n"
            f"Не трать время на мониторинг сайтов. Я сам отслежу раздачи в Steam, Epic Games и GOG. Как только топовая AAA-игра или крутое инди станут бесплатными — ты получишь пуш-уведомление прямо в ЛС. Никакого мусора, только хиты!\n\n"
            f"♾ **Безлимитный Шорт-лист (Твой Снайпер Цен):**\n"
            f"В бесплатной версии ты можешь отслеживать только 5 игр. С VIP-статусом у тебя **полный безлимит**. Добавь хоть весь магазин в шорт-лист, и я моментально сообщу тебе, как только цена на желанную игру упадет. Скупай игры на распродажах по лучшей цене!\n\n"
            f"🚫 **Ad-Free (Кристально чистый интерфейс):**\n"
            f"Устал от рекламы? VIP-пользователи получают абсолютный комфорт. Полное отключение любых рекламных, спонсорских и партнерских рассылок от администрации.\n\n"
            f"⚙️ **Автопродление:** {auto_text}\n"
            f"_(Включи, чтобы не потерять доступ к радару — бот будет автоматически продлевать подписку каждый месяц)_"
        )

        toggle_label = "🔴 Выключить автопродление" if auto_renew else "🟢 Включить автопродление"
        mk.add(types.InlineKeyboardButton(toggle_label, callback_data="toggle_auto"))
        mk.add(types.InlineKeyboardButton("💳 Оформить подписку (100 ⭐)", callback_data="buy_vip"))

        utils.safe_send_message(chat_id, text, parse_mode='Markdown', reply_markup=mk)


@bot.callback_query_handler(func=lambda c: c.data == "toggle_auto")
def handle_toggle_auto(c):
    user_id = c.message.chat.id
    database.update_user_activity(user_id)
    current_status = get_auto_renew_status(user_id)
    new_status = 1 if current_status == 0 else 0

    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("UPDATE user_news_prefs SET auto_renew = ? WHERE user_id = ?", (new_status, user_id))
            conn.commit()

        bot.answer_callback_query(c.id, "Настройка сохранена")
        # Удаляем старое сообщение и вызываем команду заново, чтобы перерисовать меню
        try: bot.delete_message(user_id, c.message.message_id)
        except: pass
        premium_command(c.message)
    except Exception as e:
        logger.error(f"Toggle error: {e}")
        bot.answer_callback_query(c.id, "⚠️ Ошибка обновления.")


@bot.callback_query_handler(func=lambda c: c.data == "buy_vip")
def handle_buy_vip(c):
    database.update_user_activity(c.message.chat.id)
    bot.answer_callback_query(c.id)
    auto_renew = get_auto_renew_status(c.message.chat.id)
    send_vip_invoice(c.message.chat.id, is_subscription=bool(auto_renew))


# Подтверждение готовности принять платеж
@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True, error_message="Произошла ошибка, попробуйте еще раз.")

# Обработка успешного платежа
@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload = message.successful_payment.invoice_payload
    chat_id = message.chat.id

    if payload == "vip_sub_30":
        try:
            with sqlite3.connect(config.DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (chat_id,))
                row = cursor.fetchone()

                current_time = datetime.utcnow()
                new_until = current_time + timedelta(days=30)

                # Если у юзера уже есть подписка, прибавляем к ней 30 дней
                if row and row[0]:
                    try:
                        old_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                        if old_until > current_time:
                            new_until = old_until + timedelta(days=30)
                    except: pass

                new_date_str = new_until.strftime('%Y-%m-%d %H:%M:%S')

                if row:
                    cursor.execute("UPDATE user_news_prefs SET premium_until = ?, want_freebies = 1 WHERE user_id = ?", (new_date_str, chat_id))
                else:
                    cursor.execute("INSERT INTO user_news_prefs (user_id, premium_until, want_freebies) VALUES (?, ?, 1)", (chat_id, new_date_str))
                conn.commit()

                success_text = f"🎉 **Ура! Оплата прошла успешно.**\n\nТвоя подписка на VIP Радар активна до: `{new_date_str} (UTC)`."
                utils.safe_send_message(chat_id, success_text, parse_mode='Markdown')
                logger.info(f"User {chat_id} bought VIP until {new_date_str}")

        except Exception as e:
            logger.error(f"Payment update error: {e}")
            utils.safe_send_message(chat_id, "⚠️ Оплата прошла, но возникла техническая заминка. Пожалуйста, напишите администратору.")

# ==========================================
# 👑 АДМИНСКАЯ КОМАНДА: ВЫДАТЬ VIP
# ==========================================
@bot.message_handler(commands=['give_vip'])
def give_vip_command(message):
    if str(message.chat.id) != str(config.ADMIN_ID): 
        return # Защита: только админ может использовать эту команду

    args = message.text.split()

    if len(args) != 3:
        utils.safe_send_message(message.chat.id, "❌ Формат команды: `/give_vip [user_id] [количество_дней]`\nПример: `/give_vip 123456789 30`", parse_mode='Markdown')
        return

    try:
        target_user_id = int(args[1])
        days_to_add = int(args[2])

        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (target_user_id,))
            row = cursor.fetchone()

            current_time = datetime.utcnow()
            new_until = current_time + timedelta(days=days_to_add)

            # Если у юзера уже есть подписка, прибавляем к ней дни
            if row and row[0]:
                try:
                    old_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                    if old_until > current_time:
                        new_until = old_until + timedelta(days=days_to_add)
                except: pass

            new_date_str = new_until.strftime('%Y-%m-%d %H:%M:%S')

            if row:
                cursor.execute("UPDATE user_news_prefs SET premium_until = ?, want_freebies = 1 WHERE user_id = ?", (new_date_str, target_user_id))
            else:
                cursor.execute("INSERT INTO user_news_prefs (user_id, premium_until, want_freebies) VALUES (?, ?, 1)", (target_user_id, new_date_str))
            conn.commit()

            utils.safe_send_message(message.chat.id, f"✅ Успешно! Пользователю `{target_user_id}` выдана VIP подписка до `{new_date_str}` (UTC).", parse_mode='Markdown')
            utils.safe_send_message(target_user_id, f"🎁 **Администратор выдал вам VIP-подписку!**\nОна активна до: `{new_date_str} (UTC)`.\n\nСпасибо, что вы с нами! ❤️", parse_mode='Markdown')

    except ValueError:
        utils.safe_send_message(message.chat.id, "❌ Ошибка: ID пользователя и количество дней должны быть числами.")
    except Exception as e:
        logger.error(f"Give VIP error: {e}")
        utils.safe_send_message(message.chat.id, f"❌ Ошибка при выдаче VIP: {e}")

# ==========================================
# 🔥 НОВОЕ: РУЧНОЙ ПОСТ В КАНАЛ (АДМИН)
# ==========================================
def process_channel_post(message):
    """Функция обработки сообщения от админа для отправки в канал"""
    if str(message.chat.id) != str(config.ADMIN_ID): return
    if message.text and message.text == "❌ Отмена":
        utils.safe_send_message(message.chat.id, "✅ Публикация отменена.", reply_markup=utils.main_kbrd(message.chat.id))
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
        return

    try:
        # bot.copy_message пересылает ЛЮБОЙ тип сообщения без пометки "Переслано от"
        bot.copy_message(chat_id=config.CHANNEL_ID, from_chat_id=message.chat.id, message_id=message.message_id)
        utils.safe_send_message(message.chat.id, "✅ **Успешно опубликовано в канале!**", parse_mode='Markdown', reply_markup=utils.main_kbrd(message.chat.id))
    except Exception as e:
        logger.error(f"Post to channel error: {e}")
        utils.safe_send_message(message.chat.id, f"❌ Ошибка публикации: {e}", reply_markup=utils.main_kbrd(message.chat.id))

@bot.message_handler(commands=['post'])
@bot.message_handler(func=lambda message: message.text == "📝 Пост в канал")
def post_to_channel_command(message):
    if str(message.chat.id) != str(config.ADMIN_ID): 
        return # Защита: только админ

    cancel_km = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_km.add("❌ Отмена")

    msg = utils.safe_send_message(
        message.chat.id, 
        "📢 **Создание поста в канал**\n\nОтправь мне то, что нужно опубликовать (текст, фото с описанием, видео или гифку).", 
        parse_mode='Markdown', 
        reply_markup=cancel_km
    )
    bot.register_next_step_handler(msg, process_channel_post)


# ==========================================
# 📊 ОБНОВЛЕННАЯ СТАТИСТИКА ДЛЯ GAME BROKER
# ==========================================
@bot.message_handler(commands=['stats'])
@bot.message_handler(regexp=r"(?i).*статистика.*") # 🔥 ДОБАВЛЕН ПЕРЕХВАТ КНОПКИ
def admin_stats_command(message):
    if str(message.chat.id) != str(config.ADMIN_ID): return

    try:
        bot.send_chat_action(message.chat.id, 'typing')

        stats = database.get_comprehensive_stats()

        if not stats:
            bot.send_message(message.chat.id, "❌ Ошибка получения данных БД.")
            return

        dau_percent = (stats['dau'] / stats['total_users'] * 100) if stats['total_users'] > 0 else 0.0
        ad_status = "🟢 Активна" if stats['ad_active'] else "🔴 Нет рекламы"

        text = (
            f"📊 **СТАТИСТИКА GAME BROKER** | `{datetime.utcnow().strftime('%H:%M')} UTC`\n"
            f"➖➖➖➖➖➖➖➖➖➖\n"
            f"👥 **АУДИТОРИЯ**\n"
            f"• Всего юзеров: **{stats['total_users']}**\n"
            f"• DAU (Активны за 24ч): **{stats['dau']}** ({dau_percent:.1f}%)\n"
            f"• Новых сегодня: **+{stats['new_today']}**\n\n"

            f"🎯 **ВОВЛЕЧЕННОСТЬ**\n"
            f"• Игр в шорт-листах: **{stats['total_wishlist_items']}**\n"
            f"• Юзеров с шорт-листами: **{stats['unique_wishlist_users']}**\n"
            f"• Рассылок (новости/халява): **{stats['sent_news_count']}**\n\n"

            f"💎 **МОНЕТИЗАЦИЯ**\n"
            f"• Активных VIP-подписок: **{stats['active_vips']}**\n\n"

            f"📢 **РЕКЛАМНАЯ КАМПАНИЯ**\n"
            f"• Статус: **{ad_status}**\n"
            f"• Показов (Views): **{stats['ad_views']}**\n"
            f"• Истекает: `{stats['ad_expires']}`"
        )

        bot.send_message(message.chat.id, text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Stats Error: {e}")
        bot.send_message(message.chat.id, f"❌ Error: {e}")

# ==========================================
# 🔄 МЕНЮ
# ==========================================
@bot.message_handler(commands=['menu'])
def force_menu(message):
    database.update_user_activity(message.chat.id)
    msg = utils.safe_send_message(message.chat.id, "🔄", reply_markup=types.ReplyKeyboardRemove())
    try:
        if msg: bot.delete_message(message.chat.id, msg.message_id)
    except: pass
    utils.safe_send_message(message.chat.id, "🗄 **Меню восстановлено!**", reply_markup=utils.main_kbrd(message.chat.id))

# ==========================================
# 🚀 ЗАПУСК
# ==========================================
if __name__ == "__main__":
    database.init_db()

    # 🔥 НОВОЕ: ГАРАНТИРОВАННОЕ СОЗДАНИЕ КОЛОНКИ ПРИ СТАРТЕ СКРИПТА
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("ALTER TABLE user_news_prefs ADD COLUMN auto_renew INTEGER DEFAULT 0")
            conn.commit()
            print("✅ Колонка auto_renew добавлена в базу данных.")
    except sqlite3.OperationalError:
        pass # Игнорируем ошибку, если колонка уже существует

    menu_system.register_handlers(bot)
    games_system.register_handlers(bot) 
    start_all_background_services()

    print("🚀 Бот запущен!")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot Polling Error: {e}")
            time.sleep(5)