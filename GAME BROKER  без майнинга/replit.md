# 🎮 Game Broker Bot - Complete Documentation

**Last Updated**: Jan 12, 2026

## 📱 Project Overview

A comprehensive Telegram gaming bot with price tracking and a Mining Farm economy system (USDT).

**Two Main Components:**
- **Telegram Bot** (main.py) - Game Broker with mining & gaming deals
- **Web App** (app.py) - Flask UI for PC levels

---

## 🛠 Tech Stack
- Python 3.11 + Flask
- SQLite3 database
- pytelegrambotapi + requests
- CryptoPay API for USDT payments

---

## 🔑 Required Secrets (Add in 🔑 Secrets tab)

| Key | Value | Where to Get |
|-----|-------|--------------|
| `BOT_TOKEN` | Telegram bot token | https://t.me/BotFather |
| `CRYPTO_PAY_API_KEY` | CryptoPay API token | https://cryptobot.dev |

---

## ✅ Payment System Status

### USDT Economy (CryptoBot API)
- **Primary Currency**: USDT
- **Usage**: Mining Farm components, boxes, packs, and withdrawals.
- **Invoice Creation**: ✅ Implemented via CryptoBot
- **Status**: Requires `CRYPTO_PAY_API_KEY` in Secrets

---

## ⛏️ Mining Farm System (USDT)

**Core Economy:**
- Users buy components and boxes for USDT.
- Build PC farms to mine USDT income.
- Withdraw real money via CryptoBot.

---

## 🚀 Features

✅ Game price tracking (17+ stores)
✅ Mining Farm system (USDT)
✅ CryptoPay integration (USDT payments/withdrawals)
✅ Referral program
✅ Admin statistics
✅ Auto news feeds (RSS)
✅ Anti-flood protection (debounce)
✅ Project Donations (Telegram Stars)

---

## 🐛 Recent Fixes

**Jan 12, 2026 - System Stabilization:**
- ✅ **Fixed**: Missing `pyTelegramBotAPI` package installed.
- ✅ **Fixed**: `ValueError: Token must not contain spaces` by adding `.strip()` to BOT_TOKEN.
- ✅ **Fixed**: Potential `UnboundLocalError` in RSS news feed system.
- ✅ **Improved**: Added safety checks for BeautifulSoup attribute parsing.
- ✅ **Fixed**: Indentation and logic errors in withdrawal processing.
- ✅ **Improved**: Database migration safety with specific error handling.

**Dec 30 - System Stability:**
- ✅ **Fixed**: Import error `NameError: name 'Thread' is not defined` in `main.py`.
- ✅ **Improved**: Import organization and threading stability.

---

## 📁 Project Structure

```
main.py              - Telegram bot
app.py               - Flask web app
templates/index.html - Web UI
wishlist.db          - SQLite database
replit.md            - This file
```

---

## 🚨 Troubleshooting

**Bot not responding?**
- Check: Is BOT_TOKEN in Secrets?
- Check: Is the workflow running?

**USDT Payments not working?**
- Check: CRYPTO_PAY_API_KEY in Secrets.
- Check: Console logs for API errors.
