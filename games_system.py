import sqlite3
import requests
import time
import random
import logging
import threading
import feedparser
import re
from bs4 import BeautifulSoup
from telebot import types
from deep_translator import GoogleTranslator
from urllib.parse import quote, unquote
from datetime import datetime

import config
import utils
import database 
from bot_init import bot

logger = logging.getLogger(__name__)

# ==========================================
# 🛑 СПИСОК СЛОВ-ИСКЛЮЧЕНИЙ
# ==========================================
STOP_WORDS = [
    "Майнинг", "Кошелек", "Отследить", "жанрам", "Шорт-лист", 
    "скидок", "Настройки", "Партнерка", "Поддержать", "Сообщество", 
    "Реклама", "Статистика", "📊 Статистика", "статистика", "Правила", "Помощь", "Назад", "Отмена",
    "Пополнить", "Вывести", "Продать", "Купить",
    "помощь", "правила", "настройки", "партнерка", "сообщество",
    "check_news", "⚙️ Настройки", "🤝 Партнерка", "💬 Сообщество", "⭐ Поддержать",
    "🔍 Поиск по жанрам", "Поиск по жанрам", "🔥 Топ скидок", "➕ Отследить игру", "ℹ️ О боте", "О боте",
    "⭐️ VIP Подписка", "VIP Подписка", "📝 Пост в канал"
]

# ==========================================
# 🗺️ КАРТА ЖАНРОВ (С ИКОНКАМИ)
# ==========================================
STEAM_TAGS = {
    "⚔️ Экшен": 19, 
    "🧙‍♂️ РПГ": 122, 
    "🧠 Стратегии": 9, 
    "🗺️ Приключения": 21,
    "🔫 Шутеры": 1774, 
    "👻 Хорроры": 1667, 
    "🚜 Симуляторы": 599, 
    "🏕️ Выживание": 1662,
    "🥊 Файтинги": 1743, 
    "⚽ Спорт": 701, 
    "🧩 Головоломки": 1664, 
    "🎨 Инди": 492,
    "👥 ММО": 128, 
    "🏃 Платформеры": 1625, 
    "🔥 Хардкор (Souls)": 29482, 
    "🤝 Кооператив": 1685
}

TRANSLATION_CACHE = {}
RSS_THREAD_RUNNING = False 
WISHLIST_THREAD_RUNNING = False

ALERT_COOLDOWN = {} 

LAST_DEALS_MSGS = {}
LAST_GENRE_MSGS = {}

# ==========================================
# 🔧 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def clean_md(text):
    """Очистка текста от опасных символов Markdown, default ломают Telegram API"""
    if not text: return ""
    return str(text).replace('*', '').replace('_', '').replace('`', '').replace('[', '【').replace(']', '】').replace('(', '（').replace(')', '）')

def safe_translate(text, target='en'):
    if not text or text.isascii(): return text
    if text in TRANSLATION_CACHE: return TRANSLATION_CACHE[text]
    try:
        translated = GoogleTranslator(source='auto', target=target).translate(text)
        TRANSLATION_CACHE[text] = translated
        return translated
    except: return text

def get_user_currency(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            row = conn.execute("SELECT currency FROM user_news_prefs WHERE user_id = ?", (user_id,)).fetchone()
            return row[0] if row else 'USD'
    except: return 'USD'

def is_user_vip(user_id):
    """Проверяет, есть ли у пользователя активная VIP подписка"""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            row = conn.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (user_id,)).fetchone()
            if row and row[0]:
                premium_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                if premium_until > datetime.utcnow():
                    return True
    except: pass
    return False

# ==========================================
# 📰 СИСТЕМА НОВОСТЕЙ И ХАЛЯВЫ
# ==========================================

def extract_image_and_text(entry):
    img_url = None
    summary_text = ""

    try:
        if 'enclosures' in entry:
            for enc in entry.enclosures:
                if 'image' in enc.type and enc.href.startswith('http'): 
                    img_url = enc.href
        if not img_url and 'media_content' in entry:
            url = entry.media_content[0]['url']
            if url.startswith('http'): img_url = url

        content = ""
        if 'summary' in entry: content += entry.summary
        if 'content' in entry: 
            for c in entry.content: content += c.value

        if content:
            soup = BeautifulSoup(content, 'html.parser')

            if not img_url:
                img = soup.find('img')
                if img and img.get('src'):
                    src = img['src']
                    if src.startswith('http') and "emoji" not in src and "doubleclick" not in src and ".webp" not in src.lower() and ".svg" not in src.lower(): 
                        img_url = src

            summary_text = soup.get_text(separator=' ', strip=True)

    except Exception as e: 
        logger.error(f"Extraction error: {e}")

    return img_url, summary_text

def is_top_tier_freebie(game_title, original_price):
    try:
        if original_price and original_price != 'N/A':
            price_val = float(original_price.replace('$', '').strip())
            if price_val < 10.0: return False
    except: pass 

    try:
        clean_title = re.sub(r'[^\w\s]', '', game_title).strip().replace(" ", "%20")
        url = f"https://www.cheapshark.com/api/1.0/games?title={clean_title}&limit=1"
        res = requests.get(url, timeout=5).json()

        if not res: return False 

        game_id = res[0]['gameID']
        details_url = f"https://www.cheapshark.com/api/1.0/games?id={game_id}"
        details = requests.get(details_url, timeout=5).json()

        info = details.get('info', {})
        steam_rating = int(info.get('steamRatingPercent', 0) or 0)
        metacritic_score = int(info.get('metacriticScore', 0) or 0)

        if steam_rating >= 80 or metacritic_score >= 75: return True
        else: return False
    except Exception as e:
        logger.error(f"Freebie Filter Error ({game_title}): {e}")
        return False

def fetch_and_post_updates(bot, manual_check=False, admin_id=None):
    debug_report = []
    new_count = 0

    with sqlite3.connect(config.DB_FILE) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS sent_news (news_id TEXT PRIMARY KEY)")

    # ==========================================
    # 1. ПАРСИНГ ХАЛЯВЫ -> В ЛС ДЛЯ VIP
    # ==========================================
    try:
        gp_url = "https://www.gamerpower.com/api/giveaways?platform=pc&type=game"
        r = requests.get(gp_url, timeout=15)

        if r.status_code == 200:
            giveaways = r.json()[:10] 

            with sqlite3.connect(config.DB_FILE) as conn:
                for ga in reversed(giveaways): 
                    nid = f"gp_{ga['id']}"

                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM sent_news WHERE news_id = ?", (nid,))
                    if cursor.fetchone(): continue

                    if is_top_tier_freebie(ga['title'], ga.get('worth', '0')):
                        title = clean_md(ga['title'])
                        link = ga['open_giveaway']
                        img = ga.get('image', '')
                        platforms = clean_md(ga.get('platforms', 'PC'))
                        worth = clean_md(ga.get('worth', 'Бесплатно'))

                        text = (
                            f"💎 **ЭЛИТНАЯ РАЗДАЧА (VIP Радар)**\n\n"
                            f"🎮 **{title}**\n"
                            f"💻 Магазин: {platforms}\n"
                            f"💰 Обычная цена: ~{worth}"
                        )
                        mk = types.InlineKeyboardMarkup()
                        mk.add(types.InlineKeyboardButton("🎁 Забрать игру", url=link))

                        vip_users = []
                        try:
                            cursor.execute("SELECT user_id, premium_until FROM user_news_prefs")
                            for row in cursor.fetchall():
                                uid, premium_until = row[0], row[1]
                                if premium_until:
                                    try:
                                        if datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S') > datetime.utcnow():
                                            vip_users.append(uid)
                                    except: pass
                        except Exception as e:
                            logger.error(f"VIP fetch error: {e}")

                        for v_uid in vip_users:
                            sent = False
                            if img: 
                                try:
                                    bot.send_photo(v_uid, img, caption=text, parse_mode='Markdown', reply_markup=mk)
                                    sent = True
                                except Exception as img_e:
                                    logger.warning(f"VIP Photo Error: {img_e} - falling back to text.")

                            if not sent:
                                utils.safe_send_message(v_uid, text, parse_mode='Markdown', reply_markup=mk)

                            time.sleep(0.05)

                        conn.execute("INSERT OR IGNORE INTO sent_news (news_id) VALUES (?)", (nid,))
                        conn.commit()
                        new_count += 1
                        time.sleep(3) 
                    else:
                        conn.execute("INSERT OR IGNORE INTO sent_news (news_id) VALUES (?)", (nid,))
                        conn.commit()
        else:
            if manual_check: debug_report.append(f"❌ GamerPower: HTTP {r.status_code}")
    except Exception as e:
        logger.error(f"GamerPower Fetch Error: {e}")
        if manual_check: debug_report.append(f"❌ Ошибка GamerPower: {e}")

    # ==========================================
    # 2. ПАРСИНГ НОВОСТЕЙ -> В ОБЩИЙ КАНАЛ
    # ==========================================
    if config.RSS_NEWS:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml'
            }
            r = requests.get(config.RSS_NEWS, headers=headers, timeout=20)
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
                if feed.entries:
                    entries = list(reversed(feed.entries[:5]))
                    with sqlite3.connect(config.DB_FILE) as conn:
                        for entry in entries:
                            nid = entry.get('id', entry.link)

                            cursor = conn.cursor()
                            cursor.execute("SELECT 1 FROM sent_news WHERE news_id = ?", (nid,))
                            if cursor.fetchone(): continue

                            title = clean_md(entry.title.replace("&nbsp;", " ").replace("&#8217;", "'"))
                            link = entry.link

                            img, raw_summary = extract_image_and_text(entry)

                            clean_summary = ""
                            if raw_summary:
                                clean_summary = re.sub(r'\s+', ' ', raw_summary).strip()
                                if len(clean_summary) > 500:
                                    clean_summary = clean_summary[:500] + "..."
                                clean_summary = clean_md(clean_summary)

                            text = f"📰 **Игровые новости**\n\n**{title}**\n\n"
                            if clean_summary:
                                text += f"📖 {clean_summary}\n\n"
                            text += f"🔗 [Читать полностью]({link})"

                            mk = types.InlineKeyboardMarkup()
                            mk.add(types.InlineKeyboardButton("📰 Читать на сайте", url=link))

                            if not img:
                                img = utils.get_image_from_url(link)

                            sent = False
                            if img: 
                                try:
                                    bot.send_photo(config.CHANNEL_ID, img, caption=text, parse_mode='Markdown', reply_markup=mk)
                                    sent = True
                                except Exception as e:
                                    logger.warning(f"Channel Photo Error: {e} - falling back to text.")

                            if not sent:
                                utils.safe_send_message(config.CHANNEL_ID, text, parse_mode='Markdown', reply_markup=mk)

                            conn.execute("INSERT OR IGNORE INTO sent_news (news_id) VALUES (?)", (nid,))
                            conn.commit()
                            new_count += 1
                            time.sleep(3) 
            else:
                if manual_check: debug_report.append(f"❌ Новости RSS: HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"RSS Fetch Error: {e}")
            if manual_check: debug_report.append(f"❌ Ошибка RSS: {e}")

    if manual_check and admin_id:
        msg = "\n".join(debug_report) if debug_report else "Ошибок при сканировании нет."
        msg += f"\n\n🆕 Отправлено постов: {new_count}"

        try:
            with sqlite3.connect(config.DB_FILE) as conn:
                row = conn.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (admin_id,)).fetchone()
                is_vip = False
                if row and row[0]:
                    try:
                        p_date = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                        if p_date > datetime.utcnow(): is_vip = True
                    except: pass
                msg += f"\n\n👑 Твой статус VIP: {'✅ Активен' if is_vip else '❌ Не активен'}"
        except: pass

        utils.safe_send_message(admin_id, msg, parse_mode='Markdown')

# ==========================================
# 🔔 МОНИТОР ЦЕН ШОРТ-ЛИСТА
# ==========================================

def check_wishlist_prices(bot):
    logger.info("🕵️‍♂️ Запуск проверки цен в шорт-листах...")

    with sqlite3.connect(config.DB_FILE) as conn:
        items = conn.execute(
            "SELECT user_id, game_id, game_name FROM wishlist WHERE game_id IS NOT NULL"
        ).fetchall()

    if not items:
        logger.info("📭 Шорт-листы пусты или нет записей с game_id.")
        return

    games_to_check = {}
    for uid, gid, title in items:
        if not gid:
            continue
        if gid not in games_to_check:
            games_to_check[gid] = []
        games_to_check[gid].append(uid)

    for game_id, user_ids in games_to_check.items():
        try:
            data = get_game_multi_store_deals(game_id, 'USD')
            if not data or not data['deals']: continue

            best_deal = data['deals'][0] 
            savings = float(best_deal['savings'])

            if savings >= 20:
                for user_id in user_ids:
                    cache_key = f"{user_id}_{game_id}"
                    last_sent = ALERT_COOLDOWN.get(cache_key, 0)

                    if time.time() - last_sent > 86400: 

                        user_curr = get_user_currency(user_id)
                        user_data = get_game_multi_store_deals(game_id, user_curr)
                        if user_data:
                            user_best = user_data['deals'][0]

                            msg = (
                                f"🔔 **ЦЕНА УПАЛА!**\n\n"
                                f"🎮 Игра: **{clean_md(data['title'])}**\n"
                                f"📉 Скидка: **-{int(savings)}%**\n"
                                f"💰 Цена: **{user_best['price']}**\n"
                                f"🏪 Магазин: {clean_md(user_best['store'])}"
                            )

                            mk = types.InlineKeyboardMarkup()
                            mk.add(types.InlineKeyboardButton("🔥 Купить", url=user_best['url']))

                            try:
                                bot.send_photo(user_id, data['thumb'], caption=msg, parse_mode='Markdown', reply_markup=mk)
                            except:
                                utils.safe_send_message(user_id, msg, parse_mode='Markdown', reply_markup=mk)

                            ALERT_COOLDOWN[cache_key] = time.time()
                            time.sleep(1) 

            time.sleep(1.5) 

        except Exception as e:
            logger.error(f"Wishlist Check Error (Game {game_id}): {e}")

# ==========================================
# 🔄 ФОНОВЫЕ ЗАДАЧИ
# ==========================================

def start_background_tasks():
    global RSS_THREAD_RUNNING, WISHLIST_THREAD_RUNNING

    if not RSS_THREAD_RUNNING:
        RSS_THREAD_RUNNING = True
        def news_loop():
            logger.info("🗞 Мониторинг новостей и халявы запущен.")
            while True:
                try: fetch_and_post_updates(bot)
                except Exception as e: logger.error(f"RSS Loop Error: {e}")
                time.sleep(1800) 
        threading.Thread(target=news_loop, daemon=True).start()

    if not WISHLIST_THREAD_RUNNING:
        WISHLIST_THREAD_RUNNING = True
        def wishlist_loop():
            logger.info("🕵️‍♂️ Монитор цен запущен.")
            while True:
                try: check_wishlist_prices(bot)
                except Exception as e: logger.error(f"Wishlist Loop Error: {e}")
                time.sleep(14400) 
        threading.Thread(target=wishlist_loop, daemon=True).start()

# ==========================================
# 🕵️ ПОИСК ИГР (МУЛЬТИ-МАГАЗИН)
# ==========================================

def get_game_multi_store_deals(game_id, user_currency='USD'):
    try:
        url = f"https://www.cheapshark.com/api/1.0/games?id={game_id}"
        data = requests.get(url, timeout=10).json()

        info = data.get('info', {})
        deals = data.get('deals', [])

        if not deals: return None

        deals.sort(key=lambda x: float(x['price']))

        seen_stores = set()
        unique_deals = []
        for d in deals:
            if d['storeID'] not in seen_stores:
                unique_deals.append(d)
                seen_stores.add(d['storeID'])

        top_deals = unique_deals[:3] 

        result = {
            "title": info.get('title', 'Unknown'),
            "thumb": info.get('thumb', ''),
            "deals": []
        }

        for d in top_deals:
            store_name = config.SUPPORTED_STORES.get(str(d['storeID']), f"Store {d['storeID']}")
            price = utils.convert_price(d['price'], user_currency)
            aff_url = utils.generate_aff_link(f"https://www.cheapshark.com/redirect?dealID={d['dealID']}", d['storeID'])
            result['deals'].append({
                "store": store_name,
                "price": price,
                "url": aff_url,
                "savings": float(d['savings'])
            })

        return result
    except Exception as e:
        logger.error(f"Deal Detail Error: {e}")
        return None

def search_steam_by_tag(tag_id, offset=0):
    try:
        actual_page = (offset // 15) + 1
        if offset == 0: actual_page = 1 

        url = f"https://store.steampowered.com/search/?tags={tag_id}&category1=998&page={actual_page}&cc=us&l=russian"

        cookies = {
            'birthtime': '568022401',
            'lastagecheckage': '1-0-1988',
            'wants_mature_content': '1'
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)

        if response.status_code != 200:
            logger.error(f"Steam returned status: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        games = []
        results_rows = soup.find(id="search_resultsRows")

        if not results_rows:
            return []

        for item in results_rows.find_all('a', class_='search_result_row'):
            try:
                title_el = item.find('span', class_='title')
                if not title_el: continue
                title = title_el.text.strip()

                if any(x in title.lower() for x in ['soundtrack', 'dlc', 'package', 'bundle', 'pass']): continue

                img_el = item.find('img')
                img = ""
                if img_el:
                    img_attr = img_el.get('src') or img_el.get('data-src')
                    if img_attr:
                        if isinstance(img_attr, list):
                            img = img_attr[0].split('?')[0]
                        else:
                            img = img_attr.split('?')[0]
                    else:
                        img = ""

                link_attr = item.get('href')
                if link_attr:
                    if isinstance(link_attr, list):
                        link = link_attr[0].split('?')[0]
                    else:
                        link = link_attr.split('?')[0]
                else:
                    link = ""

                if not link: continue

                games.append({"title": title, "thumb": img, "url": link})
            except: continue

        if len(games) > 5:
            random.shuffle(games)
        return games[:5]
    except Exception as e:
        logger.error(f"Steam Error: {e}")
        return []

def get_game_best_deal_details(game_id_or_title, is_title=False, user_currency='USD'):
    try:
        if is_title:
            clean_title = re.sub(r'[^\w\s]', ' ', game_id_or_title).strip()
            url = f"https://www.cheapshark.com/api/1.0/games?title={clean_title}&limit=1"
            search = requests.get(url, timeout=5).json()
            if not search: return None
            game_id = search[0]['gameID']
        else:
            game_id = game_id_or_title

        return get_game_multi_store_deals(game_id, user_currency)

    except: return None

# 🔥 ОБНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ УМНОГО ТОП СКИДОК С ПАМЯТЬЮ 🔥
def show_top_deals(chat_id, page=0):
    global LAST_DEALS_MSGS
    cid = str(chat_id)
    user_curr = get_user_currency(chat_id)

    # 🔥 ОБНОВЛЯЕМ АКТИВНОСТЬ
    database.update_user_activity(chat_id)

    # Очищаем чат от предыдущих карточек
    if cid in LAST_DEALS_MSGS:
        for msg_id in LAST_DEALS_MSGS[cid]:
            try: bot.delete_message(chat_id, msg_id)
            except: pass
    LAST_DEALS_MSGS[cid] = []

    wait_msg = utils.safe_send_message(chat_id, f"🎲 Ищу элитные скидки (Стр. {page+1})...")

    try:
        # 1. Запрашиваем сразу 50 топовых игр (чтобы был большой пул для выбора)
        url = "https://www.cheapshark.com/api/1.0/deals?storeID=1&onSale=1&upperPrice=50&sortBy=Deal%20Rating&steamRating=80&pageSize=50&pageNumber=0"
        all_deals = requests.get(url, timeout=10).json()

        if wait_msg: 
            try: bot.delete_message(chat_id, wait_msg.message_id)
            except: pass

        if not all_deals: 
            return utils.safe_send_message(chat_id, "Скидок не найдено или ошибка API.")

        # 2. Отфильтровываем те, что юзер уже видел
        fresh_deals = []
        for d in all_deals:
            if not d.get('thumb'): continue
            game_id_str = str(d['gameID'])
            if not database.is_deal_viewed(chat_id, game_id_str):
                fresh_deals.append(d)

        # 3. Если все 50 посмотрели - сбрасываем память и начинаем заново
        if len(fresh_deals) < 5:
            database.clear_viewed_deals(chat_id)
            fresh_deals = [d for d in all_deals if d.get('thumb')] # Берем все заново
            utils.safe_send_message(chat_id, "🔄 Вы просмотрели весь текущий топ скидок! Начинаем заново.")

        # 4. Выбираем 5 случайных свежих игр из пула
        selected_deals = random.sample(fresh_deals, min(5, len(fresh_deals)))

        for d in selected_deals:
            game_id_str = str(d['gameID'])

            # Отмечаем игру как просмотренную в БД
            database.mark_deal_viewed(chat_id, game_id_str)

            price = utils.convert_price(d['salePrice'], user_curr)
            old_price = utils.convert_price(d['normalPrice'], user_curr)

            aff_url = utils.generate_aff_link(f"https://www.cheapshark.com/redirect?dealID={d['dealID']}", d['storeID'])

            mk = types.InlineKeyboardMarkup()
            mk.add(types.InlineKeyboardButton(f"🔥 Купить за {price}", url=aff_url))
            mk.add(types.InlineKeyboardButton("➕ В шорт-лист", callback_data=f"wish_{game_id_str}"))

            savings = float(d.get('savings', 0))
            steam_rating = d.get('steamRatingPercent', 'N/A')
            if steam_rating == '0': steam_rating = 'N/A'

            caption = f"⚡ **{clean_md(d['title'])}**\n⭐ Рейтинг: {steam_rating}%\n📉 Скидка: -{int(savings)}%\n💰 Старая цена: ~{old_price}"

            try:
                sent_msg = bot.send_photo(chat_id, d['thumb'], caption=caption, parse_mode='Markdown', reply_markup=mk)
                if sent_msg: LAST_DEALS_MSGS[cid].append(sent_msg.message_id)
            except:
                sent_msg = utils.safe_send_message(chat_id, caption, parse_mode='Markdown', reply_markup=mk)
                if sent_msg: LAST_DEALS_MSGS[cid].append(sent_msg.message_id)
            time.sleep(0.3)

        # Рекламный блок для не-VIP
        if not is_user_vip(chat_id):
            active_ad = database.get_active_ad()
            if active_ad:
                ad_msg = utils.safe_send_message(chat_id, f"➖➖➖➖➖➖➖\n{active_ad['text']}", parse_mode='Markdown')
                if ad_msg: 
                    LAST_DEALS_MSGS[cid].append(ad_msg.message_id)
                    database.add_ad_view() # 🔥 ДОБАВЛЯЕМ ПРОСМОТР РЕКЛАМЫ

        # Кнопка пагинации
        mk = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("➡️ Показать еще скидки", callback_data=f"next_deals_{page+1}"))
        btn_msg = utils.safe_send_message(chat_id, f"Показана страница {page+1}.", reply_markup=mk)
        if btn_msg: LAST_DEALS_MSGS[cid].append(btn_msg.message_id)

    except Exception as e: 
        logger.error(f"Top deals error: {e}")
        if wait_msg: 
            try: bot.delete_message(chat_id, wait_msg.message_id)
            except: pass
        utils.safe_send_message(chat_id, "Ошибка поиска скидок. Попробуйте позже.")

def show_my_wishlist(chat_id, user_id):
    database.update_user_activity(chat_id)
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            items = conn.execute(
                "SELECT game_id, game_name FROM wishlist WHERE user_id = ?", (user_id,)
            ).fetchall()
        if not items:
            return utils.safe_send_message(chat_id, "🛒 Твой шорт-лист пока пуст.")
        mk = types.InlineKeyboardMarkup()
        for g_id, g_name in items:
            display = g_name or "Игра"
            if g_id:
                mk.add(
                    types.InlineKeyboardButton(f"🎮 {display}", callback_data=f"find_{g_id}"),
                    types.InlineKeyboardButton("❌", callback_data=f"remove_wish_{g_id}")
                )
            else:
                mk.add(
                    types.InlineKeyboardButton(f"🎮 {display}", callback_data=f"noop"),
                    types.InlineKeyboardButton("❌", callback_data=f"remove_wish_name_{display}")
                )
        utils.safe_send_message(chat_id, "📋 **Твой шорт-лист:**", parse_mode='Markdown', reply_markup=mk)
    except Exception as e:
        logger.error(f"Wishlist show error: {e}")

def search_game(chat_id, query):
    # 🔥 ОБНОВЛЯЕМ АКТИВНОСТЬ
    database.update_user_activity(chat_id)
    if not query: return

    utils.safe_send_message(chat_id, f"🔎 Ищу скидки на **{query}**...", parse_mode='Markdown')

    try:
        if any(u'\u0400' <= c <= u'\u04FF' for c in query): 
            q_en = safe_translate(query)
        else: 
            q_en = query

        clean_q = re.sub(r'[^\w\s]', '', q_en).strip()

        url = f"https://www.cheapshark.com/api/1.0/games?title={clean_q}&limit=5"
        games = requests.get(url, timeout=10).json()

        if not games:
            gg_link = utils.get_ggsel_link(query)
            mk = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🔎 Искать ключи (GGsel)", url=gg_link))
            utils.safe_send_message(chat_id, f"😔 В официальных магазинах пусто. Проверьте маркетплейс:", reply_markup=mk)
            return

        mk = types.InlineKeyboardMarkup()
        seen_titles = set()
        for g in games:
            if g['external'] in seen_titles: continue
            seen_titles.add(g['external'])
            mk.add(types.InlineKeyboardButton(f"🎮 {g['external']}", callback_data=f"find_{g['gameID']}"))

        utils.safe_send_message(chat_id, "👇 **Уточните игру:**", parse_mode='Markdown', reply_markup=mk)

    except Exception as e:
        logger.error(f"Search Game Error: {e}")
        utils.safe_send_message(chat_id, "❌ Ошибка поиска.")

# ==========================================
# 🎯 ХЕНДЛЕРЫ
# ==========================================

def register_handlers(bot):

    @bot.message_handler(commands=['clear_news'])
    def clear_news_memory(m):
        if str(m.chat.id) != str(config.ADMIN_ID): return
        try:
            with sqlite3.connect(config.DB_FILE) as conn:
                conn.execute("DELETE FROM sent_news")
                conn.commit()
            utils.safe_send_message(m.chat.id, "🧹 **Память бота (sent_news) успешно очищена!**\nТеперь команда `/check_news` пришлет последние новости и халяву заново.", parse_mode='Markdown')
        except Exception as e:
            utils.safe_send_message(m.chat.id, f"❌ Ошибка очистки: {e}")

    @bot.message_handler(commands=['check_news'])
    def admin_force_check(m):
        if str(m.chat.id) != str(config.ADMIN_ID): return
        utils.safe_send_message(m.chat.id, "⏳ **Сканирую 30+ источников и халяву...**")
        threading.Thread(target=fetch_and_post_updates, args=(bot, True, m.chat.id)).start()

        utils.safe_send_message(m.chat.id, "🔎 **Принудительная проверка цен (Wishlist)...**")
        threading.Thread(target=check_wishlist_prices, args=(bot,)).start()

    @bot.callback_query_handler(func=lambda c: c.data.startswith("next_deals_"))
    def next_deals_handler(c):
        try:
            page = int(c.data.split('_')[2])
            bot.answer_callback_query(c.id, "🔄 Загружаю...")
            try: bot.delete_message(c.message.chat.id, c.message.message_id)
            except: pass
            show_top_deals(c.message.chat.id, page)
        except: pass

    @bot.message_handler(func=lambda m: m.text and not m.text.startswith('/') and m.text not in STOP_WORDS)
    def handle_search(m):
        if len(m.text) < 2: return
        if any(x in m.text for x in ["Кошелек", "Ферма", "Помощь", "Правила"]): return
        if not utils.check_cooldown(m.from_user.id, "search", 2.0): return
        search_game(m.chat.id, m.text.strip())

    @bot.callback_query_handler(func=lambda c: c.data.startswith("find_"))
    def show_deals(c):
        game_id = c.data.split('_')[1]
        chat_id = c.message.chat.id

        # 🔥 ОБНОВЛЯЕМ АКТИВНОСТЬ
        database.update_user_activity(chat_id)

        user_curr = get_user_currency(chat_id)
        data = get_game_multi_store_deals(game_id, user_curr)

        if not data:
            bot.answer_callback_query(c.id, "❌ Скидки не найдены")
            return

        text = f"🎮 **{clean_md(data['title'])}**\n\n📉 **ЛУЧШИЕ ПРЕДЛОЖЕНИЯ:**\n"
        mk = types.InlineKeyboardMarkup()

        for deal in data['deals']:
            fire = "🔥 " if deal['savings'] > 50 else ""
            label = f"{fire}{clean_md(deal['store'])}: {deal['price']}"
            if deal['savings'] > 0: label += f" (-{int(deal['savings'])}%)"

            mk.add(types.InlineKeyboardButton(label, url=deal['url']))
            text += f"• {clean_md(deal['store'])}: **{deal['price']}**\n"

        if not is_user_vip(chat_id):
            active_ad = database.get_active_ad()
            if active_ad:
                text += f"\n➖➖➖➖➖➖➖\n{active_ad['text']}"
                database.add_ad_view() # 🔥 ДОБАВЛЯЕМ ПРОСМОТР РЕКЛАМЫ

        mk.add(types.InlineKeyboardButton("➕ В шорт-лист", callback_data=f"wish_{game_id}"))

        try:
            bot.send_photo(chat_id, data['thumb'], caption=text, parse_mode='Markdown', reply_markup=mk)
        except:
            utils.safe_send_message(chat_id, text, parse_mode='Markdown', reply_markup=mk)

    @bot.message_handler(func=lambda m: "Шорт-лист" in m.text)
    def wishlist_show(m):
        show_my_wishlist(m.chat.id, m.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("wish_"))
    def add_wish(c):
        gid = c.data.split('_')[1]
        user_id = c.from_user.id

        database.update_user_activity(user_id)

        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT premium_until FROM user_news_prefs WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                is_vip = False
                if row and row[0]:
                    try:
                        premium_until = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                        if premium_until > datetime.utcnow(): is_vip = True
                    except: pass

                cursor.execute("SELECT COUNT(*) FROM wishlist WHERE user_id = ?", (user_id,))
                wish_count = cursor.fetchone()[0]

                if not is_vip and wish_count >= 5:
                    bot.answer_callback_query(c.id, "🛑 Лимит 5 игр!\nОформи ⭐️ VIP для безлимита!", show_alert=True)
                    return
            except Exception as e:
                logger.error(f"Wishlist Limit Check Error: {e}")

            g_title = "Game"
            try:
                url = f"https://www.cheapshark.com/api/1.0/games?id={gid}"
                info = requests.get(url, timeout=5).json().get('info', {})
                g_title = info.get('title', 'Game')
            except: pass

            try:
                cursor.execute(
                    "INSERT OR REPLACE INTO wishlist (user_id, game_name, game_id) VALUES (?, ?, ?)",
                    (user_id, g_title, gid)
                )
                conn.commit()
                bot.answer_callback_query(c.id, "✅ Сохранено в шорт-лист")
            except Exception as e:
                logger.error(f"Add Wish Error: {e}")
                bot.answer_callback_query(c.id, "⚠️ Ошибка")

    @bot.callback_query_handler(func=lambda c: c.data == "noop")
    def noop_handler(c):
        bot.answer_callback_query(c.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("remove_wish_name_"))
    def rm_wish_by_name(c):
        name = c.data[len("remove_wish_name_"):]
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM wishlist WHERE user_id=? AND game_name=?", (c.from_user.id, name))
            conn.commit()
        bot.answer_callback_query(c.id, "🗑 Удалено")
        show_my_wishlist(c.message.chat.id, c.from_user.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("remove_wish_"))
    def rm_wish(c):
        gid = c.data.split('_')[2]
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM wishlist WHERE user_id=? AND game_id=?", (c.from_user.id, gid))
            conn.commit()
        bot.answer_callback_query(c.id, "🗑 Удалено")
        show_my_wishlist(c.message.chat.id, c.from_user.id)

    @bot.message_handler(func=lambda m: "жанрам" in m.text)
    def genres_btn(m):
        global LAST_GENRE_MSGS
        chat_id = m.chat.id
        cid = str(chat_id)

        # 🔥 ОБНОВЛЯЕМ АКТИВНОСТЬ
        database.update_user_activity(chat_id)

        if cid in LAST_GENRE_MSGS:
            for msg_id in LAST_GENRE_MSGS[cid]:
                try: bot.delete_message(chat_id, msg_id)
                except: pass
        LAST_GENRE_MSGS[cid] = []

        mk = types.InlineKeyboardMarkup(row_width=2) 
        btns = [types.InlineKeyboardButton(k, callback_data=f"genre_{k}_0") for k in STEAM_TAGS.keys()]
        mk.add(*btns)
        utils.safe_send_message(chat_id, "🎯 **Категории:**", parse_mode='Markdown', reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data == "back_to_genres")
    def back_to_genres_handler(c):
        global LAST_GENRE_MSGS
        chat_id = c.message.chat.id
        cid = str(chat_id)

        if cid in LAST_GENRE_MSGS:
            for msg_id in LAST_GENRE_MSGS[cid]:
                try: bot.delete_message(chat_id, msg_id)
                except: pass
        LAST_GENRE_MSGS[cid] = []

        mk = types.InlineKeyboardMarkup(row_width=2) 
        btns = [types.InlineKeyboardButton(k, callback_data=f"genre_{k}_0") for k in STEAM_TAGS.keys()]
        mk.add(*btns)
        try:
            bot.edit_message_text("🎯 **Выберите категорию:**", chat_id, c.message.message_id, parse_mode='Markdown', reply_markup=mk)
        except:
            utils.safe_send_message(chat_id, "🎯 **Выберите категорию:**", parse_mode='Markdown', reply_markup=mk)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("genre_"))
    def genre_search(c):
        global LAST_GENRE_MSGS
        chat_id = c.message.chat.id
        cid = str(chat_id)
        bot.answer_callback_query(c.id, "🔍 Ищу игры...")

        if cid in LAST_GENRE_MSGS:
            for msg_id in LAST_GENRE_MSGS[cid]:
                try: bot.delete_message(chat_id, msg_id)
                except: pass
        LAST_GENRE_MSGS[cid] = []

        try: bot.delete_message(chat_id, c.message.message_id)
        except: pass

        wait_msg = utils.safe_send_message(chat_id, "⏳ **Ищу игры по жанру, подождите...**", parse_mode='Markdown')

        parts = c.data.split('_')
        g, offset = parts[1], int(parts[2])
        tag = STEAM_TAGS.get(g)

        if not tag: 
            if wait_msg: 
                try: bot.delete_message(chat_id, wait_msg.message_id)
                except: pass
            return

        # 🔥 Делаем случайную стартовую страницу для бесконечного разнообразия
        if offset == 0:
            offset = random.choice([0, 15, 30, 45, 60])

        games = search_steam_by_tag(tag, offset)

        if wait_msg: 
            try: bot.delete_message(chat_id, wait_msg.message_id)
            except: pass

        if not games:
             utils.safe_send_message(chat_id, f"😔 Игр в жанре **{g}** пока не нашел или ошибка Steam.")
             return

        user_curr = get_user_currency(chat_id)

        for gm in games:
            clean_title = re.sub(r'[^\w\s]', '', safe_translate(gm['title'])).strip()
            url = f"https://www.cheapshark.com/api/1.0/games?title={clean_title}&limit=1"
            try:
                res = requests.get(url, timeout=5).json()
                if res:
                    gid = res[0]['gameID']
                    deals = get_game_multi_store_deals(gid, user_curr)
                    if deals and deals['deals']:
                        best = deals['deals'][0]
                        caption = f"🎮 **{clean_md(gm['title'])}**\n🏆 Лучшая цена: **{best['price']}** ({clean_md(best['store'])})"
                        mk = types.InlineKeyboardMarkup()
                        mk.add(types.InlineKeyboardButton(f"🛒 Купить ({best['price']})", url=best['url']))
                        mk.add(types.InlineKeyboardButton("➕ В шорт-лист", callback_data=f"wish_{gid}"))

                        try:
                            sent_msg = bot.send_photo(chat_id, gm['thumb'], caption=caption, parse_mode='Markdown', reply_markup=mk)
                            if sent_msg: LAST_GENRE_MSGS[cid].append(sent_msg.message_id)
                        except:
                            sent_msg = utils.safe_send_message(chat_id, caption, parse_mode='Markdown', reply_markup=mk)
                            if sent_msg: LAST_GENRE_MSGS[cid].append(sent_msg.message_id)
                        continue
            except: pass

            mk = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Steam", url=gm['url']))
            try:
                sent_msg = bot.send_photo(chat_id, gm['thumb'], caption=f"🎮 **{clean_md(gm['title'])}**", parse_mode='Markdown', reply_markup=mk)
                if sent_msg: LAST_GENRE_MSGS[cid].append(sent_msg.message_id)
            except:
                sent_msg = utils.safe_send_message(chat_id, f"🎮 **{clean_md(gm['title'])}**", parse_mode='Markdown', reply_markup=mk)
                if sent_msg: LAST_GENRE_MSGS[cid].append(sent_msg.message_id)

        if not is_user_vip(chat_id):
            active_ad = database.get_active_ad()
            if active_ad:
                ad_msg = utils.safe_send_message(chat_id, f"➖➖➖➖➖➖➖\n{active_ad['text']}", parse_mode='Markdown')
                if ad_msg: 
                    LAST_GENRE_MSGS[cid].append(ad_msg.message_id)
                    database.add_ad_view() # 🔥 ДОБАВЛЯЕМ ПРОСМОТР РЕКЛАМЫ

        mk = types.InlineKeyboardMarkup(row_width=1)
        mk.add(types.InlineKeyboardButton("➡️ Дальше", callback_data=f"genre_{g}_{offset+15}"))
        mk.add(types.InlineKeyboardButton("🎭 Сменить жанр", callback_data="back_to_genres"))

        btn_msg = utils.safe_send_message(chat_id, "Еще игры?", reply_markup=mk)
        if btn_msg: LAST_GENRE_MSGS[cid].append(btn_msg.message_id)