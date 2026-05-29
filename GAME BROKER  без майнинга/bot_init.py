import telebot
import os
import logging
import threading
import time
import config

# Настройка логов
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Получаем токен
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()

if not BOT_TOKEN:
    logger.critical("❌ ОШИБКА: BOT_TOKEN не найден в Secrets!")
    print("❌ ОШИБКА: Добавь BOT_TOKEN в Secrets!")

# Инициализируем бота (используем threaded=False если будут проблемы с потоками, но обычно True ок)
bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# 🛡️ СИСТЕМА АВТО-БЭКАПА БАЗЫ ДАННЫХ
# ==========================================

def send_db_backup():
    """Отправляет файл базы данных админу"""
    try:
        if os.path.exists(config.DB_FILE):
            with open(config.DB_FILE, 'rb') as db_file:
                bot.send_document(
                    config.ADMIN_ID, 
                    db_file, 
                    caption="🛡️ **Автоматический бэкап базы данных**\n\nСохрани этот файл. Если что-то случится с сервером, просто замени им новый файл `database.db`.", 
                    parse_mode="Markdown"
                )
            logger.info("✅ Бэкап БД успешно отправлен админу.")
        else:
            logger.warning("⚠️ Файл БД не найден для бэкапа.")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке бэкапа: {e}")

def backup_loop():
    """Фоновый цикл для отправки бэкапа раз в 24 часа"""
    logger.info("🛡️ Служба авто-бэкапов запущена.")
    # Отправляем первый бэкап сразу при запуске (чтобы убедиться, что всё работает)
    send_db_backup()

    while True:
        # Ждем 24 часа (86400 секунд)
        time.sleep(86400)
        send_db_backup()

def start_backup_task():
    """Запускает поток бэкапов (вызывать при старте бота)"""
    threading.Thread(target=backup_loop, daemon=True).start()