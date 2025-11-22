"""Main application entrypoint for CoinTrackerBot.

This module wires together the Telegram Bot (aiogram), periodic jobs (APScheduler),
and application-level utilities (caching, indicators, portfolio management).

Key responsibilities:
- Configure and start the bot, dispatcher and scheduler.
- Register handlers and middlewares.
- Provide scheduled background tasks (price checks, cache refresh, user reports).
- Build a lightweight in-process cache for dashboard data and persist it to data/cache.json.

Concurrency and design notes:
- Network I/O and long-running tasks use async/await to avoid blocking the event loop.
- The APScheduler runs coroutine jobs where appropriate; periodic tasks are non-blocking.
- Persistent state is stored as JSON files under data/ and accessed via helper functions.
- Logging is configured at module startup; sensitive data (tokens) should not be logged.
"""

import asyncio
import logging
import sys
import threading
from aiogram import Bot, Dispatcher, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config.config import BOT_TOKEN, ALARM_FILE, PORTFOLIO_FILE, WATCHLIST_FILE, SAVINGS_FILE, BUDGET_FILE, TRANSACTIONS_FILE, USER_SETTINGS_FILE, ACHIEVEMENTS_FILE, FIAT_TRANSACTIONS_FILE
from utils import get_price, get_volatility, calculate_rsi, load_file, save_file_async, get_historical_prices
# Add missing imports for cached functions
from utils import get_price_cached, get_24h_change_cached, calculate_rsi_cached
from utils import get_24h_change  # Fix missing import
from states import BotStates
from handlers import commands, callbacks
from datetime import datetime, timedelta
import random
from keyboards import slider_keyboard, dashboard_keyboard, indicators_keyboard, review_settings_keyboard, percent_period_keyboard, indicator_type_keyboard, repeat_keyboard
from collections import defaultdict, deque
import time
import json
from utils_cache import (
    get_price_cached_from_file, get_24h_change_cached_from_file, calculate_rsi_cached_from_file, get_macd_cached_from_file,
    get_price_cached_from_file_async, get_24h_change_cached_from_file_async, calculate_rsi_cached_from_file_async, get_macd_cached_from_file_async
)

# Ensure CACHE_FILE is defined early for cache writer/reader usage
CACHE_FILE = "data/cache.json"

# Professional logging setup
logger = logging.getLogger("CoinTrackerBot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler("CoinTrackerBot.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Spam-Schutz Middleware ---
class SpamProtectionMiddleware:
    """Middleware to protect against abusive/flooding user behavior.

    Rate tracking:
    - Keeps a short deque of recent timestamps per user (maxlen=30).
    - Warns users that exceed short-term thresholds and escalates to temporary blocks.
    - Blocks escalate across repeated offenses with increasing durations.

    Integration:
    - Middleware inspects incoming events to identify the originating user.
    - If a user is currently blocked, their events are silently dropped.
    - Non-blocking: middleware awaits handlers as usual.
    """
    def __init__(self):
        self.user_timestamps = defaultdict(lambda: deque(maxlen=30))  # max 30 timestamps
        self.user_warned = defaultdict(bool)
        self.user_block_until = defaultdict(float)
        self.user_block_level = defaultdict(int)
        logger.debug("[Middleware] SpamProtectionMiddleware initialized.")

    async def __call__(self, handler, event, data):
        logger.debug(f"[Middleware] Event received: {event}")
        user_id = None
        if hasattr(event, 'from_user') and event.from_user:
            user_id = str(event.from_user.id)
        elif hasattr(event, 'message') and hasattr(event.message, 'from_user') and event.message.from_user:
            user_id = str(event.message.from_user.id)
        if not user_id:
            logger.debug("[Middleware] No user_id found; continuing normal processing.")
            return await handler(event, data)
        now = time.time()
        # Check block state
        if now < self.user_block_until[user_id]:
            logger.info(f"[Middleware] User {user_id} is blocked until {self.user_block_until[user_id]}")
            return  # Ignore events while blocked
        # Rate tracking
        self.user_timestamps[user_id].append(now)
        recent = [t for t in self.user_timestamps[user_id] if now - t <= 1]
        logger.debug(f"[Middleware] User {user_id} recent events in 1s: {len(recent)}")
        if len(recent) >= 3:
            last_2s = [t for t in self.user_timestamps[user_id] if now - t <= 2]
            if len(last_2s) >= 6 and not self.user_warned[user_id]:
                logger.info(f"[Middleware] Warning user {user_id} for spamming.")
                # Send a warning message if possible
                if hasattr(event, 'answer'):
                    await event.answer("⚠️ Bitte nicht spammen! Sonst wirst du vorübergehend gesperrt.")
                elif hasattr(event, 'reply'):
                    await event.reply("⚠️ Bitte nicht spammen! Sonst wirst du vorübergehend gesperrt.")
                self.user_warned[user_id] = True
            last_10s = [t for t in self.user_timestamps[user_id] if now - t <= 10]
            if len(last_10s) >= 30:
                level = self.user_block_level[user_id]
                block_times = [60, 300, 1200, 3600]  # 1min, 5min, 20min, 1h
                block_time = block_times[min(level, len(block_times)-1)]
                self.user_block_until[user_id] = now + block_time
                self.user_block_level[user_id] += 1
                self.user_warned[user_id] = False
                logger.warning(f"[Middleware] User {user_id} blocked for {block_time} seconds (Level {level})")
                if hasattr(event, 'answer'):
                    await event.answer(f"🚫 Du wurdest wegen Spam für {block_time//60} Minuten gesperrt.")
                elif hasattr(event, 'reply'):
                    await event.reply(f"🚫 Du wurdest wegen Spam für {block_time//60} Minuten gesperrt.")
                return
        else:
            self.user_warned[user_id] = False
        logger.debug(f"[Middleware] Passing event for user {user_id} to handler.")
        return await handler(event, data)

# --- Middleware registrieren ---
dp.message.middleware(SpamProtectionMiddleware())
dp.callback_query.middleware(SpamProtectionMiddleware())

async def check_achievements(user_id: str, portfolio: dict, transactions: list, alarms: list):
    logger.debug(f"[Achievements] check_achievements für user_id={user_id}")
    achievements = load_file(ACHIEVEMENTS_FILE).get(user_id, {})
    total_value = 0
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    for coin, data in portfolio.items():
        if coin == "fiat":
            for curr, amount in data.items():
                if curr != currency:
                    total_value += amount * 0.9 if curr == "USD" and currency == "EUR" else amount / 0.9
                else:
                    total_value += amount
        else:
            price = await get_price(coin, currency)
            if price:
                total_value += price * data["amount"]
    logger.debug(f"[Achievements] total_value={total_value}")
    now = datetime.now().isoformat()
    if not achievements.get("first_buy") and any(t["type"] == "buy" for t in transactions):
        logger.info(f"[Achievements] first_buy für user_id={user_id} erreicht")
        achievements["first_buy"] = {"name": "Erster Kauf", "description": "Du hast deinen ersten Coin gekauft!", "date": now}
    if not achievements.get("portfolio_10000") and total_value >= 10000:
        logger.info(f"[Achievements] portfolio_10000 für user_id={user_id} erreicht")
        achievements["portfolio_10000"] = {"name": "High Roller", "description": "Portfolio-Wert über 10.000!", "date": now}
    if not achievements.get("ten_alarms") and len(alarms) >= 10:
        logger.info(f"[Achievements] ten_alarms für user_id={user_id} erreicht")
        achievements["ten_alarms"] = {"name": "Alarm-Meister", "description": "10 Alarme gesetzt!", "date": now}
    if not achievements.get("ten_trades") and len(transactions) >= 10:
        logger.info(f"[Achievements] ten_trades für user_id={user_id} erreicht")
        achievements["ten_trades"] = {"name": "Trader", "description": "10 Transaktionen durchgeführt!", "date": now}
    savings = load_file(SAVINGS_FILE).get(user_id, {})
    budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
    if not achievements.get("goal_reached") and any((portfolio.get(c, {"amount": 0})["amount"] >= d["target"]) for c, d in savings.items()):
        logger.info(f"[Achievements] goal_reached für user_id={user_id} erreicht")
        achievements["goal_reached"] = {"name": "Sparziel erreicht", "description": "Du hast ein Sparziel erreicht!", "date": now}
    if not achievements.get("budget_set") and budget.get("amount", 0) > 0:
        logger.info(f"[Achievements] budget_set für user_id={user_id} erreicht")
        achievements["budget_set"] = {"name": "Budget gesetzt", "description": "Du hast ein Budget festgelegt!", "date": now}
    if not achievements.get("watchlist_add") and len(load_file(WATCHLIST_FILE).get(user_id, [])) > 0:
        logger.info(f"[Achievements] watchlist_add für user_id={user_id} erreicht")
        achievements["watchlist_add"] = {"name": "Watchlist erweitert", "description": "Du hast Coins zur Watchlist hinzugefügt!", "date": now}
    await save_file_async(ACHIEVEMENTS_FILE, {user_id: achievements})
    logger.debug(f"[Achievements] Achievements gespeichert für user_id={user_id}")

async def send_monthly_report(user_id: str):
    logger.debug(f"[Report] send_monthly_report für user_id={user_id}")
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    total_value = 0
    for coin, data in portfolio.items():
        if coin == "fiat":
            for curr, amount in data.items():
                if curr != currency:
                    total_value += amount * 0.9 if curr == "USD" and currency == "EUR" else amount / 0.9
                else:
                    total_value += amount
        else:
            price = await get_price(coin, currency)
            if price:
                total_value += price * data["amount"]
    logger.debug(f"[Report] total_value={total_value}")
    buys = len([t for t in transactions if t["type"] == "buy" and t["date"][:7] == datetime.now().strftime("%Y-%m")])
    sells = len([t for t in transactions if t["type"] == "sell" and t["date"][:7] == datetime.now().strftime("%Y-%m")])
    logger.debug(f"[Report] buys={buys}, sells={sells}")
    response = (
        f"📅 *Monatlicher Bericht ({datetime.now().strftime('%Y-%m')})*\n\n"
        f"- Portfolio-Wert: **{total_value:.2f} {currency}**\n"
        f"- Käufe: {buys}\n"
        f"- Verkäufe: {sells}\n"
        f"- Erfolge: {len(load_file(ACHIEVEMENTS_FILE).get(user_id, {}))}"
    )
    try:
        await bot.send_message(
            int(user_id),
            response,
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        logger.info(f"[Report] Monatsbericht an user_id={user_id} gesendet.")
    except Exception as e:
        logger.error(f"[Report] Fehler beim Senden des Berichts an user_id={user_id}: {e}")

async def check_prices():
    logger.debug("[Alarm] check_prices gestartet")
    alarms = load_file(ALARM_FILE)
    for user_id, user_alarms in alarms.items():
        logger.debug(f"[Alarm] Prüfe Alarme für user_id={user_id}")
        settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
        currency = settings.get("currency", "USD")
        updated_alarms = []
        for alarm in user_alarms:
            logger.debug(f"[Alarm] Alarm: {alarm}")
            if alarm["type"] == "price":
                current_price = await get_price(alarm["coin"], currency) or 0
                logger.debug(f"[Alarm] Preis für {alarm['coin']} in {currency}: {current_price}")
                if alarm["direction"] == "below" and current_price < alarm["target"]:
                    await bot.send_message(
                        int(user_id),
                        f"🔔 *Alarm*: {alarm['coin']} ist unter {alarm['target']:.0f} {currency} gefallen! Aktueller Preis: {current_price:.2f} {currency}",
                        parse_mode="Markdown"
                    )
                    logger.info(f"[Alarm] Preis-Alarm (below) ausgelöst für {alarm['coin']} user_id={user_id}")
                    alarm["trigger_count"] += 1
                elif alarm["direction"] == "above" and current_price > alarm["target"]:
                    await bot.send_message(
                        int(user_id),
                        f"🔔 *Alarm*: {alarm['coin']} ist über {alarm['target']:.0f} {currency} gestiegen! Aktueller Preis: {current_price:.2f} {currency}",
                        parse_mode="Markdown"
                    )
                    logger.info(f"[Alarm] Preis-Alarm (above) ausgelöst für {alarm['coin']} user_id={user_id}")
                    alarm["trigger_count"] += 1
                updated_alarms.append(alarm)
            elif alarm["type"] == "percent":
                coin = alarm["coin"]
                percent = alarm["percent"]
                period = alarm["period"]
                repeat = alarm.get("repeat", False)
                try:
                    interval = "1m" if period <= 60 else "5m" if period <= 240 else "15m"
                    limit = max(2, int(period / (1 if interval == "1m" else 5 if interval == "5m" else 15)) + 1)
                    prices = await get_historical_prices(coin, interval=interval, limit=limit)
                    if prices and len(prices) >= 2:
                        old_price = prices[0]["price"]
                        current_price = prices[-1]["price"]
                        change = (current_price - old_price) / old_price * 100 if old_price else 0
                        logger.debug(f"[Alarm] Prozent-Alarm {coin}: old={old_price}, current={current_price}, change={change}")
                        if abs(change) >= percent and not alarm.get("triggered", False):
                            direction = "gestiegen" if change > 0 else "gefallen"
                            try:
                                await bot.send_message(
                                    int(user_id),
                                    f"🔔 *Prozent-Alarm*: {coin} ist in {period}min um {change:.2f}% {direction}!",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"[Alarm] Fehler beim Senden Prozent-Alarm: {e}")
                            logger.info(f"[Alarm] Prozent-Alarm ausgelöst für {coin} user_id={user_id}")
                            if repeat:
                                alarm["triggered"] = True
                            else:
                                alarm["triggered"] = True
                        elif repeat and abs(change) < percent:
                            alarm["triggered"] = False  # Reset, wenn Schwelle wieder unterschritten
                    updated_alarms.append(alarm)
                except Exception as e:
                    logger.error(f"[Alarm] Fehler bei Prozent-Alarm für {coin}: {e}")
                    updated_alarms.append(alarm)
            elif alarm["type"] == "indicator":
                coin = alarm["coin"]
                indicator = alarm["indicator"]
                value = alarm["value"]
                repeat = alarm.get("repeat", False)
                try:
                    if indicator == "rsi_overbought":
                        rsi = await calculate_rsi(coin)
                        if rsi and rsi > value and not alarm.get("triggered", False):
                            try:
                                await bot.send_message(
                                    int(user_id),
                                    f"🔔 *Indikator-Alert*: {coin} RSI ist über {value:.1f} (aktuell: {rsi:.1f})!",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"[Alarm] Fehler beim Senden Indikator-Alert: {e}")
                            logger.info(f"[Alarm] Indikator-Alert ausgelöst für {coin} user_id={user_id}")
                            if repeat:
                                alarm["triggered"] = True
                            else:
                                alarm["triggered"] = True
                    elif indicator == "rsi_oversold":
                        rsi = await calculate_rsi(coin)
                        if rsi and rsi < value and not alarm.get("triggered", False):
                            try:
                                await bot.send_message(
                                    int(user_id),
                                    f"🔔 *Indikator-Alert*: {coin} RSI ist unter {value:.1f} (aktuell: {rsi:.1f})!",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logger.error(f"[Alarm] Fehler beim Senden Indikator-Alert: {e}")
                            logger.info(f"[Alarm] Indikator-Alert ausgelöst für {coin} user_id={user_id}")
                            if repeat:
                                alarm["triggered"] = True
                            else:
                                alarm["triggered"] = True
                        elif repeat and rsi and rsi >= value:
                            alarm["triggered"] = False
                    updated_alarms.append(alarm)
                except Exception as e:
                    logger.error(f"[Alarm] Fehler bei Indikator-Alarm für {coin}: {e}")
                    updated_alarms.append(alarm)
            elif alarm["type"] == "watchlist":
                logger.debug(f"[Alarm] Watchlist-Alarm: {alarm}")
                if alarm["alarm_type"] == "volatility":
                    volatility_data = await get_volatility(alarm["coin"])
                    logger.debug(f"[Alarm] Volatility für {alarm['coin']}: {volatility_data}")
                    if volatility_data and volatility_data["volatility"] > alarm["target"]:
                        await bot.send_message(
                            int(user_id),
                            f"⚡ *Watchlist-Alarm*: {alarm['coin']} hat eine Volatilität von {volatility_data['volatility']:.2f}% (>{alarm['target']:.1f}%)!",
                            parse_mode="Markdown"
                        )
                        logger.info(f"[Alarm] Volatility-Alarm ausgelöst für {alarm['coin']} user_id={user_id}")
                        alarm["trigger_count"] += 1
                elif alarm["alarm_type"] == "rsi_overbought":
                    rsi = await calculate_rsi(alarm["coin"])
                    logger.debug(f"[Alarm] RSI für {alarm['coin']}: {rsi}")
                    if rsi and rsi > alarm["target"]:
                        await bot.send_message(
                            int(user_id),
                            f"📈 *Watchlist-Alarm*: {alarm['coin']} ist überkauft! RSI: {rsi:.1f} (>{alarm['target']:.0f})",
                            parse_mode="Markdown"
                        )
                        logger.info(f"[Alarm] RSI-Overbought-Alarm ausgelöst für {alarm['coin']} user_id={user_id}")
                        alarm["trigger_count"] += 1
                elif alarm["alarm_type"] == "rsi_oversold":
                    rsi = await calculate_rsi(alarm["coin"])
                    logger.debug(f"[Alarm] RSI für {alarm['coin']}: {rsi}")
                    if rsi and rsi < alarm["target"]:
                        await bot.send_message(
                            int(user_id),
                            f"📉 *Watchlist-Alarm*: {alarm['coin']} ist überverkauft! RSI: {rsi:.1f} (<{alarm['target']:.0f})",
                            parse_mode="Markdown"
                        )
                        logger.info(f"[Alarm] RSI-Oversold-Alarm ausgelöst für {alarm['coin']} user_id={user_id}")
                        alarm["trigger_count"] += 1
                updated_alarms.append(alarm)
        alarms[user_id] = updated_alarms
        await save_file_async(ALARM_FILE, alarms)
        logger.debug(f"[Alarm] Alarme für user_id={user_id} gespeichert.")

async def manual_coin_input(message: types.Message, state: FSMContext):
    logger.debug(f"[Input] manual_coin_input von user_id={message.from_user.id}, text={message.text}")
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    symbol = message.text.strip().upper()
    price = await get_price(symbol, currency)
    logger.debug(f"[Input] Preis für {symbol} in {currency}: {price}")
    if price is None:
        logger.info(f"[Input] Ungültiger Coin oder API-Probleme für {symbol}")
        await message.reply(
            "❌ *Fehler*: Ungültiger Coin oder API-Probleme.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
    else:
        await message.reply(
            f"💰 *{symbol}*: **{price:.2f} {currency}**",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔔 Alarm setzen", callback_data=f"vol_alarm:{symbol}"),
                 types.InlineKeyboardButton(text="➕ Zu Portfolio", callback_data="portfolio_buy")],
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        logger.info(f"[Input] Preis für {symbol} an user_id={user_id} gesendet.")
    await state.clear()
    logger.debug(f"[Input] State für user_id={user_id} gecleared.")
dp.message.register(manual_coin_input, StateFilter(BotStates.manual_coin_input))

async def manual_target_input(message: types.Message, state: FSMContext):
    logger.debug(f"[Input] manual_target_input von user_id={message.from_user.id}, text={message.text}")
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    try:
        target = float(message.text)
        logger.debug(f"[Input] Zielwert: {target}")
        if target <= 0:
            raise ValueError
        data = await state.get_data()
        logger.debug(f"[Input] State-Daten: {data}")
        if data.get("direction") == "percent":
            user_id = str(message.from_user.id)
            alarms = load_file(ALARM_FILE)
            if user_id not in alarms:
                alarms[user_id] = []
            alarms[user_id].append({
                "coin": data["coin"],
                "target": target,
                "direction": "percent",
                "trigger_count": 0,
                "currency": currency,
                "type": "price",
                "base_price": await get_price(data["coin"], currency) or 0
            })
            await save_file_async(ALARM_FILE, alarms)
            logger.info(f"[Input] Prozent-Alarm für {data['coin']} user_id={user_id} gesetzt: {target}")
            await message.reply(
                f"🔔 *Alarm gesetzt*: {data['coin']} ändert sich um ±**{target:.1f}%**",
                parse_mode="Markdown",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="📋 Meine Alarme", callback_data="dash_alarms"),
                     types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
            await state.clear()
            logger.debug(f"[Input] State für user_id={user_id} gecleared.")
        else:
            await state.update_data(target=target)
            logger.debug(f"[Input] State für user_id={user_id} updated mit target={target}")
            await message.reply(
                f"Zielpreis auf **{target:.0f} {currency}** gesetzt. Bestätige oder passe an:",
                parse_mode="Markdown",
                reply_markup=slider_keyboard(target)
            )
            await state.set_state(BotStates.adjusting_target)
            logger.debug(f"[Input] State für user_id={user_id} auf adjusting_target gesetzt.")
    except ValueError:
        logger.info(f"[Input] Ungültige Eingabe für Zielwert von user_id={user_id}: {message.text}")
        await message.reply(
            "❌ *Fehler*: Bitte gib eine positive Zahl ein.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(manual_target_input, StateFilter(BotStates.manual_target))

async def portfolio_add_amount(message: types.Message, state: FSMContext):
    logger.debug(f"[Portfolio] portfolio_add_amount von user_id={message.from_user.id}, text={message.text}")
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    try:
        amount = float(message.text)
        logger.debug(f"[Portfolio] amount={amount}")
        if amount <= 0:
            raise ValueError
        data = await state.get_data()
        logger.debug(f"[Portfolio] State-Daten: {data}")
        coin = data["coin"]
        action = data.get("action", "buy")
        portfolio = load_file(PORTFOLIO_FILE)
        transactions = load_file(TRANSACTIONS_FILE)
        budget = load_file(BUDGET_FILE)
        if user_id not in portfolio:
            portfolio[user_id] = {}
        if user_id not in transactions:
            transactions[user_id] = []
        if user_id not in budget:
            budget[user_id] = {"amount": 0, "spent": 0}
        price = await get_price(coin, currency) or 0
        logger.debug(f"[Portfolio] Preis für {coin} in {currency}: {price}")
        if action == "buy":
            portfolio[user_id]["fiat"] = portfolio[user_id].get("fiat", {})
            if currency not in portfolio[user_id]["fiat"] or portfolio[user_id]["fiat"][currency] < price * amount:
                logger.info(f"[Portfolio] Nicht genügend {currency} für Kauf von {amount} {coin} user_id={user_id}")
                await message.reply(
                    f"❌ *Fehler*: Nicht genügend {currency} im Portfolio.",
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="💵 Einzahlen", callback_data="fiat_deposit"),
                         types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                    ])
                )
                await state.clear()
                logger.debug(f"[Portfolio] State für user_id={user_id} gecleared.")
                return
            portfolio[user_id]["fiat"][currency] -= price * amount
            if portfolio[user_id]["fiat"][currency] == 0:
                del portfolio[user_id]["fiat"][currency]
            if not portfolio[user_id]["fiat"]:
                del portfolio[user_id]["fiat"]
            portfolio[user_id][coin] = portfolio[user_id].get(coin, {"amount": 0, "buy_price": 0})
            old_amount = portfolio[user_id][coin]["amount"]
            old_price = portfolio[user_id][coin]["buy_price"]
            new_amount = old_amount + amount
            new_buy_price = ((old_price * old_amount) + (price * amount)) / new_amount if new_amount else 0
            portfolio[user_id][coin] = {"amount": new_amount, "buy_price": new_buy_price}
            transactions[user_id].append({
                "type": "buy",
                "coin": coin,
                "amount": amount,
                "price": price,
                "date": datetime.now().isoformat(),
                "currency": currency
            })
            budget[user_id]["spent"] += price * amount
            logger.info(f"[Portfolio] Kauf: {amount} {coin} für {price*amount} {currency} user_id={user_id}")
            await message.reply(
                f"✅ *{amount:.4f} {coin}* gekauft für {price * amount:.2f} {currency}.",
                parse_mode="Markdown",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
                     types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
            await check_achievements(user_id, portfolio[user_id], transactions[user_id], load_file(ALARM_FILE).get(user_id, []))
        else:  # sell
            if coin not in portfolio[user_id] or portfolio[user_id][coin]["amount"] < amount:
                logger.info(f"[Portfolio] Nicht genügend {coin} für Verkauf user_id={user_id}")
                await message.reply(
                    f"❌ *Fehler*: Nicht genügend {coin} im Portfolio.",
                    parse_mode="Markdown",
                    reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                        [types.InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
                         types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                    ])
                )
                await state.clear()
                logger.debug(f"[Portfolio] State für user_id={user_id} gecleared.")
                return
            portfolio[user_id][coin]["amount"] -= amount
            portfolio[user_id]["fiat"] = portfolio[user_id].get("fiat", {})
            portfolio[user_id]["fiat"][currency] = portfolio[user_id]["fiat"].get(currency, 0) + price * amount
            if portfolio[user_id][coin]["amount"] == 0:
                del portfolio[user_id][coin]
            transactions[user_id].append({
                "type": "sell",
                "coin": coin,
                "amount": amount,
                "price": price,
                "date": datetime.now().isoformat(),
                "currency": currency
            })
            logger.info(f"[Portfolio] Verkauf: {amount} {coin} für {price*amount} {currency} user_id={user_id}")
            await message.reply(
                f"✅ *{amount:.4f} {coin}* verkauft für {price * amount:.2f} {currency}.",
                parse_mode="Markdown",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
                     types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
            await check_achievements(user_id, portfolio[user_id], transactions[user_id], load_file(ALARM_FILE).get(user_id, []))
        await save_file_async(PORTFOLIO_FILE, portfolio)
        await save_file_async(TRANSACTIONS_FILE, transactions)
        await save_file_async(BUDGET_FILE, budget)
        logger.debug(f"[Portfolio] Portfolio, Transactions und Budget gespeichert für user_id={user_id}")
        await state.clear()
        logger.debug(f"[Portfolio] State für user_id={user_id} gecleared.")
    except ValueError:
        logger.info(f"[Portfolio] Ungültige Eingabe für amount von user_id={user_id}: {message.text}")
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl ein (z.B. 0.5).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(portfolio_add_amount, StateFilter(BotStates.portfolio_add_amount))

async def fiat_deposit_amount(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        portfolio = load_file(PORTFOLIO_FILE)
        fiat_transactions = load_file(FIAT_TRANSACTIONS_FILE)
        if user_id not in portfolio:
            portfolio[user_id] = {}
        if user_id not in fiat_transactions:
            fiat_transactions[user_id] = []
        portfolio[user_id]["fiat"] = portfolio[user_id].get("fiat", {})
        portfolio[user_id]["fiat"][currency] = portfolio[user_id]["fiat"].get(currency, 0) + amount
        fiat_transactions[user_id].append({
            "type": "deposit",
            "amount": amount,
            "currency": currency,
            "date": datetime.now().isoformat()
        })
        await save_file_async(PORTFOLIO_FILE, portfolio)
        await save_file_async(FIAT_TRANSACTIONS_FILE, fiat_transactions)
        await message.reply(
            f"✅ *{amount:.2f} {currency}* eingezahlt.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💵 Fiat", callback_data="dash_fiat"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await state.clear()
    except ValueError:
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl ein (z.B. 1000).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(fiat_deposit_amount, StateFilter(BotStates.fiat_deposit))

async def fiat_withdraw_amount(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    try:
        amount = float(message.text)
        if amount <= 0:
            raise ValueError
        portfolio = load_file(PORTFOLIO_FILE)
        fiat_transactions = load_file(FIAT_TRANSACTIONS_FILE)
        if user_id not in portfolio or "fiat" not in portfolio.get(user_id, {}) or currency not in portfolio[user_id].get("fiat", {}) or portfolio[user_id]["fiat"][currency] < amount:
            await message.reply(
                f"❌ *Fehler*: Nicht genügend {currency} im Portfolio.",
                parse_mode="Markdown",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="💵 Fiat", callback_data="dash_fiat"),
                     types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
            await state.clear()
            return
        portfolio[user_id]["fiat"][currency] -= amount
        if portfolio[user_id]["fiat"][currency] == 0:
            del portfolio[user_id]["fiat"][currency]
        if not portfolio[user_id]["fiat"]:
            del portfolio[user_id]["fiat"]
        fiat_transactions[user_id].append({
            "type": "withdraw",
            "amount": amount,
            "currency": currency,
            "date": datetime.now().isoformat()
        })
        await save_file_async(PORTFOLIO_FILE, portfolio)
        await save_file_async(FIAT_TRANSACTIONS_FILE, fiat_transactions)
        await message.reply(
            f"✅ *{amount:.2f} {currency}* ausgezahlt.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💵 Fiat", callback_data="dash_fiat"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await state.clear()
    except ValueError:
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl ein (z.B. 500).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(fiat_withdraw_amount, StateFilter(BotStates.fiat_withdraw))

async def watchlist_alarm_value(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    try:
        value = float(message.text)
        if value <= 0:
            raise ValueError
        data = await state.get_data()
        coin = data["coin"]
        alarm_type = data["alarm_type"]
        alarms = load_file(ALARM_FILE)
        if user_id not in alarms:
            alarms[user_id] = []
        alarms[user_id].append({
            "coin": coin,
            "target": value,
            "direction": "above" if alarm_type == "rsi_overbought" else "below" if alarm_type == "rsi_oversold" else "above",
            "trigger_count": 0,
            "currency": currency,
            "type": "watchlist",
            "alarm_type": alarm_type
        })
        await save_file_async(ALARM_FILE, alarms)
        alarm_desc = "RSI > 70" if alarm_type == "rsi_overbought" else "RSI < 30" if alarm_type == "rsi_oversold" else f"Volatilität > {value:.1f}%"
        await message.reply(
            f"🔔 *Watchlist-Alarm gesetzt*: {coin} {alarm_desc}.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="📋 Meine Alarme", callback_data="dash_alarms"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await state.clear()
    except ValueError:
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl ein (z.B. 5).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(watchlist_alarm_value, StateFilter(BotStates.watchlist_alarm_value))

async def savings_add_amount(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    try:
        target = float(message.text)
        if target <= 0:
            raise ValueError
        data = await state.get_data()
        coin = data["coin"]
        savings = load_file(SAVINGS_FILE)
        if user_id not in savings:
            savings[user_id] = {}
        savings[user_id][coin] = {"target": target}
        await save_file_async(SAVINGS_FILE, savings)
        await message.reply(
            f"✅ *Sparziel gesetzt*: {target:.4f} {coin}.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🎯 Sparziele", callback_data="dash_savings"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await state.clear()
    except ValueError:
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl ein (z.B. 1.5).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(savings_add_amount, StateFilter(BotStates.savings_add))

async def budget_set_amount(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    try:
        amount = float(message.text)
        if amount < 0:
            raise ValueError
        budget = load_file(BUDGET_FILE)
        budget[user_id] = {"amount": amount, "spent": budget.get(user_id, {"spent": 0})["spent"]}
        await save_file_async(BUDGET_FILE, budget)
        await message.reply(
            f"✅ *Budget gesetzt*: {amount:.2f} {currency}.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💸 Budget", callback_data="dash_budget"),
                 types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await state.clear()
    except ValueError:
        await message.reply(
            "❌ *Fehler*: Gib eine positive Zahl oder 0 ein (z.B. 1000).",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
dp.message.register(budget_set_amount, StateFilter(BotStates.budget_set))

async def confirm_reset_code(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    data = await state.get_data()
    if message.text == data.get("reset_code"):
        files = [ALARM_FILE, PORTFOLIO_FILE, WATCHLIST_FILE, SAVINGS_FILE, BUDGET_FILE, TRANSACTIONS_FILE, USER_SETTINGS_FILE, ACHIEVEMENTS_FILE, FIAT_TRANSACTIONS_FILE]
        for file in files:
            data = load_file(file)
            if user_id in data:
                del data[user_id]
                await save_file_async(file, data)
        await message.reply(
            "🗑️ *Daten gelöscht.*\nStarte neu mit */start*.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
    else:
        await message.reply(
            "❌ *Falscher Code.*\nVersuche es erneut oder gehe zurück.",
            parse_mode="Markdown",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
    await state.clear()
dp.message.register(confirm_reset_code, StateFilter(BotStates.confirm_reset_code))

# Add caching for dashboard data
_dashboard_cache = {}
_DASHBOARD_CACHE_TTL = 10  # seconds

async def update_global_price_cache():
    logger.info("[Cache] update_global_price_cache started")
    # Alle Coins aus allen User-Portfolios und Watchlists sammeln
    user_ids = set()
    try:
        user_ids = set(load_file(PORTFOLIO_FILE).keys()) | set(load_file(WATCHLIST_FILE).keys())
    except Exception as e:
        logger.error(f"[Cache] Error loading user ids: {e}")
    coins = set()
    currencies = set()
    for user_id in user_ids:
        try:
            portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
            watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
            settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
            currency = settings.get("currency", "USD").upper()
            currencies.add(currency)
            coins.update([c for c in portfolio if c != "fiat"])
            coins.update(watchlist)
        except Exception as e:
            logger.error(f"[Cache] Error collecting coins/currencies for user {user_id}: {e}")
    coins = list(coins)
    currencies = list(currencies)
    logger.info(f"[Cache] Coins to update: {coins} | Currencies: {currencies}")
    if not coins or not currencies:
        return
    # Preise für alle Coins und Currencies holen
    cache_data = {}
    for coin in coins:
        # Always fetch USD change/RSI for all coins
        try:
            change_usd = await get_24h_change(coin)
            rsi_usd = await calculate_rsi(coin, 14)
            cache_data[f"{coin.upper()}_USD"] = cache_data.get(f"{coin.upper()}_USD", {})
            cache_data[f"{coin.upper()}_USD"]["24h_change"] = change_usd
            cache_data[f"{coin.upper()}_USD"]["rsi_14"] = rsi_usd
        except Exception as e:
            logger.error(f"[Cache] Error fetching USD change/RSI for {coin}: {e}")
        for currency in currencies:
            try:
                price = await get_price(coin, currency)
                key = f"{coin.upper()}_{currency.upper()}"
                cache_data[key] = cache_data.get(key, {})
                cache_data[key]["price"] = price
            except Exception as e:
                logger.error(f"[Cache] Error fetching price for {coin} {currency}: {e}")
    cache_data["timestamp"] = time.time()
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        logger.info(f"[Cache] cache.json updated with {len(coins) * len(currencies)} coin-currency pairs (price), {len(coins)} USD change/RSI")
    except Exception as e:
        logger.error(f"[Cache] Error writing cache.json: {e}")

# Im Dashboard nur noch die neuen Cache-Funktionen verwenden
async def get_dashboard_data_cached(user_id):
    now = time.time()
    logger.info(f"[Dashboard] get_dashboard_data_cached called for user {user_id} at {now}")
    if user_id in _dashboard_cache and now - _dashboard_cache[user_id]["timestamp"] < _DASHBOARD_CACHE_TTL:
        logger.info(f"[Dashboard] Returning cached dashboard data for user {user_id}")
        return _dashboard_cache[user_id]["data"]

    logger.info(f"[Dashboard] Cache expired or not found for user {user_id}, fetching fresh data")
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings["currency"]
    user_indicators = set(settings.get("indicators", ["rsi"]))
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
    alarms = load_file(ALARM_FILE).get(user_id, [])
    budget = load_file(BUDGET_FILE).get(user_id, {"total": 0, "spent": 0})
    fiat_balances = portfolio.get("fiat", {})

    def get_coin_amount(coin_data):
        if isinstance(coin_data, dict):
            return coin_data.get("amount", 0)
        return coin_data

    def fast_price(coin):
        price = get_price_cached_from_file(coin, currency)
        logger.debug(f"[Dashboard] fast_price (file) for {coin} in {currency}: {price}")
        return price

    def fast_change(coin):
        return get_24h_change_cached_from_file(coin, currency="USD") if "rsi" in user_indicators or "macd" in user_indicators else None

    def fast_rsi(coin):
        return calculate_rsi_cached_from_file(coin, period=14, currency="USD") if "rsi" in user_indicators else None

    # Platzhalter für weitere Indikatoren (hier nur rsi und macd als Beispiel)
    def fast_macd(coin):
        return get_macd_cached_from_file(coin, currency="USD") if "macd" in user_indicators else None

    portfolio_value = 0
    for coin, data in portfolio.items():
        if coin == "fiat":
            continue
        amount = get_coin_amount(data)
        price = fast_price(coin)
        logger.debug(f"[Dashboard] {coin}: amount={amount}, price={price}")
        if price is not None and amount is not None:
            portfolio_value += price * amount

    watchlist_data = []
    for coin in watchlist:
        price = fast_price(coin)
        change = fast_change(coin)
        rsi = fast_rsi(coin)
        macd = fast_macd(coin) if "macd" in user_indicators else None
        logger.debug(f"[Dashboard] Watchlist {coin}: price={price}, change={change}, rsi={rsi}, macd={macd}")
        item = {
            "coin": coin,
            "price": price,
            "change": change,
            "rsi": rsi,
            "macd": macd
        }
        watchlist_data.append(item)

    dashboard_data = {
        "portfolio_value": portfolio_value,
        "watchlist": watchlist_data,
        "alarms": len(alarms),
        "budget": budget,
        "fiat_balances": fiat_balances,
        "currency": currency
    }

    logger.info(f"[Dashboard] Fresh dashboard data built for user {user_id}")
    _dashboard_cache[user_id] = {"data": dashboard_data, "timestamp": now}
    return dashboard_data

async def handle_dashboard(message: types.Message):
    user_id = str(message.from_user.id)
    dashboard_data = await get_dashboard_data_cached(user_id)

    # Format the dashboard message
    watchlist_text = "\n".join([
        f"- {item['coin']}: {item['price']:.2f} {dashboard_data['currency']}"
        + (f" ({item['change']:+.2f}%" if item.get('change') is not None else "")
        + (f", RSI: {item['rsi']:.1f}" if item.get('rsi') is not None else "")
        + (f", MACD: {item['macd']:.2f}" if item.get('macd') is not None else "")
        + (')' if (item.get('change') is not None or item.get('rsi') is not None or item.get('macd') is not None) else '')
        for item in dashboard_data["watchlist"]
    ])
    dashboard_message = (
        f"📊 Vermögens-Dashboard\n\n"
        f"💼 Portfolio-Wert: {dashboard_data['portfolio_value']:.2f} {dashboard_data['currency']}\n"
        f"👀 Deine Watchlist\n{watchlist_text}\n"
        f"🔔 Alarme: {dashboard_data['alarms']} aktiv\n"
        f"🎯 Sparziele: 0 (0.0% erreicht)\n"
        f"💸 Budget: {dashboard_data['budget'].get('total', dashboard_data['budget'].get('amount', 0)):.2f} {dashboard_data['currency']} (Ausgegeben: {dashboard_data['budget'].get('spent', 0):.2f})\n"
        f"💵 Fiat-Bestände: {', '.join([f'{currency}: {amount:.2f}' for currency, amount in dashboard_data['fiat_balances'].items()])}\n"
        f"🔄 Währung: {dashboard_data['currency']}"
    )
    await message.reply(dashboard_message, parse_mode="Markdown")

# Update the back button handler to show the full dashboard
@dp.callback_query(lambda c: c.data == "dash_back")
async def handle_back_to_dashboard(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    dashboard_data = await get_dashboard_data_cached(user_id)

    # Format the dashboard message
    watchlist_text = "\n".join([
        f"- {item['coin']}: {item['price']:.2f} {dashboard_data['currency']}"
        + (f" ({item['change']:+.2f}%" if item.get('change') is not None else "")
        + (f", RSI: {item['rsi']:.1f}" if item.get('rsi') is not None else "")
        + (f", MACD: {item['macd']:.2f}" if item.get('macd') is not None else "")
        + (')' if (item.get('change') is not None or item.get('rsi') is not None or item.get('macd') is not None) else '')
        for item in dashboard_data["watchlist"]
    ])
    dashboard_message = (
        f"📊 Vermögens-Dashboard\n\n"
        f"💼 Portfolio-Wert: {dashboard_data['portfolio_value']:.2f} {dashboard_data['currency']}\n"
        f"👀 Deine Watchlist\n{watchlist_text}\n"
        f"🔔 Alarme: {dashboard_data['alarms']} aktiv\n"
        f"🎯 Sparziele: 0 (0.0% erreicht)\n"
        f"💸 Budget: {dashboard_data['budget'].get('total', dashboard_data['budget'].get('amount', 0)):.2f} {dashboard_data['currency']} (Ausgegeben: {dashboard_data['budget'].get('spent', 0):.2f})\n"
        f"💵 Fiat-Bestände: {', '.join([f'{currency}: {amount:.2f}' for currency, amount in dashboard_data['fiat_balances'].items()])}\n"
        f"🔄 Währung: {dashboard_data['currency']}"
    )

    try:
        await cq.message.edit_text(
            dashboard_message,
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
    except Exception as e:
        if "message is not modified" in str(e):
            pass  # Ignoriere diesen harmlosen Fehler
        else:
            logger.error(f"[Dashboard] Fehler beim Editieren der Nachricht: {e}")

@dp.callback_query(lambda c: c.data == "dash_indicators")
async def handle_indicators_settings(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    user_indicators = set(settings.get("indicators", ["rsi"]))
    await cq.message.edit_text(
        "Wähle die Indikatoren, die im Dashboard/Watchlist angezeigt werden sollen:",
        reply_markup=indicators_keyboard(user_indicators)
    )

@dp.callback_query(lambda c: c.data.startswith("toggle_indicator:"))
async def handle_toggle_indicator(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    indicator = cq.data.split(":", 1)[1]
    settings = load_file(USER_SETTINGS_FILE)
    user_settings = settings.get(user_id, {})
    indicators = set(user_settings.get("indicators", ["rsi"]))
    if indicator in indicators:
        indicators.remove(indicator)
    else:
        indicators.add(indicator)
    user_settings["indicators"] = list(indicators)
    settings[user_id] = user_settings
    await save_file_async(USER_SETTINGS_FILE, settings)
    await cq.message.edit_text(
        "Wähle die Indikatoren, die im Dashboard/Watchlist angezeigt werden sollen:",
        reply_markup=indicators_keyboard(indicators)
    )

@dp.callback_query(lambda c: c.data == "dash_review")
async def handle_review_settings(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    enabled = settings.get("review_enabled", False)
    freq = settings.get("review_frequency", "daily")
    time_val = settings.get("review_time", "18:00")
    await cq.message.edit_text(
        "\U0001F4C8 *Portfolio-Rückblick Einstellungen*\n\nWähle, ob und wann du einen Rückblick erhalten möchtest:",
        parse_mode="Markdown",
        reply_markup=review_settings_keyboard(enabled, freq, time_val)
    )
    await cq.answer()

@dp.callback_query(lambda c: c.data.startswith("review_toggle:"))
async def handle_review_toggle(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE)
    user_settings = settings.get(user_id, {})
    onoff = cq.data.split(":")[1]
    user_settings["review_enabled"] = (onoff == "on")
    settings[user_id] = user_settings
    await save_file_async(USER_SETTINGS_FILE, settings)
    await handle_review_settings(cq, state)

@dp.callback_query(lambda c: c.data.startswith("review_freq:"))
async def handle_review_freq(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE)
    user_settings = settings.get(user_id, {})
    freq = cq.data.split(":")[1]
    user_settings["review_frequency"] = freq
    settings[user_id] = user_settings
    await save_file_async(USER_SETTINGS_FILE, settings)
    await handle_review_settings(cq, state)

@dp.callback_query(lambda c: c.data.startswith("review_time:"))
async def handle_review_time(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE)
    user_settings = settings.get(user_id, {})
    t = cq.data.split(":")[1]
    user_settings["review_time"] = t
    settings[user_id] = user_settings
    await save_file_async(USER_SETTINGS_FILE, settings)
    await handle_review_settings(cq, state)

async def send_portfolio_review(user_id, frequency):
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    now = datetime.now()
    if frequency == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "heute"
    else:
        # Wochenstart: Montag
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "diese Woche"
    # Finde Portfolio-Wert zu Startzeitpunkt (vereinfachte Methode: erste Transaktion nach Start)
    start_value = 0
    for t in sorted(transactions, key=lambda x: x["date"]):
        t_time = datetime.fromisoformat(t["date"])
        if t_time >= start:
            break
        if t["type"] == "buy":
            start_value += t["amount"] * t["price"]
        elif t["type"] == "sell":
            start_value -= t["amount"] * t["price"]
    # Aktueller Wert
    current_value = 0
    for coin, data in portfolio.items():
        if coin == "fiat":
            continue
        price = await get_price(coin, currency)
        if price:
            current_value += data.get("amount", 0) * price
    diff = current_value - start_value
    diff_pct = (diff / start_value * 100) if start_value else 0
    msg = (
        f"\U0001F4C8 *Portfolio-Rückblick* {label}\n\n"
        f"Aktueller Wert: {current_value:.2f} {currency}\n"
        f"Veränderung seit {label}: {diff:+.2f} {currency} ({diff_pct:+.2f}%)\n"
    )
    try:
        await bot.send_message(int(user_id), msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[Review] Fehler beim Senden des Rückblicks an {user_id}: {e}")

async def main():
    """Start the bot, register routers, and schedule background jobs.

    Responsibilities:
    - Include command and callback routers.
    - Configure periodic jobs: price checks, cache refresh, monthly reports and user reviews.
    - Start dispatcher polling and ensure proper shutdown logging.
    """
    logger.info("Bot is starting...")
    # Set Windows-specific event loop policy if applicable
    if hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logger.info("Event loop policy set (if running on Windows)")

    # Router zuerst einbinden, dann Bot-Commands setzen
    dp.include_router(commands.router)
    logger.info("commands.router included")
    dp.include_router(callbacks.router)
    logger.info("callbacks.router included (Callback-Handler wie dash_back sollten jetzt aktiv sein)")

    # Bot-Commands setzen (async, aber nicht blockierend für Router)
    asyncio.create_task(commands.set_bot_commands(bot))
    logger.info("Bot-Commands werden asynchron gesetzt.")

    scheduler = AsyncIOScheduler()
    # Scheduler-Jobs direkt als async/coroutine eintragen
    scheduler.add_job(check_prices, "interval", minutes=1)
    logger.info("Scheduler für Preisüberwachung gestartet.")
    for user_id in load_file(PORTFOLIO_FILE).keys():
        logger.debug(f"[Scheduler] Monatlicher Report-Job für User {user_id} wird geplant.")
        scheduler.add_job(lambda uid=user_id: send_monthly_report(uid), "cron", day=1, hour=0)
        logger.debug(f"Monatlicher Report-Job für User {user_id} geplant.")
    scheduler.add_job(update_global_price_cache, "interval", seconds=10)
    logger.info("Scheduler für globalen Preis-Cache gestartet (alle 10s)")

    # Nach dem Start: Rückblick-Jobs für alle User anlegen
    settings_all = load_file(USER_SETTINGS_FILE)
    for user_id, user_settings in settings_all.items():
        if user_settings.get("review_enabled"):
            freq = user_settings.get("review_frequency", "daily")
            time_str = user_settings.get("review_time", "18:00")
            hour, minute = map(int, time_str.split(":"))
            job_id = f"review_{user_id}"
            # Entferne evtl. alten Job
            try:
                scheduler.remove_job(job_id)
            except Exception:
                pass
            if freq == "daily":
                scheduler.add_job(lambda uid=user_id: send_portfolio_review(uid, "daily"), "cron", hour=hour, minute=minute, id=job_id)
            else:
                scheduler.add_job(lambda uid=user_id: send_portfolio_review(uid, "weekly"), "cron", day_of_week="mon", hour=hour, minute=minute, id=job_id)

    scheduler.start()
    logger.info("Scheduler gestartet. Starte Polling...")

    try:
        logger.info("Starte dp.start_polling...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.exception("Fehler beim Starten des Bots:")
    finally:
        logger.info("Bot wurde gestoppt.")

if __name__ == "__main__":
    try:
        logger.info("Starte asyncio.run(main()) ...")
        asyncio.run(main())
    except Exception as e:
        logger.exception("Unerwarteter Fehler im Hauptprozess:")
