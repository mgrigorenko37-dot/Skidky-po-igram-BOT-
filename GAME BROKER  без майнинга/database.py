import sqlite3
import logging
import config
from datetime import datetime, timedelta

# Настраиваем логгер
logger = logging.getLogger(__name__)

def init_db():
    """
    Инициализация базы данных.
    Создает таблицы и обновляет структуру при необходимости.
    """
    print("⚙️ Проверка структуры базы данных...")
    try:
        with sqlite3.connect(config.DB_FILE, check_same_thread=False) as conn:
            cursor = conn.cursor()

            # --- 1. Создание таблиц (если нет) ---

            # База пользователей (Используем таблицу mining_users как основную для совместимости, но переименуем логику)
            cursor.execute('''CREATE TABLE IF NOT EXISTS mining_users (
                user_id INTEGER PRIMARY KEY,
                reg_date TEXT,
                referrer_id INTEGER DEFAULT 0,
                last_active_date TEXT DEFAULT CURRENT_TIMESTAMP
            )''')

            # Вишлист
            cursor.execute('''CREATE TABLE IF NOT EXISTS wishlist 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, game_name TEXT, last_price REAL, UNIQUE(user_id, game_name))''')

            # Магазины
            cursor.execute('''CREATE TABLE IF NOT EXISTS user_stores (user_id INTEGER, store_id TEXT, UNIQUE(user_id, store_id))''')

            # Настройки (VIP-ПОДПИСКА И АВТОПРОДЛЕНИЕ)
            cursor.execute('''CREATE TABLE IF NOT EXISTS user_news_prefs 
                (user_id INTEGER PRIMARY KEY, want_news INTEGER DEFAULT 1, want_freebies INTEGER DEFAULT 1, 
                 is_supporter INTEGER DEFAULT 0, referrer_id INTEGER, currency TEXT DEFAULT 'USD',
                 premium_until DATETIME, auto_renew INTEGER DEFAULT 0)''')

            # Отправленные новости
            cursor.execute('''CREATE TABLE IF NOT EXISTS sent_news (news_id TEXT PRIMARY KEY)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS posted_deals (game_id TEXT PRIMARY KEY, date_sent TEXT)''')

            # 🔥 ТАБЛИЦА ДЛЯ РЕКЛАМНОЙ КАМПАНИИ (ДОБАВЛЕНЫ ПРОСМОТРЫ)
            cursor.execute('''CREATE TABLE IF NOT EXISTS ad_campaign (
                id INTEGER PRIMARY KEY DEFAULT 1, 
                ad_text TEXT, 
                expires_at DATETIME,
                views INTEGER DEFAULT 0
            )''')

            # 🔥 ТАБЛИЦА ИСТОРИИ ПРОСМОТРОВ СКИДОК
            cursor.execute('''CREATE TABLE IF NOT EXISTS viewed_deals (
                user_id INTEGER,
                deal_id TEXT,
                viewed_at DATETIME,
                UNIQUE(user_id, deal_id)
            )''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_viewed_user ON viewed_deals(user_id)")

            # ВАЖНО: Сохраняем структуру перед миграциями
            conn.commit()

            # --- 2. АВТО-ЛЕЧЕНИЕ (Добавление колонок в старую базу) ---

            cursor.execute("PRAGMA table_info(user_news_prefs)")
            prefs_cols = [col[1] for col in cursor.fetchall()]
            if "premium_until" not in prefs_cols:
                try:
                    print("🔧 Лечу базу: добавляю колонку premium_until (VIP подписка)...")
                    cursor.execute("ALTER TABLE user_news_prefs ADD COLUMN premium_until DATETIME")
                except Exception as e:
                    logger.error(f"Migration error for premium_until: {e}")
            if "auto_renew" not in prefs_cols:
                try:
                    cursor.execute("ALTER TABLE user_news_prefs ADD COLUMN auto_renew INTEGER DEFAULT 0")
                except: pass

            cursor.execute("PRAGMA table_info(ad_campaign)")
            ad_cols = [col[1] for col in cursor.fetchall()]
            if "views" not in ad_cols:
                try:
                    cursor.execute("ALTER TABLE ad_campaign ADD COLUMN views INTEGER DEFAULT 0")
                except: pass

            # 🔥 ИСПРАВЛЕННЫЙ БЛОК МИГРАЦИИ
            cursor.execute("PRAGMA table_info(mining_users)")
            user_cols = [col[1] for col in cursor.fetchall()]
            if "last_active_date" not in user_cols:
                try:
                    print("🔧 Лечу базу: добавляю колонку last_active_date...")
                    # Создаем пустую колонку (SQLite это разрешает)
                    cursor.execute("ALTER TABLE mining_users ADD COLUMN last_active_date TEXT")
                    # Заполняем её текущим временем, чтобы не было пустых (NULL) значений
                    cursor.execute("UPDATE mining_users SET last_active_date = CURRENT_TIMESTAMP")
                except Exception as e:
                    print(f"❌ Ошибка миграции last_active_date: {e}")

            conn.commit()
            print("✅ База данных проверена и готова к работе (Оптимизировано для Game Broker).")

    except Exception as e:
        logger.error(f"Database init error: {e}")
        print(f"❌ Ошибка инициализации БД: {e}")

# --- ФУНКЦИИ АКТИВНОСТИ ---

def update_user_activity(user_id):
    """Обновляет время последней активности пользователя для подсчета DAU."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE mining_users SET last_active_date = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating user activity: {e}")

# --- ФУНКЦИИ ИСТОРИИ ПРОСМОТРОВ ---

def mark_deal_viewed(user_id, deal_id):
    """Отмечает игру как просмотренную пользователем."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("INSERT OR IGNORE INTO viewed_deals (user_id, deal_id, viewed_at) VALUES (?, ?, ?)", (user_id, str(deal_id), now))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error marking deal viewed: {e}")
        return False

def is_deal_viewed(user_id, deal_id):
    """Проверяет, видел ли пользователь уже эту игру."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM viewed_deals WHERE user_id = ? AND deal_id = ?", (user_id, str(deal_id)))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking viewed deal: {e}")
        return False

def clear_viewed_deals(user_id):
    """Очищает историю просмотров пользователя."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM viewed_deals WHERE user_id = ?", (user_id,))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error clearing viewed deals: {e}")
        return False

# --- ФУНКЦИИ (ДИНАМИЧЕСКАЯ РЕКЛАМА) ---

def set_active_ad(text, days=None):
    """Устанавливает рекламный текст. Если text=None, удаляет рекламу."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            if text is None:
                cursor.execute("DELETE FROM ad_campaign WHERE id = 1")
            else:
                expires_at = (datetime.utcnow() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S') if days else None
                # При установке новой рекламы сбрасываем просмотры
                cursor.execute("REPLACE INTO ad_campaign (id, ad_text, expires_at, views) VALUES (1, ?, ?, 0)", (text, expires_at))
            conn.commit()
            return True
    except Exception as e:
        logger.error(f"Error setting ad: {e}")
        return False

def add_ad_view():
    """Увеличивает счетчик показов рекламы на 1."""
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE ad_campaign SET views = views + 1 WHERE id = 1")
            conn.commit()
    except Exception as e:
        logger.error(f"Error adding ad view: {e}")

def get_active_ad():
    """
    Возвращает словарь {'text': str, 'expires_at': datetime/None, 'views': int} 
    или None, если рекламы нет или она истекла.
    """
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ad_text, expires_at, views FROM ad_campaign WHERE id = 1")
            row = cursor.fetchone()

            if row and row[0]:
                ad_text = row[0]
                expires_at_str = row[1]
                views = row[2] if row[2] else 0

                # Если есть таймер, проверяем, не истек ли он
                if expires_at_str:
                    expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
                    if datetime.utcnow() > expires_at:
                        set_active_ad(None) # Удаляем просроченную рекламу
                        return None
                    return {'text': ad_text, 'expires_at': expires_at, 'views': views}

                # Реклама без таймера (вечная)
                return {'text': ad_text, 'expires_at': None, 'views': views}
    except Exception as e:
        logger.error(f"Error getting ad: {e}")
    return None

# --- 🚀 [NEW] ЦЕНТРАЛИЗОВАННАЯ СТАТИСТИКА (GAME BROKER) ---
def get_comprehensive_stats():
    """
    Собирает всю статистику проекта (Аудитория, VIP, Активность, Реклама) в один словарь.
    """
    stats = {}
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            cursor = conn.cursor()

            # 1. АУДИТОРИЯ
            stats['total_users'] = cursor.execute("SELECT COUNT(*) FROM mining_users").fetchone()[0]

            # 🔥 БЕЗОПАСНЫЙ ПОДСЧЕТ DAU
            try:
                dau_query = """
                    SELECT COUNT(*) FROM mining_users 
                    WHERE last_active_date >= datetime('now', '-1 day') 
                    OR reg_date >= datetime('now', '-1 day')
                """
                stats['dau'] = cursor.execute(dau_query).fetchone()[0]
            except Exception:
                stats['dau'] = 0

            stats['new_today'] = cursor.execute("SELECT COUNT(*) FROM mining_users WHERE reg_date >= date('now')").fetchone()[0]

            # 2. ШОРТ-ЛИСТЫ (Польза)
            stats['total_wishlist_items'] = cursor.execute("SELECT COUNT(*) FROM wishlist").fetchone()[0]
            stats['unique_wishlist_users'] = cursor.execute("SELECT COUNT(DISTINCT user_id) FROM wishlist").fetchone()[0]

            # 3. VIP СТАТУС (Монетизация)
            vip_query = "SELECT COUNT(*) FROM user_news_prefs WHERE premium_until IS NOT NULL AND premium_until > datetime('now')"
            stats['active_vips'] = cursor.execute(vip_query).fetchone()[0]

            # 4. РЕКЛАМНАЯ КАМПАНИЯ
            try:
                ad_row = cursor.execute("SELECT expires_at, views FROM ad_campaign WHERE id = 1").fetchone()
                if ad_row:
                    stats['ad_active'] = True
                    stats['ad_expires'] = ad_row[0] if ad_row[0] else "Бессрочно"
                    stats['ad_views'] = ad_row[1] if ad_row[1] else 0
                else:
                    stats['ad_active'] = False
                    stats['ad_expires'] = "—"
                    stats['ad_views'] = 0
            except Exception:
                stats['ad_active'] = False
                stats['ad_expires'] = "—"
                stats['ad_views'] = 0

            # 5. ИСТОРИЯ РАССЫЛОК (Халява и Новости)
            stats['sent_news_count'] = cursor.execute("SELECT COUNT(*) FROM sent_news").fetchone()[0]

    except Exception as e:
        logger.error(f"Stats Error: {e}")
        return None

    return stats