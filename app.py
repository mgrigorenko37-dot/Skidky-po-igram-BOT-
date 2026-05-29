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

# ── MAIN ──
@app.route('/')
def index():
    return render_template('index.html')

# ── SEARCH ──
@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'error': 'too_short'}), 400
    try:
        r = requests.get(
            'https://www.cheapshark.com/api/1.0/games',
            params={'title': q, 'limit': 20},
            timeout=8
        )
        games = r.json()
        return jsonify([{
            'id': g.get('gameID'),
            'title': g.get('external', ''),
            'thumb': g.get('thumb', ''),
            'cheapest': g.get('cheapest', 'N/A'),
            'deal_id': g.get('cheapestDealID', ''),
            'deal_url': f"https://www.cheapshark.com/redirect?dealID={g.get('cheapestDealID','')}"
        } for g in games[:15]])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── DEALS ──
@app.route('/api/deals')
def api_deals():
    page   = int(request.args.get('page', 0))
    min_sv = int(request.args.get('min_savings', 0))
    max_px = request.args.get('max_price', 60)
    store  = request.args.get('store', '')
    sort   = request.args.get('sort', 'Savings')
    try:
        params = {
            'upperPrice': max_px,
            'sortBy': sort,
            'pageSize': 25,
            'pageNumber': page,
            'lowerPrice': 0.01
        }
        if store:
            params['storeID'] = store
        r = requests.get('https://www.cheapshark.com/api/1.0/deals', params=params, timeout=8)
        deals = r.json()
        results = []
        for d in deals:
            sv = float(d.get('savings', 0))
            if sv < min_sv:
                continue
            results.append({
                'id': d.get('dealID'),
                'title': d.get('title', ''),
                'thumb': d.get('thumb', ''),
                'sale_price': d.get('salePrice', '0'),
                'normal_price': d.get('normalPrice', '0'),
                'savings': round(sv),
                'metacritic': d.get('metacriticScore', '0'),
                'steam_rating': d.get('steamRatingText', ''),
                'steam_rating_pct': d.get('steamRatingPercent', ''),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── FREE GAMES ──
@app.route('/api/free')
def api_free():
    try:
        r = requests.get(
            'https://www.cheapshark.com/api/1.0/deals',
            params={'upperPrice': 0, 'sortBy': 'recent', 'pageSize': 30},
            timeout=8
        )
        deals = r.json()
        results = []
        for d in deals:
            if float(d.get('salePrice', 1)) == 0:
                results.append({
                    'id': d.get('dealID'),
                    'title': d.get('title', ''),
                    'thumb': d.get('thumb', ''),
                    'normal_price': d.get('normalPrice', '0'),
                    'metacritic': d.get('metacriticScore', '0'),
                    'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
                })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GAME DETAIL ──
@app.route('/api/game/<game_id>')
def api_game_detail(game_id):
    try:
        r = requests.get(
            f'https://www.cheapshark.com/api/1.0/games',
            params={'id': game_id},
            timeout=8
        )
        data = r.json()
        deals = []
        stores_r = requests.get('https://www.cheapshark.com/api/1.0/stores', timeout=5)
        stores_map = {str(s['storeID']): s['storeName'] for s in stores_r.json()}
        for d in data.get('deals', []):
            deals.append({
                'store': stores_map.get(str(d.get('storeID')), f"Store {d.get('storeID')}"),
                'store_id': d.get('storeID'),
                'sale_price': d.get('price', '0'),
                'normal_price': d.get('retailPrice', '0'),
                'savings': round(float(d.get('savings', 0))),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
            })
        deals.sort(key=lambda x: float(x['sale_price']))
        info = data.get('info', {})
        return jsonify({
            'title': info.get('title', ''),
            'thumb': info.get('thumb', ''),
            'metacritic': info.get('metacriticScore', '0'),
            'metacritic_link': info.get('metacriticLink', ''),
            'steam_rating': info.get('steamRatingText', ''),
            'steam_rating_pct': info.get('steamRatingPercent', ''),
            'cheapest_price': info.get('cheapestPriceEver', {}).get('price', ''),
            'deals': deals
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GENRE GAMES ──
@app.route('/api/genre')
def api_genre():
    tag = request.args.get('tag', '')
    page = int(request.args.get('page', 0))
    if not tag:
        return jsonify({'error': 'no_tag'}), 400
    try:
        r = requests.get(
            'https://www.cheapshark.com/api/1.0/deals',
            params={'sortBy': 'Reviews', 'pageSize': 20, 'pageNumber': page, 'upperPrice': 60},
            timeout=8
        )
        deals = r.json()
        results = []
        for d in deals:
            sv = float(d.get('savings', 0))
            results.append({
                'id': d.get('dealID'),
                'title': d.get('title', ''),
                'thumb': d.get('thumb', ''),
                'sale_price': d.get('salePrice', '0'),
                'normal_price': d.get('normalPrice', '0'),
                'savings': round(sv),
                'steam_rating_pct': d.get('steamRatingPercent', '0'),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
            })
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── STORES ──
@app.route('/api/stores')
def api_stores():
    try:
        r = requests.get('https://www.cheapshark.com/api/1.0/stores', timeout=6)
        stores = r.json()
        return jsonify([{
            'id': str(s['storeID']),
            'name': s['storeName'],
            'active': s.get('isActive', 1)
        } for s in stores if s.get('isActive', 1)])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── WISHLIST ──
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

# ── PROFILE ──
@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            user  = conn.execute("SELECT reg_date FROM mining_users WHERE user_id = ?", (user_id,)).fetchone()
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

# ── CURRENCY SETTINGS ──
@app.route('/api/settings/<int:user_id>', methods=['POST'])
def api_settings_update(user_id):
    data = request.get_json(force=True)
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("INSERT OR IGNORE INTO user_news_prefs (user_id) VALUES (?)", (user_id,))
            if 'currency' in data:
                conn.execute("UPDATE user_news_prefs SET currency = ? WHERE user_id = ?", (data['currency'], user_id))
            if 'want_news' in data:
                conn.execute("UPDATE user_news_prefs SET want_news = ? WHERE user_id = ?", (int(data['want_news']), user_id))
            if 'want_freebies' in data:
                conn.execute("UPDATE user_news_prefs SET want_freebies = ? WHERE user_id = ?", (int(data['want_freebies']), user_id))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    database.init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
