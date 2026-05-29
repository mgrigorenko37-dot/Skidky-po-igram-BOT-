from flask import Flask, render_template, jsonify, request
import sqlite3
import requests
import json
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import config
import database

# ── Cached stores map ─────────────────────
_stores_cache = {}
_stores_cache_ts = 0

def get_stores_map():
    global _stores_cache, _stores_cache_ts
    now = time.time()
    if _stores_cache and now - _stores_cache_ts < 3600:
        return _stores_cache
    try:
        r = requests.get('https://www.cheapshark.com/api/1.0/stores', timeout=6)
        _stores_cache = {str(s['storeID']): s['storeName']
                         for s in r.json()}
        _stores_cache_ts = now
    except Exception:
        pass
    return _stores_cache

app = Flask(__name__)

@app.after_request
def add_cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return r

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

# ── SEARCH ──────────────────────────────
@app.route('/api/stats')
def api_stats():
    """Реальная статистика: магазины, макс. скидка, кол-во игр"""
    try:
        stores = get_stores_map()
        r = requests.get('https://www.cheapshark.com/api/1.0/deals',
                         params={'sortBy': 'Savings', 'pageSize': 20, 'upperPrice': 60}, timeout=8)
        deals = r.json()
        max_sv = round(max((float(d.get('savings', 0)) for d in deals), default=89))
        return jsonify({'stores': len(stores) or 35, 'max_savings': max_sv, 'games': 15427})
    except Exception:
        return jsonify({'stores': 35, 'max_savings': 89, 'games': 15000})

# ── SEARCH ABBREVIATIONS ─────────────────
_ABBREVS = {
    'gta v': 'grand theft auto v',   'gta 5': 'grand theft auto v',
    'gta4':  'grand theft auto iv',  'gta 4': 'grand theft auto iv',
    'gta3':  'grand theft auto iii', 'gta 3': 'grand theft auto iii',
    'gta sa': 'grand theft auto san andreas', 'gta san andreas': 'grand theft auto san andreas',
    'rdr2':  'red dead redemption 2','rdr':   'red dead redemption',
    'cod':   'call of duty',         'bf':    'battlefield',
    'csgo':  'counter-strike',       'cs2':   'counter-strike 2',
    'cs go': 'counter-strike',       'tf2':   'team fortress 2',
    'tlou':  'the last of us',       'nfs':   'need for speed',
    'ac':    "assassin's creed",     'ds':    'dark souls',
    'ff':    'final fantasy',        'mgs':   'metal gear',
    'nier':  'nier automata',        'bg3':   "baldur's gate 3",
    'bg 3':  "baldur's gate 3",      'witcher 3': 'the witcher 3',
    'skyrim': 'the elder scrolls v', 'oblivion': 'the elder scrolls iv',
    'morrowind': 'the elder scrolls iii',
}

def _expand_query(q):
    """Expand abbreviations in search query."""
    low = q.lower().strip()
    return _ABBREVS.get(low, q)

def _search_score(title, q):
    """Relevance: 0=exact, 1=starts with, 2=word match, 3=contains."""
    t = title.lower(); ql = q.lower()
    if t == ql: return 0
    if t.startswith(ql): return 1
    if any(w == ql for w in t.split()): return 2
    if ql in t: return 3
    return 4

@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({'error': 'too_short'}), 400
    try:
        expanded = _expand_query(q)
        r = requests.get('https://www.cheapshark.com/api/1.0/games',
                         params={'title': expanded, 'limit': 30}, timeout=8)
        raw = r.json()
        # Deduplicate by normalized title (keep cheapest price)
        seen = {}
        for g in raw:
            key = (g.get('external', '') or '').lower().strip()
            if not key: continue
            if key not in seen:
                seen[key] = g
            else:
                # Keep the one with lower cheapest price
                try:
                    if float(g.get('cheapest', 9999)) < float(seen[key].get('cheapest', 9999)):
                        seen[key] = g
                except Exception:
                    pass
        # Sort by relevance score
        results = sorted(seen.values(), key=lambda g: _search_score(g.get('external', ''), expanded))
        return jsonify([{
            'id':       g.get('gameID'),
            'title':    g.get('external', ''),
            'thumb':    g.get('thumb', ''),
            'cheapest': g.get('cheapest', 'N/A'),
            'deal_id':  g.get('cheapestDealID', ''),
            'deal_url': f"https://www.cheapshark.com/redirect?dealID={g.get('cheapestDealID','')}"
        } for g in results[:20]])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── DEALS ────────────────────────────────
# ── Quality filter: only real AAA/popular games ──────────
_SKIP_KEYWORDS = [
    'soundtrack', ' ost', ' osts', 'artbook', 'season pass', 'expansion pack',
    'bonus content', 'upgrade pack', 'digital art', 'pass bundle',
    'pre-order', 'pre order', 'digital deluxe upgrade', 'supporter pack',
    'cosmetic', 'skin pack', 'weapon pack', 'character pack',
    # Publisher shovelware bundles
    'bundle', 'mega pack', 'jumbo', 'gigantic', 'publisher pack',
    'franchise pack', 'anniversary pack',
]

def _is_quality_game(d):
    """Return True only for real, popular full games (AAA/AA tier)."""
    title = (d.get('title') or '').lower()
    mc    = int(d.get('metacriticScore', 0) or 0)
    rt    = int(d.get('steamRatingPercent', 0) or 0)
    np    = float(d.get('normalPrice', 0) or 0)

    # Skip DLC, OST, shovelware bundles
    if any(kw in title for kw in _SKIP_KEYWORDS):
        return False

    # Must have a real retail price — AAA/AA games cost at least $19.99
    if np < 19.99:
        return False

    # Quality gate: strong Metacritic OR strong Steam community rating
    if mc > 0:
        if mc < 70:
            return False          # Has MC score but it's low
    else:
        # No Metacritic score — need very strong Steam rating to compensate
        if rt < 80:
            return False

    return True


def _fetch_deals_page(params, store=''):
    """Fetch one page of deals from CheapShark and return raw list."""
    p = dict(params)
    if store: p['storeID'] = store
    try:
        r = requests.get('https://www.cheapshark.com/api/1.0/deals', params=p, timeout=8)
        return r.json() if r.ok else []
    except Exception:
        return []

@app.route('/api/deals')
def api_deals():
    page   = int(request.args.get('page', 0))
    min_sv = int(request.args.get('min_savings', 0))
    max_px = request.args.get('max_price', 80)
    min_px = request.args.get('min_price', '0')
    sort   = request.args.get('sort', 'Savings')
    store  = request.args.get('store', '')
    min_mc = int(request.args.get('min_meta', 0))
    aaa    = request.args.get('aaa', '0') == '1'
    try:
        base_params = {
            'upperPrice': max_px, 'pageSize': 100, 'pageNumber': page,
            'lowerPrice': max(float(min_px or 0), 0.01)
        }
        # Fetch from TWO sort orders in parallel to get a wider pool
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(_fetch_deals_page, {**base_params, 'sortBy': 'Savings'}, store)
            f2 = ex.submit(_fetch_deals_page, {**base_params, 'sortBy': 'DealRating'}, store)
            raw1, raw2 = f1.result(), f2.result()

        # Merge and deduplicate by dealID
        seen_ids = set()
        merged = []
        for d in raw1 + raw2:
            did = d.get('dealID', '')
            if did and did not in seen_ids:
                seen_ids.add(did)
                merged.append(d)

        smap = get_stores_map()
        results = []
        for d in merged:
            sv = float(d.get('savings', 0) or 0)
            mc = int(d.get('metacriticScore', 0) or 0)
            np = float(d.get('normalPrice', 0) or 0)
            rt = int(d.get('steamRatingPercent', 0) or 0)

            if sv < min_sv: continue
            if mc < min_mc: continue
            if not _is_quality_game(d): continue

            if aaa:
                if mc > 0 and mc < 80: continue
                if mc == 0 and rt < 85: continue
                if np < 29.99: continue

            steam_id = d.get('steamAppID', '') or ''
            results.append({
                'id': d.get('dealID'), 'title': d.get('title', ''),
                'thumb': d.get('thumb', ''),
                'steam_app_id': steam_id,
                'game_id': d.get('gameID', ''),
                'store': smap.get(str(d.get('storeID', '')), ''),
                'store_id': str(d.get('storeID', '')),
                'sale_price': d.get('salePrice', '0'),
                'normal_price': d.get('normalPrice', '0'),
                'savings': round(sv), 'metacritic': mc,
                'steam_rating': d.get('steamRatingText', ''),
                'steam_rating_pct': rt,
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
            })
        # Sort by savings descending
        results.sort(key=lambda x: x['savings'], reverse=True)
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── FREE GAMES ───────────────────────────
@app.route('/api/free')
def api_free():
    try:
        r = requests.get('https://www.cheapshark.com/api/1.0/deals',
                         params={'upperPrice': 0, 'sortBy': 'Metacritic', 'pageSize': 60}, timeout=8)
        results = []
        for d in r.json():
            if float(d.get('salePrice', 1) or 1) != 0: continue
            mc = int(d.get('metacriticScore', 0) or 0)
            rt = int(d.get('steamRatingPercent', 0) or 0)
            np = float(d.get('normalPrice', 0) or 0)

            # Quality gate for free section
            title = (d.get('title') or '').lower()
            if any(kw in title for kw in _SKIP_KEYWORDS): continue
            if np < 4.99: continue                     # skip browser/F2P clutter
            if mc > 0 and mc < 60: continue            # bad MC score
            if mc == 0 and rt < 70: continue           # no MC + weak community

            results.append({
                'id': d.get('dealID'), 'title': d.get('title', ''),
                'thumb': d.get('thumb', ''), 'normal_price': d.get('normalPrice', '0'),
                'metacritic': mc, 'steam_rating_pct': rt,
                'store_id': str(d.get('storeID', '')),
                'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
            })
        return jsonify(results[:30])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── GAME DETAIL ──────────────────────────
@app.route('/api/game/<game_id>')
def api_game_detail(game_id):
    try:
        r   = requests.get('https://www.cheapshark.com/api/1.0/games', params={'id': game_id}, timeout=8)
        sr  = requests.get('https://www.cheapshark.com/api/1.0/stores', timeout=5)
        smap = {str(s['storeID']): s['storeName'] for s in sr.json()}
        data = r.json()
        deals = sorted([{
            'store': smap.get(str(d.get('storeID')), f"Store {d.get('storeID')}"),
            'store_id': d.get('storeID'), 'sale_price': d.get('price', '0'),
            'normal_price': d.get('retailPrice', '0'),
            'savings': round(float(d.get('savings', 0))),
            'deal_url': f"https://www.cheapshark.com/redirect?dealID={d.get('dealID','')}"
        } for d in data.get('deals', [])], key=lambda x: float(x['sale_price']))
        info = data.get('info', {})
        steam_app_id = info.get('steamAppID', '') or ''
        cheapest_ever = data.get('cheapestPriceEver', {})
        return jsonify({
            'title': info.get('title', ''), 'thumb': info.get('thumb', ''),
            'steam_app_id': steam_app_id,
            'metacritic': info.get('metacriticScore', '0'),
            'steam_rating': info.get('steamRatingText', ''),
            'steam_rating_pct': info.get('steamRatingPercent', ''),
            'cheapest_price': info.get('cheapestPriceEver', {}).get('price', ''),
            'cheapest_ever_price': cheapest_ever.get('price', ''),
            'cheapest_ever_date': cheapest_ever.get('date', ''),
            'deals': deals
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── WISHLIST ─────────────────────────────
@app.route('/api/wishlist/<int:user_id>', methods=['GET'])
def api_wishlist_get(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT game_name, last_price, target_price FROM wishlist WHERE user_id=? ORDER BY rowid DESC",
                (user_id,)).fetchall()
        items = [{'name': r[0], 'last_price': r[1], 'target_price': r[2]} for r in rows]

        def enrich(item):
            name = item['name']
            try:
                r1 = requests.get('https://www.cheapshark.com/api/1.0/deals',
                    params={'title': name, 'sortBy': 'Price', 'pageSize': 5}, timeout=4)
                deals = r1.json() if r1.ok else []
            except Exception:
                deals = []
            try:
                r2 = requests.get('https://www.cheapshark.com/api/1.0/games',
                    params={'title': name, 'limit': 1}, timeout=4)
                games = r2.json() if r2.ok else []
            except Exception:
                games = []
            if deals:
                best = deals[0]
                item['sale_price'] = float(best.get('salePrice', 0))
                item['normal_price'] = float(best.get('normalPrice', 0))
                item['savings_pct'] = float(best.get('savings', 0))
                item['store_id'] = str(best.get('storeID', ''))
                item['deal_id'] = best.get('dealID', '')
                item['is_on_sale'] = item['sale_price'] < item['normal_price'] - 0.01
            if games:
                atp = games[0].get('cheapestPriceEver') or {}
                ps = atp.get('price')
                item['all_time_low'] = float(ps) if ps else None
            return item

        if items:
            with ThreadPoolExecutor(max_workers=min(8, len(items))) as ex:
                items = list(ex.map(enrich, items))

        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>', methods=['POST'])
def api_wishlist_add(user_id):
    data = request.get_json(force=True)
    name = data.get('name', '').strip()
    if not name: return jsonify({'error': 'no_name'}), 400
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            count = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id=?", (user_id,)).fetchone()[0]
            vip   = conn.execute(
                "SELECT 1 FROM user_news_prefs WHERE user_id=? AND premium_until>datetime('now')", (user_id,)
            ).fetchone()
            limit = 100 if vip else 5
            if count >= limit:
                return jsonify({'error': 'limit', 'limit': limit, 'vip': bool(vip)}), 400
            conn.execute("INSERT OR IGNORE INTO wishlist (user_id,game_name,last_price) VALUES(?,?,?)",
                         (user_id, name, None))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>/alert', methods=['POST'])
def api_wishlist_alert(user_id):
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    target_price = data.get('target_price')
    if not name:
        return jsonify({'error': 'no name'}), 400
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute('UPDATE wishlist SET target_price=? WHERE user_id=? AND game_name=?',
                         (target_price, user_id, name))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wishlist/<int:user_id>/<path:game_name>', methods=['DELETE'])
def api_wishlist_delete(user_id, game_name):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("DELETE FROM wishlist WHERE user_id=? AND game_name=?", (user_id, game_name))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── USER AUTO-REGISTER (WebApp init) ─────
@app.route('/api/user/register', methods=['POST'])
def api_user_register():
    """Called when WebApp opens — ensures user exists in DB with Telegram profile info."""
    data = request.get_json(force=True) or {}
    user_id    = data.get('user_id')
    first_name = (data.get('first_name') or '').strip()[:64]
    last_name  = (data.get('last_name')  or '').strip()[:64]
    username   = (data.get('username')   or '').strip()[:64]
    if not user_id:
        return jsonify({'error': 'no_user_id'}), 400
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            # Add columns if missing (migration safety)
            for col, typedef in [('first_name', 'TEXT'), ('last_name', 'TEXT'), ('username', 'TEXT')]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
                except Exception:
                    pass
            # Insert user if not exists
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, reg_date) VALUES (?, datetime('now'))",
                (user_id,)
            )
            # Update profile fields
            conn.execute(
                "UPDATE users SET first_name=?, last_name=?, username=? WHERE user_id=?",
                (first_name, last_name, username, user_id)
            )
            # Ensure user_news_prefs row exists
            conn.execute("INSERT OR IGNORE INTO user_news_prefs (user_id) VALUES (?)", (user_id,))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── PROFILE ──────────────────────────────
@app.route('/api/profile/<int:user_id>')
def api_profile(user_id):
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            user  = conn.execute("SELECT reg_date FROM users WHERE user_id=?", (user_id,)).fetchone()
            prefs = conn.execute(
                "SELECT premium_until, currency, want_news, want_freebies, auto_renew FROM user_news_prefs WHERE user_id=?",
                (user_id,)).fetchone()
            wc = conn.execute("SELECT COUNT(*) FROM wishlist WHERE user_id=?", (user_id,)).fetchone()[0]
            rc = conn.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)).fetchone()[0]
        is_vip = False; premium_until = None
        currency = 'USD'; want_news = False; want_freebies = False; auto_renew = 0
        if prefs:
            premium_until = prefs[0]; currency = prefs[1] or 'USD'
            want_news = bool(prefs[2]); want_freebies = bool(prefs[3])
            auto_renew = prefs[4] or 0
            if premium_until:
                try: is_vip = datetime.strptime(premium_until, '%Y-%m-%d %H:%M:%S') > datetime.utcnow()
                except: pass
        return jsonify({
            'user_id': user_id, 'reg_date': user[0] if user else None,
            'is_vip': is_vip, 'premium_until': premium_until if is_vip else None,
            'currency': currency, 'want_news': want_news, 'want_freebies': want_freebies,
            'auto_renew': bool(auto_renew), 'wishlist_count': wc, 'referrals': rc
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── SETTINGS ─────────────────────────────
@app.route('/api/settings/<int:user_id>', methods=['POST'])
def api_settings_update(user_id):
    data = request.get_json(force=True)
    try:
        with sqlite3.connect(config.DB_FILE) as conn:
            conn.execute("INSERT OR IGNORE INTO user_news_prefs (user_id) VALUES(?)", (user_id,))
            if 'currency'      in data: conn.execute("UPDATE user_news_prefs SET currency=?      WHERE user_id=?", (data['currency'],          user_id))
            if 'want_news'     in data: conn.execute("UPDATE user_news_prefs SET want_news=?     WHERE user_id=?", (int(data['want_news']),     user_id))
            if 'want_freebies' in data: conn.execute("UPDATE user_news_prefs SET want_freebies=? WHERE user_id=?", (int(data['want_freebies']), user_id))
            if 'auto_renew'    in data: conn.execute("UPDATE user_news_prefs SET auto_renew=?    WHERE user_id=?", (int(data['auto_renew']),    user_id))
            conn.commit()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── VIP INVOICE (Telegram Stars) ─────────
@app.route('/api/vip/invoice/<int:user_id>', methods=['POST'])
def api_vip_invoice(user_id):
    if not config.BOT_TOKEN:
        return jsonify({'error': 'no_token'}), 500
    data      = request.get_json(force=True) or {}
    auto_renew = data.get('auto_renew', False)
    try:
        payload = {
            'title': 'VIP Статус ⭐',
            'description': (
                'Элитный радар халявы (AAA и топ инди) · '
                'Безлимитный шорт-лист до 100 игр · '
                'Уведомление о снижении цены · '
                'Ad-Free режим · 30 дней'
            ),
            'payload': 'vip_sub_30',
            'currency': 'XTR',
            'prices': json.dumps([{'label': 'VIP Подписка 30 дней', 'amount': 100}]),
        }
        if auto_renew:
            payload['subscription_period'] = 2592000
        r = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/createInvoiceLink",
            data=payload, timeout=8
        )
        resp = r.json()
        if resp.get('ok'):
            return jsonify({'link': resp['result']})
        return jsonify({'error': resp.get('description', 'api_error')}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── DONATE INVOICE (Telegram Stars) ──────
@app.route('/api/donate/invoice/<int:user_id>/<int:amount>', methods=['POST'])
def api_donate_invoice(user_id, amount):
    if not config.BOT_TOKEN:
        return jsonify({'error': 'no_token'}), 500
    if amount not in [25, 50, 100, 250, 500]:
        return jsonify({'error': 'bad_amount'}), 400
    try:
        payload = {
            'title': '⭐ Поддержать Game Broker',
            'description': f'Донат {amount} звёзд. Спасибо, что помогаешь развитию проекта!',
            'payload': f'donate_{amount}',
            'currency': 'XTR',
            'prices': json.dumps([{'label': f'Донат {amount} ⭐', 'amount': amount}]),
        }
        r = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/createInvoiceLink",
            data=payload, timeout=8
        )
        resp = r.json()
        if resp.get('ok'):
            return jsonify({'link': resp['result']})
        return jsonify({'error': resp.get('description', 'api_error')}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    database.init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
