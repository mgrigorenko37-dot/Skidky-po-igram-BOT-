from flask import Flask, render_template, jsonify, request
import sqlite3
import requests
import os
from datetime import datetime
import config
import database

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'error': 'too_short'}), 400
    try:
        url = f"https://www.cheapshark.com/api/1.0/games?title={requests.utils.quote(q)}&limit=15"
        r = requests.get(url, timeout=8)
        games = r.json()
        results = []
        for g in games[:12]:
            results.append({
                'id': g.get('gameID'),
                'title': g.get('external', 'Unknown'),
                'thumb': g.get('thumb', ''),
                'cheapest': g.get('cheapest', 'N/A'),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={g.get('cheapestDealID', '')}"
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/deals')
def api_deals():
    page = int(request.args.get('page', 0))
    try:
        url = f"https://www.cheapshark.com/api/1.0/deals?upperPrice=60&sortBy=Savings&pageSize=20&pageNumber={page}"
        r = requests.get(url, timeout=8)
        deals = r.json()
        results = []
        for d in deals:
            savings = float(d.get('savings', 0))
            if savings < 30:
                continue
            results.append({
                'id': d.get('dealID'),
                'title': d.get('title', 'Unknown'),
                'thumb': d.get('thumb', ''),
                'sale_price': d.get('salePrice', '0'),
                'normal_price': d.get('normalPrice', '0'),
                'savings': round(savings),
                'metacritic': d.get('metacriticScore', '0'),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID', '')}"
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>', methods=['GET'])
def api_wishlist_get(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT game_name, last_price FROM wishlist WHERE user_id = ? ORDER BY rowid DESC",
                (user_id,)
            ).fetchall()
        return jsonify([{'name': r[0], 'last_price': r[1]} for r in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>', methods=['POST'])
def api_wishlist_add(user_id):
    data = request.get_json(force=True)
    game_name = data.get('name', '').strip()
    if not game_name:
        return jsonify({'error': 'no_name'}), 400
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            count = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id = ?", (user_id,)).fetchone()[0]
            vip = conn.execute(
                "SELECT 1 FROM user_news_prefs WHERE user_id = ? AND premium_until > datetime('now')", (user_id,)
            ).fetchone()
            limit = 100 if vip else 5
            if count >= limit:
                return jsonify({'error': 'limit', 'limit': limit, 'vip': bool(vip)}), 400
            conn.execute(
                "INSERT OR IGNORE INTO wishlist (user_id, game_name, last_price) VALUES (?, ?, ?)",
                (user_id, game_name, None)
            )
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>/<path:game_name>', methods=['DELETE'])
def api_wishlist_delete(user_id, game_name):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM wishlist WHERE user_id = ? AND game_name = ?", (user_id, game_name))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            user = conn.execute("SELECT reg_date, referrer_id FROM mining_users WHERE user_id = ?", (user_id,)).fetchone()
            prefs = conn.execute(
                "SELECT premium_until, currency, want_news, want_freebies FROM user_news_prefs WHERE user_id = ?", (user_id,)
            ).fetchone()
            wishlist_count = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id = ?", (user_id,)).fetchone()[0]
            referrals = conn.execute("SELECT COUNT(*) FROM mining_users WHERE referrer_id = ?", (user_id,)).fetchone()[0]

        is_vip = False
        premium_until = None
        currency = 'USD'
        want_news = True
        want_freebies = True

        if prefs:
            premium_until = prefs[0]
            currency = prefs[1] or 'USD'
            want_news = bool(prefs[2])
            want_freebies = bool(prefs[3])
            if premium_until:
                try:
                    dt = datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S')
                    is_vip = dt > datetime.utcnow()
                except:
                    pass

        return jsonify({
            'user_id': user_id,
            'reg_date': user[0] if user else None,
            'is_vip': is_vip,
            'premium_until': premium_until if is_vip else None,
            'currency': currency,
            'want_news': want_news,
            'want_freebies': want_freebies,
            'wishlist_count': wishlist_count,
            'referrals': referrals
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    database.init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
