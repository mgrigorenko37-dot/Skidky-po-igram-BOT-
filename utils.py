import time
import logging
import os
import requests
import telebot
from bs4 import BeautifulSoup
from urllib.parse import quote
from telebot import types

from bot_init import bot
import config

logger = logging.getLogger(__name__)

# ==========================================
# 🛡️ АНТИ-ФЛУД И БЕЗОПАСНОСТЬ
# ==========================================
COOLDOWNS = {}

def check_cooldown(user_id, action, timeout=1.5):
    """Возвращает True, если можно выполнять действие"""
    current_time = time.time()
    if user_id not in COOLDOWNS:
        COOLDOWNS[user_id] = {}

    last_time = COOLDOWNS[user_id].get(action, 0)

    if current_time - last_time >= timeout:
        COOLDOWNS[user_id][action] = current_time
        return True
    return False

# --- БЕЗОПАСНАЯ ОТПРАВКА (Anti-Crash) ---
def safe_send_message(chat_id, text, **kwargs):
    """
    Безопасная отправка сообщения.
    Обрабатывает аргумент 'caption', перенося его в текст, чтобы избежать ошибок API.
    """
    try:
        if 'caption' in kwargs:
            caption = kwargs.pop('caption')
            if caption:
                if text:
                    text = f"{text}\n\n{caption}"
                else:
                    text = caption

        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e: 
        logger.warning(f"Ошибка отправки сообщения {chat_id}: {e}")
        return None

def safe_edit_message_text(text, chat_id, message_id, **kwargs):
    try: return bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except: return None

def safe_answer_callback(callback_query_id, text=None, show_alert=False):
    try:
        if text: return bot.answer_callback_query(callback_query_id, text, show_alert=show_alert)
        return bot.answer_callback_query(callback_query_id)
    except: return None

def safe_send_photo(chat_id, photo_url, **kwargs):
    try: return bot.send_photo(chat_id, photo_url, **kwargs)
    except Exception as e:
        logger.warning(f"Ошибка отправки фото: {e}")
        caption = kwargs.get('caption', 'Ошибка загрузки фото')
        return safe_send_message(chat_id, caption, parse_mode=kwargs.get('parse_mode'))

def safe_delete_message(chat_id, message_id):
    try: bot.delete_message(chat_id, message_id)
    except: pass

def get_bot_username(m=None):
    try: return bot.get_me().username
    except: return "bot_username"

# ==========================================
# 💱 АВТО-КОНВЕРТАЦИЯ ВАЛЮТ (API)
# ==========================================
RATES_CACHE = {}
LAST_RATES_UPDATE = 0

def get_live_rates():
    """Получает свежие курсы валют с открытого API"""
    global RATES_CACHE, LAST_RATES_UPDATE

    if time.time() - LAST_RATES_UPDATE < 3600 and RATES_CACHE:
        return RATES_CACHE

    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        res = requests.get(url, timeout=5).json()

        if 'rates' in res:
            RATES_CACHE = res['rates']
            LAST_RATES_UPDATE = time.time()
            return RATES_CACHE

    except Exception as e:
        logger.error(f"Currency API Error: {e}")

    return RATES_CACHE

def convert_price(usd_price, user_currency):
    """
    Конвертирует цену и возвращает готовую строку (например: '1500 ₽')
    """
    if usd_price is None: return "N/A"
    try:
        p = float(usd_price)
        if p == 0: return "БЕСПЛАТНО"

        if user_currency == 'USD':
            return f"${p:.2f}"

        rates = get_live_rates()
        rate = rates.get(user_currency, 1.0)

        final_price = p * rate
        symbol = config.CURRENCY_SIGNS.get(user_currency, user_currency)

        if final_price > 100:
            return f"{int(final_price)} {symbol}"
        return f"{final_price:.2f} {symbol}"

    except: return f"${usd_price}"

# ==========================================
# 🎹 МЕНЮ И КЛАВИАТУРЫ
# ==========================================

def get_webapp_url():
    """Возвращает URL для Telegram Mini App.
    Приоритет: WEBAPP_URL (задаётся вручную) → REPLIT_DOMAINS (деплой/дев)
    """
    # 1. Явно заданный URL (например, после деплоя)
    custom = os.environ.get('WEBAPP_URL', '').strip().rstrip('/')
    if custom:
        return custom
    # 2. Домен Replit (работает и в деплое, и в дев-режиме)
    domain = os.environ.get('REPLIT_DOMAINS', '') or os.environ.get('REPLIT_DEV_DOMAIN', '')
    if domain:
        # REPLIT_DOMAINS может содержать несколько доменов через запятую — берём первый
        domain = domain.split(',')[0].strip()
        return f"https://{domain}"
    return None

def main_kbrd(uid=None):
    """
    Главное меню бота — только кнопка Web App
    """
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=False)

    webapp_url = get_webapp_url()
    if webapp_url:
        m.add(types.KeyboardButton(
            "🎮 Играть",
            web_app=types.WebAppInfo(url=webapp_url)
        ))
    else:
        m.add(types.KeyboardButton("🎮 Играть"))

    return m

# ==========================================
# 🔗 ССЫЛКИ И ПАРСИНГ
# ==========================================

def generate_aff_link(original_url, store_id):
    store_id = str(store_id)
    if store_id in config.PARTNER_LINKS and config.PARTNER_LINKS[store_id]:
        partner_base = config.PARTNER_LINKS[store_id]
        separator = "&" if "?" in partner_base else "?"
        return f"{partner_base}{separator}ulp={quote(original_url)}&subid={config.ADMITAD_SUBID}"
    return original_url

def get_ggsel_link(game_title):
    search_url = f"https://ggsel.net/catalog?q={game_title}"
    return f"{config.GGSEL_AFF_LINK}{quote(search_url)}"

def get_image_from_url(url):
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        og = soup.find('meta', property='og:image')
        if og and og.get('content'): return str(og['content'])
        all_imgs = soup.find_all('img')
        for img in all_imgs:
            src = img.get('src')
            if src and isinstance(src, str) and src.startswith('http'):
                if 'logo' not in src.lower() and 'icon' not in src.lower():
                    return src
    except Exception as e:
        logger.error(f"Error in get_image_from_url: {e}")
    return None