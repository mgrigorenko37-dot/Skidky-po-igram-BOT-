import os

# ==========================================
# 🔐 1. ТОКЕНЫ И ID
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# 🔥 1 ПЛАТЕЖНЫЙ ШЛЮЗ
CRYPTO_BOT_TOKEN = os.environ.get('CRYPTO_PAY_API_KEY')

ADMIN_ID = os.environ.get('ADMIN_ID', '8463157443')
CHANNEL_ID = "@GameBroker_Official"
DB_FILE = "wishlist.db"

CURRENCY_SIGNS = {
    "USD": "$", "RUB": "₽", "KZT": "₸", "BYN": "Br",
    "UAH": "₴", "UZS": "so'm", "KGS": "с", "AMD": "֏", "AZN": "₼", "TJS": "som"
}

# 💱 КУРСЫ ВАЛЮТ
EXCHANGE_RATES = {
    "USD": 1.0, "RUB": 100.0, "KZT": 520.0, "BYN": 3.3,
    "UAH": 42.0, "UZS": 12800.0, "KGS": 87.0, "AMD": 390.0, "AZN": 1.7, "TJS": 11.0
}

# 👇 ИЗМЕНИЛ ССЫЛКУ НИЖЕ НА РАБОЧУЮ (StopGame)
RSS_NEWS = "https://3dnews.ru/games/rss/"
RSS_FREEBIES = "https://freesteam.ru/feed/"

ADMITAD_SUBID = "game_broker_bot"
GGSEL_AFF_LINK = "https://xnmik.com/g/ngv70om7ow2992f3b792768e16fdce/?erid=2bL9aMPo2e49hMef4phyrMWkN2&ulp="

# --- ПОЛНЫЙ СПИСОК МАГАЗИНОВ CHEAPSHARK ---
SUPPORTED_STORES = {
    "1": "Steam", "2": "GamersGate", "3": "GreenManGaming", "4": "Amazon", "5": "GameStop", 
    "6": "Direct2Drive", "7": "GOG", "8": "Origin", "9": "Get Games", "10": "Shiny Loot", 
    "11": "Humble Store", "12": "Desura", "13": "Uplay", "14": "IndieGameStand", "15": "Fanatical", 
    "16": "Gamesrocket", "17": "Games Republic", "18": "SilaGames", "19": "Playfield", "20": "ImperialGames", 
    "21": "WinGameStore", "22": "FunStockDigital", "23": "GameBillet", "24": "Voidu", "25": "Epic Games", 
    "26": "Razer Game Store", "27": "Gamesplanet", "28": "Gamesload", "29": "2Game", "30": "IndieGala", 
    "31": "Blizzard Shop", "32": "AllYouPlay", "33": "DLGamer", "34": "Itch.io", "35": "Noctre"
}
PARTNER_LINKS = {str(i): "" for i in range(1, 36)}
GENRES = {
    "Action": "⚔️ Экшен", "RPG": "🧙‍♂️ РПГ", "Strategy": "🧠 Стратегии",
    "Adventure": "🗺️ Приключения", "Shooter": "🔫 Шутеры", "Horror": "👻 Хорроры",
    "Simulation": "🚜 Симуляторы", "Survival": "🏕️ Выживание", "Racing": "🏎️ Гонки",
    "Fighting": "🥊 Файтинги", "Sports": "⚽ Спорт", "Puzzle": "🧩 Головоломки",
    "Indie": "🎨 Инди", "MMO": "👥 ММО", "Platformer": "🏃 Платформеры",
    "Cyberpunk": "🤖 Киберпанк", "Souls-like": "🔥 Хардкор (Souls)", "Co-op": "🤝 Кооператив"
}