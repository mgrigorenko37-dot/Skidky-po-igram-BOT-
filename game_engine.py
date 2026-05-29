import requests
import logging
from bs4 import BeautifulSoup
from urllib.parse import quote
import config

# Настраиваем логгер
logger = logging.getLogger(__name__)

# ==========================================
# 🎮 ДВИЖОК ПОИСКА ИГР (ПАРСЕР)
# ==========================================

def search_game_prices(game_name):
    """
    Ищет цены на игру в поддерживаемых магазинах.
    Возвращает список словарей: {'store': 'Steam', 'price': '10.00', 'link': '...'}
    """
    results = []

    # 1. Поиск в Steam (через API или парсинг)
    steam_price = get_steam_price(game_name)
    if steam_price:
        results.append(steam_price)

    # 2. Поиск на GGsel (партнерка)
    ggsel_link = f"{config.GGSEL_AFF_LINK}{quote('https://ggsel.net/catalog?q=' + game_name)}"
    results.append({
        'store': 'GGsel (Keys)',
        'price': 'Проверить', # Цену сложно вытянуть без API, отправляем юзера
        'link': ggsel_link,
        'flag': '🔑'
    })

    # 3. GabeStore (Пример парсинга)
    # Можно добавить другие магазины тут

    return results

def get_steam_price(game_name):
    """
    Получает цену из Steam (пример через поиск)
    """
    try:
        url = f"https://store.steampowered.com/search/?term={quote(game_name)}&cc=us"
        cookies = {'birthtime': '568022401'} # Обход проверки возраста
        r = requests.get(url, cookies=cookies, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)

        soup = BeautifulSoup(r.text, 'html.parser')
        search_row = soup.find('a', class_='search_result_row')

        if search_row:
            title = search_row.find('span', class_='title').text
            price_div = search_row.find('div', class_='search_price')

            # Проверяем скидку
            if 'discounted' in price_div.get('class', []):
                price_text = price_div.text.split('$')[-1].strip() + "$"
            else:
                price_text = price_div.text.strip()

            link = search_row['href']

            return {
                'store': 'Steam',
                'price': price_text,
                'link': link,
                'flag': '🇺🇸'
            }
    except Exception as e:
        logger.error(f"Steam parse error: {e}")
    return None

def get_game_image(game_name):
    """
    Ищет картинку игры для красивого вывода
    """
    try:
        url = f"https://store.steampowered.com/search/?term={quote(game_name)}"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(r.text, 'html.parser')
        img_tag = soup.find('img')
        if img_tag:
            return img_tag['src']
    except:
        pass
    return None