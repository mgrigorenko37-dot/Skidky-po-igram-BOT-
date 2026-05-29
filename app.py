from flask import Flask, render_template, jsonify
import config  # <--- Самое важное: импортируем настройки бота

app = Flask(__name__)

# Помощник для оформления (цвета и эмодзи)
def get_tier_style(tier_id):
    styles = {
        1: {"color": "success", "emoji": "👶"}, # Новичок
        2: {"color": "info",    "emoji": "👨‍💻"}, # Любитель
        3: {"color": "warning", "emoji": "🧑‍🔧"}, # Профи
        4: {"color": "danger",  "emoji": "👨‍🏫"}, # Элита
        5: {"color": "dark",    "emoji": "🏆"}, # Легенда
        6: {"color": "primary", "emoji": "👔"}, # Бизнесмен
        7: {"color": "secondary", "emoji": "🎩"}, # Миллионер
        8: {"color": "dark",    "emoji": "👑"}  # Миллиардер
    }
    return styles.get(tier_id, {"color": "secondary", "emoji": "📦"})

def get_levels_from_config():
    """
    Создает список уровней для сайта на основе config.py
    """
    levels = {}

    # Читаем словарь TIERS_CONFIG из конфига
    for tier_id, data in config.TIERS_CONFIG.items():
        style = get_tier_style(tier_id)

        # Считаем примерное кол-во боксов (условно: цена уровня / цена бокса)
        # Это для красоты, чтобы на сайте были "палочки" сложности
        estimated_boxes = int(data['price'] * 2) 

        levels[data['name']] = {
            "id": tier_id,
            "price": data['price'],        # БЕРЕМ ЦЕНУ ИЗ БОТА (USDT)
            "description": f"Доход: ${data['income']} в день",
            "emoji": style['emoji'],
            "color": style['color'],
            "boxes": estimated_boxes # Для визуализации прогресса
        }
    return levels

@app.route('/')
def index():
    # Генерируем данные на лету
    dynamic_levels = get_levels_from_config()
    return render_template('index.html', levels=dynamic_levels)

@app.route('/api/levels')
def api_levels():
    # API тоже отдает актуальные данные
    return jsonify(get_levels_from_config())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)