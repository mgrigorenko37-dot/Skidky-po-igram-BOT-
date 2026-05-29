import time
import threading
import logging
import sqlite3
import sys
import signal
import requests
import json
from datetime import datetime, timedelta
from telebot import types

# Flask app export for gunicorn deployment
from app import app  # noqa: F401

import config
import database
import utils
from bot_init import bot, start_backup_task

import menu_system
import games_system


# ==========================================
# 🛠 НАСТРОЙКА ЛОГОВ
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
    try:
        games_system.start_background_tasks()
    except Exception as e:
        logger.error(f"Error starting games RSS: {e}")
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

            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            existing_user = cursor.fetchone()

            if not existing_user:
                reg_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute(
                    "INSERT INTO users (user_id, reg_date, referrer_id) VALUES (?, ?, ?)",
                    (user_id, reg_date, referrer_id)
                )
                conn.commit()

                if referrer_id:
                    vip_until = database.add_vip_days(referrer_id, 7)
                    notify = (
                        "🎉 **Новый партнер!**\n"
                        "Кто-то зарегистрировался по вашей ссылке.\n\n"
                        "⭐ Вам начислено **+7 дней VIP** за реферала!"
                    )
                    if vip_until:
                        notify += f"\n📅 VIP активен до: `{vip_until} (UTC)`"
                    utils.safe_send_message(referrer_id, notify, parse_mode='Markdown')
                    logger.info(f"New Referral: {user_id} invited by {referrer_id}, +7 VIP days awarded")

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
    """Получает статус автопродления (1 или 0)"""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            row = conn.execute(
                "SELECT auto_renew FROM user_news_prefs WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row[0] if row else 0
    except: return 0

def send_vip_invoice(chat_id, is_subscription=False):
    """Отправляет счет на VIP подписку через Telegram Stars"""
    sub_period = 2592000 if is_subscription else None
    label_text = "VIP Подписка (Авто)" if is_subscription else "VIP Радар (30 дней)"
    desc = "Элитные раздачи топовых игр, безлимитный шорт-лист и полное отключение рекламы.\n\n"
    desc += "🔄 Включено автопродление каждые 30 дней." if is_subscription else "Подписка на 30 дней."

    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendInvoice"
        payload = {
            "chat_id": chat_id,
            "title": "VIP Статус ⭐️",
            "description": desc,
            "payload": "vip_sub_30",
            "provider_token": "",
            "currency": "XTR",
            "prices": json.dumps([{"label": label_text, "amount": 100}])
        }
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
            f"Бот продолжит присылать элитные раздачи игр в личные сообщения и давать доступ к безлимитному шорт-листу."
        )
        toggle_label = "🔴 Выключить автопродление" if auto_renew else "🟢 Включить автопродление"
        mk.add(types.InlineKeyboardButton(toggle_label, callback_data="toggle_auto"))
        mk.add(types.InlineKeyboardButton("💎 Продлить (100 ⭐)", callback_data="buy_vip"))
        utils.safe_send_message(chat_id, text, parse_mode='Markdown', reply_markup=mk)
    else:
        auto_text = "♾ Включено" if auto_renew else "⏹ Выключено"
        text = (
            f"⭐️ **VIP Статус — Инструмент для тех, кто ценит выгоду!**\n\n"
            f"🎁 **Радар Элитной Халявы:**\n"
            f"Топовые AAA-игры и крутое инди — пуш-уведомление прямо в ЛС.\n\n"
            f"♾ **Безлимитный Шорт-лист (до 100 игр):**\n"
            f"Добавляй всё что хочешь — бот сообщит когда цена упадет.\n\n"
            f"🚫 **Ad-Free:**\n"
            f"Полное отключение любых рекламных рассылок.\n\n"
            f"⚙️ **Автопродление:** {auto_text}\n"
            f"_(Включи, чтобы бот автоматически продлевал подписку каждый месяц)_"
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


@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(
        pre_checkout_query.id, ok=True,
        error_message="Произошла ошибка, попробуйте еще раз."
    )

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

                if row and row[0]:
                    try:
                        old_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                        if old_until > current_time:
                            new_until = old_until + timedelta(days=30)
                    except: pass

                new_date_str = new_until.strftime('%Y-%m-%d %H:%M:%S')

                if row:
                    cursor.execute(
                        "UPDATE user_news_prefs SET premium_until = ?, want_freebies = 1 WHERE user_id = ?",
                        (new_date_str, chat_id)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO user_news_prefs (user_id, premium_until, want_freebies) VALUES (?, ?, 1)",
                        (chat_id, new_date_str)
                    )
                conn.commit()

                success_text = (
                    f"🎉 **Ура! Оплата прошла успешно.**\n\n"
                    f"Твоя подписка на VIP Радар активна до: `{new_date_str} (UTC)`."
                )
                utils.safe_send_message(chat_id, success_text, parse_mode='Markdown')
                logger.info(f"User {chat_id} bought VIP until {new_date_str}")

        except Exception as e:
            logger.error(f"Payment update error: {e}")
            utils.safe_send_message(
                chat_id,
                "⚠️ Оплата прошла, но возникла техническая заминка. Пожалуйста, напишите администратору."
            )


# ==========================================
# 👑 АДМИНСКАЯ КОМАНДА: ВЫДАТЬ VIP
# ==========================================
@bot.message_handler(commands=['give_vip'])
def give_vip_command(message):
    if str(message.chat.id) != str(config.ADMIN_ID): return

    args = message.text.split()
    if len(args) != 3:
        utils.safe_send_message(
            message.chat.id,
            "❌ Формат: `/give_vip [user_id] [дней]`\nПример: `/give_vip 123456789 30`",
            parse_mode='Markdown'
        )
        return

    try:
        target_user_id = int(args[1])
        days_to_add = int(args[2])

        new_date_str = database.add_vip_days(target_user_id, days_to_add)
        if new_date_str:
            utils.safe_send_message(
                message.chat.id,
                f"✅ Пользователю `{target_user_id}` выдан VIP до `{new_date_str}` (UTC).",
                parse_mode='Markdown'
            )
            utils.safe_send_message(
                target_user_id,
                f"🎁 **Администратор выдал вам VIP-подписку!**\nАктивна до: `{new_date_str} (UTC)`.\n\nСпасибо, что вы с нами! ❤️",
                parse_mode='Markdown'
            )
        else:
            utils.safe_send_message(message.chat.id, "❌ Ошибка при выдаче VIP.")
    except ValueError:
        utils.safe_send_message(message.chat.id, "❌ ID и количество дней должны быть числами.")
    except Exception as e:
        logger.error(f"Give VIP error: {e}")
        utils.safe_send_message(message.chat.id, f"❌ Ошибка: {e}")


# ==========================================
# 🔥 ПОСТ В КАНАЛ (АДМИН)
# ==========================================
def process_channel_post(message):
    if str(message.chat.id) != str(config.ADMIN_ID): return
    if message.text and message.text == "❌ Отмена":
        utils.safe_send_message(message.chat.id, "✅ Публикация отменена.", reply_markup=utils.main_kbrd(message.chat.id))
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
        return
    try:
        bot.copy_message(chat_id=config.CHANNEL_ID, from_chat_id=message.chat.id, message_id=message.message_id)
        utils.safe_send_message(
            message.chat.id, "✅ **Успешно опубликовано в канале!**",
            parse_mode='Markdown', reply_markup=utils.main_kbrd(message.chat.id)
        )
    except Exception as e:
        logger.error(f"Post to channel error: {e}")
        utils.safe_send_message(
            message.chat.id, f"❌ Ошибка публикации: {e}",
            reply_markup=utils.main_kbrd(message.chat.id)
        )

@bot.message_handler(commands=['post'])
@bot.message_handler(func=lambda message: message.text == "📝 Пост в канал")
def post_to_channel_command(message):
    if str(message.chat.id) != str(config.ADMIN_ID): return
    cancel_km = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_km.add("❌ Отмена")
    msg = utils.safe_send_message(
        message.chat.id,
        "📢 **Создание поста в канал**\n\nОтправь то, что нужно опубликовать (текст, фото, видео, гифку).",
        parse_mode='Markdown', reply_markup=cancel_km
    )
    bot.register_next_step_handler(msg, process_channel_post)


# ==========================================
# 📊 СТАТИСТИКА (АДМИН)
# ==========================================
@bot.message_handler(commands=['stats'])
@bot.message_handler(regexp=r"(?i).*статистика.*")
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

    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("ALTER TABLE user_news_prefs ADD COLUMN auto_renew INTEGER DEFAULT 0")
            conn.commit()
    except sqlite3.OperationalError:
        pass

    menu_system.register_handlers(bot)
    games_system.register_handlers(bot)
    start_all_background_services()

    try:
        bot.set_my_commands([
            types.BotCommand("start", "Открыть Game Broker")
        ])
    except Exception as e:
        logger.warning(f"Не удалось установить команды бота: {e}")

    # Чистый выход по SIGTERM (Replit останавливает процесс этим сигналом)
    def _shutdown(signum, frame):
        logger.info("Получен сигнал завершения — останавливаем polling...")
        try:
            bot.stop_polling()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Принудительно закрываем старую сессию через прямые вызовы Telegram API
    logger.info("Закрываем старые сессии Telegram...")
    base_url = f"https://api.telegram.org/bot{config.BOT_TOKEN}"
    for attempt in range(3):
        try:
            r = requests.post(f"{base_url}/deleteWebhook",
                              json={"drop_pending_updates": True}, timeout=8)
            logger.info(f"deleteWebhook: {r.json().get('description','ok')}")
            break
        except Exception as e:
            logger.warning(f"deleteWebhook attempt {attempt+1}: {e}")
            time.sleep(2)

    # Закрываем открытое getUpdates-соединение на стороне Telegram
    try:
        r = requests.post(f"{base_url}/close", timeout=8)
        logger.info(f"close: {r.json().get('description','ok')}")
    except Exception:
        pass

    # Ждём, пока Telegram полностью освободит соединение (long-poll таймаут = 30с)
    logger.info("Ожидание освобождения сессии (35 сек)...")
    time.sleep(35)

    print("🚀 Бот запущен!")
    while True:
        try:
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=25,
                skip_pending=True,
                restart_on_change=False,
                logger_level=logging.WARNING
            )
        except Exception as e:
            err = str(e)
            logger.error(f"Bot Polling Error: {e}")
            if "409" in err or "Conflict" in err:
                logger.warning("Конфликт сессий (409) — ждём полного закрытия (35 сек)...")
                try:
                    requests.post(
                        f"https://api.telegram.org/bot{config.BOT_TOKEN}/close",
                        timeout=5
                    )
                except Exception:
                    pass
                try:
                    bot.remove_webhook(drop_pending_updates=True)
                except Exception:
                    pass
                time.sleep(35)
            elif "502" in err or "503" in err or "504" in err:
                logger.warning("Telegram временно недоступен — повтор через 15 сек...")
                time.sleep(15)
            else:
                time.sleep(5)
