"""Command handlers for the Telegram bot.

This module registers command handlers and callback flows used by the
bot. It contains language/localization mappings, helper utilities for
translations, state group definitions for multi-step dialogs, and a
collection of command handlers that build and send textual responses
and inline keyboards.

Notes:
- This file focuses on interaction code only; business logic and data
  access are delegated to functions in `utils` and `utils_cache`.
- All user-visible strings are left intact to preserve localization
  semantics; only internal comments have been converted to English.
"""

from aiogram import Bot, Dispatcher, types
from aiogram import Router
from aiogram.filters import Command, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from config.config import BOT_TOKEN, COIN_LIST, ALARM_FILE, PORTFOLIO_FILE, WATCHLIST_FILE, SAVINGS_FILE, BUDGET_FILE, TRANSACTIONS_FILE, USER_SETTINGS_FILE, ACHIEVEMENTS_FILE, FIAT_TRANSACTIONS_FILE
from utils import get_price, get_24h_change, get_volatility, get_historical_prices, calculate_rsi, load_file, save_file_async
from keyboards import coin_keyboard, dashboard_keyboard, chart_select_keyboard, watchlist_alarm_keyboard, settings_keyboard, percent_period_keyboard, indicator_type_keyboard, repeat_keyboard
from states import BotStates
from aiogram.fsm.state import StatesGroup, State
import time
import json
import random
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from utils_cache import (
    get_price_cached_from_file, get_24h_change_cached_from_file, calculate_rsi_cached_from_file,
    get_price_cached_from_file_async, get_24h_change_cached_from_file_async, calculate_rsi_cached_from_file_async
)


class PercentAlertStates(StatesGroup):
    """FSM states for the percent-change alert creation flow."""
    choosing_coin = State()
    entering_percent = State()
    entering_period = State()
    entering_repeat = State()


class IndicatorAlertStates(StatesGroup):
    """FSM states for the indicator-based alert creation flow."""
    choosing_coin = State()
    choosing_type = State()
    entering_value = State()
    entering_repeat = State()


bot = Bot(token=BOT_TOKEN)
router = Router()

# Localization payloads for supported languages (German and English)
LANGUAGES = {
    "de": {
        "welcome": "👋 *Willkommen beim Krypto-Alarm-Bot!*\nVerwalte dein Krypto-Vermögen mit unserer Mini-App:\n\n"
                    "📊 */dashboard* – Zentrale Vermögensübersicht\n"
                    "📈 */price* – Aktuellen Preis eines Coins abfragen\n"
                    "🔔 */setalarm* – Preisalarm setzen\n"
                    "📋 */myalarms* – Deine aktiven Alarme anzeigen\n"
                    "🔥 */trending* – Top-5 Coins mit Preissprüngen\n"
                    "💼 */portfolio* – Dein virtuelles Portfolio verwalten\n"
                    "⚡ */volatility* – Volatilität eines Coins prüfen\n"
                    "👀 */watchlist* – Deine Watchlist verwalten\n"
                    "🎯 */savings* – Sparziele setzen und verfolgen\n"
                    "💸 */budget* – Budget für Krypto-Käufe festlegen\n"
                    "📊 */charts* – Erweiterte Charts anzeigen\n"
                    "🏆 */achievements* – Deine Erfolge anzeigen\n"
                    "💵 */fiat* – Fiat-Bestände verwalten\n"
                    "📥 */export* – Deine Daten exportieren\n"
                    "🔒 */privacy* – Datenschutzerklärung anzeigen\n"
                    "🗑️ */reset* – Alle Daten löschen\n\n"
                    "Starte mit */dashboard* für eine Übersicht!",
        "analyze_title": "📈 *Portfolio-Analyse*",
        "analyze_diversity": "Diversifikation: {diversity}",
        "analyze_best": "Bester Coin: {best}",
        "analyze_worst": "Schwächster Coin: {worst}",
        "analyze_tip": "Tipp: {tip}",
        "set_percent_alarm": "Gib den Prozentsatz für den Alarm ein (z.B. 2 für 2%):",
        "set_percent_period": "Für welchen Zeitraum? (z.B. 24 für 24h):",
        "set_percent_repeat": "Soll der Alarm wiederholt werden? (ja/nein):",
        "percent_alarm_set": "Prozentualer Alarm für {coin} gesetzt: {percent}% in {period}h, wiederholt: {repeat}",
        "choose_language": "Wähle deine Sprache:",
        "language_set": "Sprache auf {lang} gesetzt.",
        "widgets_config": "Konfiguriere deine Widgets:",
        "widget_favcoins": "Lieblingscoins gespeichert.",
    },
    "en": {
        "welcome": "👋 *Welcome to the Crypto Alert Bot!*\nManage your crypto assets with our mini-app:\n\n"
                   "📊 */dashboard* – Central asset overview\n"
                   "📈 */price* – Query the current price of a coin\n"
                   "🔔 */setalarm* – Set price alert\n"
                   "📋 */myalarms* – View your active alerts\n"
                   "🔥 */trending* – Top-5 coins with price jumps\n"
                   "💼 */portfolio* – Manage your virtual portfolio\n"
                   "⚡ */volatility* – Check the volatility of a coin\n"
                   "👀 */watchlist* – Manage your watchlist\n"
                   "🎯 */savings* – Set and track savings goals\n"
                   "💸 */budget* – Set budget for crypto purchases\n"
                   "📊 */charts* – View advanced charts\n"
                   "🏆 */achievements* – View your achievements\n"
                   "💵 */fiat* – Manage fiat balances\n"
                   "📥 */export* – Export your data\n"
                   "🔒 */privacy* – View privacy policy\n"
                   "🗑️ */reset* – Delete all data\n\n"
                   "Start with */dashboard* for an overview!",
        "analyze_title": "📈 *Portfolio Analysis*",
        "analyze_diversity": "Diversity: {diversity}",
        "analyze_best": "Best coin: {best}",
        "analyze_worst": "Worst coin: {worst}",
        "analyze_tip": "Tip: {tip}",
        "set_percent_alarm": "Enter the percentage for the alert (e.g. 2 for 2%):",
        "set_percent_period": "For which period? (e.g. 24 for 24h):",
        "set_percent_repeat": "Should the alert repeat? (yes/no):",
        "percent_alarm_set": "Percent alert for {coin} set: {percent}% in {period}h, repeat: {repeat}",
        "choose_language": "Choose your language:",
        "language_set": "Language set to {lang}.",
        "widgets_config": "Configure your widgets:",
        "widget_favcoins": "Favorite coins saved.",
    }
}

def t(user_id, key, **kwargs):
    """Return a localized string for a user and format it.

    Reads the user's settings from `USER_SETTINGS_FILE` and falls back
    to German if no preference is found. The returned string is
    formatted with any provided keyword arguments.
    """
    settings = load_file(USER_SETTINGS_FILE).get(str(user_id), {"language": "de"})
    lang = settings.get("language", "de")
    return LANGUAGES.get(lang, LANGUAGES["de"])[key].format(**kwargs)

async def set_bot_commands(bot: Bot):
    """Register a set of BotCommand entries shown in the Telegram UI.

    This function prepares the list of available commands and sets
    them using `bot.set_my_commands` so they appear in the client's
    command suggestion UI.
    """

    commands = [
        types.BotCommand(command="start", description="Willkommen beim Krypto-Alarm-Bot"),
        types.BotCommand(command="dashboard", description="Zentrale Vermögensübersicht"),
        types.BotCommand(command="price", description="Aktuellen Preis eines Coins abfragen"),
        types.BotCommand(command="setalarm", description="Preisalarm setzen"),
        types.BotCommand(command="myalarms", description="Deine aktiven Alarme anzeigen"),
        types.BotCommand(command="trending", description="Top-5 Coins mit Preissprüngen"),
        types.BotCommand(command="portfolio", description="Dein virtuelles Portfolio verwalten"),
        types.BotCommand(command="volatility", description="Volatilität eines Coins prüfen"),
        types.BotCommand(command="watchlist", description="Deine Watchlist verwalten"),
        types.BotCommand(command="savings", description="Sparziele setzen und verfolgen"),
        types.BotCommand(command="budget", description="Budget für Krypto-Käufe festlegen"),
        types.BotCommand(command="charts", description="Erweiterte Charts anzeigen"),
        types.BotCommand(command="achievements", description="Deine Erfolge anzeigen"),
        types.BotCommand(command="fiat", description="Fiat-Bestände verwalten"),
        types.BotCommand(command="export", description="Deine Daten exportieren"),
        types.BotCommand(command="privacy", description="Datenschutzerklärung anzeigen"),
        types.BotCommand(command="reset", description="Alle Daten löschen"),
        types.BotCommand(command="status", description="Bot-Status überprüfen"),
        types.BotCommand(command="settings", description="Show settings"),
    ]
    await bot.set_my_commands(commands)


async def cmd_start(message: types.Message):
    """Handle `/start`: send welcome message and show dashboard keyboard."""
    await message.reply(
        t(message.from_user.id, "welcome"),
        parse_mode="Markdown",
        reply_markup=dashboard_keyboard()
    )
router.message.register(cmd_start, Command("start"))

async def cmd_dashboard(message: types.Message):
    """Assemble and send the user's dashboard summary.

    The dashboard aggregates portfolio value, watchlist snippets,
    active alarms, savings progress, budget and fiat balances.
    """
    user_id = str(message.from_user.id)
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
    alarms = load_file(ALARM_FILE).get(user_id, [])
    savings = load_file(SAVINGS_FILE).get(user_id, {})
    budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    fiat = portfolio.get("fiat", {})

    total_value = 0
    for coin, data in portfolio.items():
        if coin == "fiat":
            for curr, amount in data.items():
                if curr != currency:
                    total_value += amount * 0.9 if curr == "USD" and currency == "EUR" else amount / 0.9
                else:
                    total_value += amount
        else:
            price = get_price_cached_from_file(coin, currency)
            if price:
                total_value += price * data["amount"]

    savings_count = len(savings)
    savings_progress = 0
    if savings:
        for coin, data in savings.items():
            current = portfolio.get(coin, {"amount": 0})["amount"]
            savings_progress += min(current / data["target"], 1) * 100 / savings_count

    show_rsi = settings.get("show_watchlist_rsi", True)
    watchlist_lines = []
    for coin in watchlist:
        price = get_price_cached_from_file(coin, currency)
        change = get_24h_change_cached_from_file(coin)
        rsi = calculate_rsi_cached_from_file(coin)
        if price is not None and change is not None:
            line = f"- {coin}: {price:.2f} {currency} ({'+' if change > 0 else ''}{change:.2f}%"
            if show_rsi and rsi is not None:
                line += f", RSI: {rsi:.1f}"
            line += ")"
        elif price is not None:
            line = f"- {coin}: {price:.2f} {currency} (Daten unvollständig)"
        else:
            line = f"- {coin}: Daten nicht verfügbar"
        watchlist_lines.append(line)
    watchlist_str = '\n'.join(watchlist_lines) if watchlist_lines else 'Keine'

    response = (
        f"📊 *Vermögens-Dashboard*\n\n"
        f"💼 Portfolio-Wert: **{total_value:.2f} {currency}**\n"
        f"👀 Deine Watchlist\n{watchlist_str}\n"
        f"🔔 Alarme: {len(alarms)} aktiv\n"
        f"🎯 Sparziele: {savings_count} ({savings_progress:.1f}% erreicht)\n"
        f"💸 Budget: {budget['amount']:.2f} {currency} (Ausgegeben: {budget['spent']:.2f})\n"
        f"💵 Fiat-Bestände: {', '.join([f'{k}: {v:.2f}' for k, v in fiat.items()]) or 'Keine'}\n"
        f"🔄 Währung: {currency}"
    )
    await message.reply(response, reply_markup=dashboard_keyboard(), parse_mode="Markdown")
router.message.register(cmd_dashboard, Command("dashboard"))

async def cmd_charts(message: types.Message, state: FSMContext):
    """Show the chart selection keyboard and set the FSM state."""
    await message.reply(
        "📊 *Chart auswählen*",
        parse_mode="Markdown",
        reply_markup=chart_select_keyboard()
    )
    await state.set_state(BotStates.chart_select)
router.message.register(cmd_charts, Command("charts"))

async def cmd_price(message: types.Message, state: FSMContext):
    """Initiate the price query flow by asking the user to choose a coin."""
    await message.reply("Wähle einen Coin für die Preisabfrage:", reply_markup=coin_keyboard(for_price=True))
    await state.set_state(BotStates.choosing_coin)
router.message.register(cmd_price, Command("price"))

async def cmd_setalarm(message: types.Message, state: FSMContext):
    """Start the generic alarm creation flow by prompting coin selection."""
    await message.reply("Wähle den Coin für deinen Alarm:", reply_markup=coin_keyboard())
    await state.set_state(BotStates.choosing_coin)
router.message.register(cmd_setalarm, Command("setalarm"))

async def cmd_myalarms(message: types.Message):
    """List the user's active alarms with inline controls to delete them."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    alarms = load_file(ALARM_FILE).get(user_id, [])
    if not alarms:
        await message.reply(
            "ℹ️ Du hast keine aktiven Alarme.",
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, alarm in enumerate(alarms):
        if alarm["type"] == "price":
            if alarm["direction"] == "percent":
                text = f"{alarm['coin']} ±{alarm['target']:.1f}% (Ausgelöst: {alarm['trigger_count']})"
            else:
                direction = "📉 unter" if alarm["direction"] == "below" else "📈 über"
                text = f"{alarm['coin']} {direction} {alarm['target']:.0f} {currency} (Ausgelöst: {alarm['trigger_count']})"
        else:  # Watchlist alarm
            direction = "📈 über" if alarm["alarm_type"] == "rsi_overbought" else "📉 unter" if alarm["alarm_type"] == "rsi_oversold" else "⚡"
            target = f"{alarm['target']:.0f}" if alarm["alarm_type"].startswith("rsi_") else f"{alarm['target']:.1f}%"
            text = f"{alarm['coin']} {direction} {target} (Ausgelöst: {alarm['trigger_count']})"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=text, callback_data=f"delete:{i}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🗑️ Alle löschen", callback_data="delete_all"),
                              InlineKeyboardButton(text="🔔 Neuen Alarm", callback_data="set_alarm")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")])
    await message.reply("🔔 *Deine aktiven Alarme*:", reply_markup=kb, parse_mode="Markdown")
router.message.register(cmd_myalarms, Command("myalarms"))

async def cmd_trending(message: types.Message):
    """Compute and show the top-5 trending coins by 24h change."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    trending = []
    for coin in COIN_LIST:
        change = get_24h_change(coin)
        if change is not None:
            trending.append((coin, change))
    trending.sort(key=lambda x: abs(x[1]), reverse=True)
    top_5 = trending[:5]
    response = "🔥 *Top-5 Trending Coins (24h)*:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, (coin, change) in enumerate(top_5, 1):
        response += f"{i}. *{coin}*: **{'+' if change > 0 else ''}{change:.2f}%**\n"
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"Preis: {coin}", callback_data=f"trend_price:{coin}"),
            InlineKeyboardButton(text=f"Alarm: {coin}", callback_data=f"trend_alarm:{coin}"),
            InlineKeyboardButton(text=f"Vol.: {coin}", callback_data=f"trend_vol:{coin}")
        ])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")])
    await message.reply(response, reply_markup=kb, parse_mode="Markdown")
router.message.register(cmd_trending, Command("trending"))

async def cmd_portfolio(message: types.Message):
    """Render the user's portfolio details and quick action keyboard."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    if not portfolio or (len(portfolio) == 1 and "fiat" in portfolio):
        await message.reply(
            "💼 *Dein Portfolio ist leer.*\nFüge Coins oder Fiat hinzu:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Kaufen", callback_data="portfolio_buy"),
                 InlineKeyboardButton(text="💵 Einzahlen", callback_data="fiat_deposit")],
                [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        return
    total_value = 0
    response = "💼 *Dein Portfolio*\n\n"
    for coin, data in portfolio.items():
        if coin == "fiat":
            for curr, amount in data.items():
                if curr != currency:
                    rate = 0.9 if curr == "USD" and currency == "EUR" else 1/0.9
                    total_value += amount * rate
                    response += f"- *{curr}*: {amount:.2f} ({amount * rate:.2f} {currency})\n"
                else:
                    total_value += amount
                    response += f"- *{curr}*: {amount:.2f}\n"
        else:
            price = get_price_cached_from_file(coin, currency)
            if price:
                value = price * data["amount"]
                total_value += value
                gain_loss = (price - data["buy_price"]) * data["amount"]
                response += f"- *{coin}*: {data['amount']:.4f} ({value:.2f} {currency}, {'+' if gain_loss > 0 else ''}{gain_loss:.2f})\n"
    response += f"\n📊 Gesamtwert: **{total_value:.2f} {currency}**"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Kaufen", callback_data="portfolio_buy"),
         InlineKeyboardButton(text="➖ Verkaufen", callback_data="portfolio_sell")],
        [InlineKeyboardButton(text="📜 Historie", callback_data="portfolio_history"),
         InlineKeyboardButton(text="💵 Einzahlen", callback_data="fiat_deposit")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_portfolio, Command("portfolio"))

async def cmd_fiat(message: types.Message, state: FSMContext):
    """Show fiat balances and actions to deposit/withdraw."""
    user_id = str(message.from_user.id)
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    fiat = portfolio.get("fiat", {})
    response = "💵 *Fiat-Bestände*\n\n"
    if not fiat:
        response += "Keine Fiat-Bestände. Zahle etwas ein!"
    else:
        for curr, amount in fiat.items():
            response += f"- *{curr}*: {amount:.2f}\n"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Einzahlen", callback_data="fiat_deposit"),
         InlineKeyboardButton(text="➖ Auszahlen", callback_data="fiat_withdraw")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_fiat, Command("fiat"))

# --- Combined savings & budget menu ---
async def cmd_goals(message: types.Message, state: FSMContext):
    """Show savings goals and budget summary with quick actions."""
    user_id = str(message.from_user.id)
    savings = load_file(SAVINGS_FILE).get(user_id, {})
    budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    response = "🎯 *Sparziele & Budget*\n\n"
    if not savings:
        response += "Keine Sparziele. Füge ein Ziel hinzu!\n"
    else:
        for coin, data in savings.items():
            current = load_file(PORTFOLIO_FILE).get(user_id, {}).get(coin, {"amount": 0})["amount"]
            progress = (current / data["target"]) * 100 if data["target"] else 0
            response += f"- *{coin}*: {current:.4f}/{data['target']:.4f} ({progress:.1f}%)\n"
    response += f"\n💸 *Budget*: {budget['amount']:.2f} {currency}\nAusgegeben: {budget['spent']:.2f} {currency}"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Sparziel", callback_data="savings_add"),
         InlineKeyboardButton(text="✏️ Budget setzen", callback_data="budget_set")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_goals, Command("goals"))

async def cmd_watchlist(message: types.Message):
    """Display the user's watchlist and latest price/RSI snippets."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
    response = "👀 *Deine Watchlist (Lieblingscoins)*\n\n"
    if not watchlist:
        response += "Leer. Füge Coins hinzu!"
    else:
        for coin in watchlist:
            price = get_price_cached_from_file(coin, currency)
            change = get_24h_change_cached_from_file(coin)
            rsi = calculate_rsi_cached_from_file(coin)
            if price and change is not None:
                response += f"- *{coin}*: **{price:.2f} {currency}** ({'+' if change > 0 else ''}{change:.2f}%"
                if rsi:
                    response += f", RSI: {rsi:.1f}"
                response += ")\n"
            else:
                response += f"- *{coin}*: Daten nicht verfügbar\n"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Coin hinzufügen", callback_data="watchlist_add"),
         InlineKeyboardButton(text="➖ Coin entfernen", callback_data="watchlist_remove")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_watchlist, Command("watchlist"))

async def cmd_volatility(message: types.Message, state: FSMContext):
    """Start the volatility check flow by asking the user to choose a coin."""
    await message.reply("Wähle einen Coin für die Volatilitätsprüfung:", reply_markup=coin_keyboard())
    await state.set_state(BotStates.volatility_select)
router.message.register(cmd_volatility, Command("volatility"))

async def cmd_status(message: types.Message):
    """Send a quick status check including ping latency."""
    start_time = time.time()
    try:
        test_message = await bot.send_message(message.chat.id, "Ping test...")
        ping_ms = (time.time() - start_time) * 1000  # Convert to milliseconds
        await bot.delete_message(message.chat.id, test_message.message_id)
        await message.reply(
            f"🟢 *Bot Status*\n\n- Status: **Online**\n- Ping: **{ping_ms:.2f} ms**",
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
    except Exception as e:
        await message.reply(
            f"🔴 *Bot Status*\n\n- Status: **Error**\n- Error: {str(e)}",
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
router.message.register(cmd_status, Command("status"))

async def cmd_savings(message: types.Message, state: FSMContext):
    """Show detailed savings goals and allow adding new targets."""
    user_id = str(message.from_user.id)
    savings = load_file(SAVINGS_FILE).get(user_id, {})
    if not savings:
        await message.reply(
            "🎯 *Keine Sparziele.*\nFüge ein Ziel hinzu:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Sparziel", callback_data="savings_add"),
                 InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        return
    response = "🎯 *Deine Sparziele*\n\n"
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    for coin, data in savings.items():
        current = portfolio.get(coin, {"amount": 0})["amount"]
        progress = (current / data["target"]) * 100
        response += f"- *{coin}*: {current:.4f}/{data['target']:.4f} ({progress:.1f}%)\n"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Sparziel", callback_data="savings_add"),
         InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_savings, Command("savings"))

async def cmd_budget(message: types.Message, state: FSMContext):
    """Display and allow editing of the user's monthly budget."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
    await message.reply(
        f"💸 *Budget*\n\nMonatliches Budget: {budget['amount']:.2f} {currency}\nAusgegeben: {budget['spent']:.2f} {currency}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Budget setzen", callback_data="budget_set"),
             InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
        ]), parse_mode="Markdown"
    )
router.message.register(cmd_budget, Command("budget"))

async def cmd_achievements(message: types.Message):
    """Present the user's earned achievements and basic navigation."""
    user_id = str(message.from_user.id)
    achievements = load_file(ACHIEVEMENTS_FILE).get(user_id, {})
    response = "🏆 *Deine Erfolge*\n\n"
    if not achievements:
        response += "Keine Erfolge bisher. Führe Aktionen aus, um welche freizuschalten!"
    else:
        for key, data in achievements.items():
            response += f"- *{data['name']}* ({data['date'][:10]}): {data['description']}\n"
    await message.reply(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistik", callback_data="dash_stats"),
         InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
router.message.register(cmd_achievements, Command("achievements"))

async def cmd_export(message: types.Message):
    """Bundle user data into a JSON file and send it as a document."""
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {"currency": "USD"})
    currency = settings.get("currency", "USD")
    data = {
        "portfolio": load_file(PORTFOLIO_FILE).get(user_id, {}),
        "watchlist": load_file(WATCHLIST_FILE).get(user_id, []),
        "alarms": load_file(ALARM_FILE).get(user_id, []),
        "savings": load_file(SAVINGS_FILE).get(user_id, {}),
        "budget": load_file(BUDGET_FILE).get(user_id, {}),
        "transactions": load_file(TRANSACTIONS_FILE).get(user_id, []),
        "fiat_transactions": load_file(FIAT_TRANSACTIONS_FILE).get(user_id, []),
        "achievements": load_file(ACHIEVEMENTS_FILE).get(user_id, {})
    }
    export_data = json.dumps(data, indent=2).encode('utf-8')
    file = types.BufferedInputFile(export_data, filename=f"crypto_data_{user_id}.json")
    await message.reply_document(
        document=file,
        caption="📥 *Deine Daten wurden exportiert.*",
        parse_mode="Markdown",
        reply_markup=dashboard_keyboard()
    )
router.message.register(cmd_export, Command("export"))

async def cmd_privacy(message: types.Message):
    """Send the privacy policy describing local data handling."""
    await message.reply(
        "🔒 *Datenschutzerklärung*\n\n"
        "Deine Daten (Portfolio, Alarme, etc.) werden lokal in JSON-Dateien gespeichert und nur für die Funktionen des Bots verwendet. "
        "Keine Daten werden an Dritte weitergegeben. Nutze */export* für eine Kopie deiner Daten oder */reset* zum Löschen.",
        parse_mode="Markdown",
        reply_markup=dashboard_keyboard()
    )
router.message.register(cmd_privacy, Command("privacy"))

async def cmd_reset(message: types.Message, state: FSMContext):
    code = str(random.randint(1000, 9999))
    await state.update_data(reset_code=code)
    await message.reply(
        f"⚠️ *Daten zurücksetzen?*\nDas löscht alle deine Daten unwiderruflich!\nBestätige mit dem Code: **{code}**",
        parse_mode="Markdown",
        reply_markup=dashboard_keyboard()
    )
    await state.set_state(BotStates.confirm_reset_code)
router.message.register(cmd_reset, Command("reset"))

# --- Dynamischer Prozent-Alarm ---
class PercentAlarmStates(StatesGroup):
    choosing_coin = State()
    entering_percent = State()
    entering_period = State()
    entering_repeat = State()

@router.message(Command("setpercentalarm"))
async def cmd_setpercentalarm(message: types.Message, state: FSMContext):
    await message.reply("Wähle den Coin für deinen prozentualen Alarm:", reply_markup=coin_keyboard())
    await state.set_state(PercentAlarmStates.choosing_coin)

@router.callback_query(StateFilter(PercentAlarmStates.choosing_coin))
async def percent_alarm_coin_chosen(cq: types.CallbackQuery, state: FSMContext):
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)
    await cq.message.edit_text("Gib den Prozentsatz für den Alarm ein (z.B. 2 für 2%):")
    await state.set_state(PercentAlarmStates.entering_percent)
    await cq.answer()

@router.message(StateFilter(PercentAlarmStates.entering_percent))
async def percent_alarm_enter_percent(message: types.Message, state: FSMContext):
    try:
        percent = float(message.text.replace(",", "."))
        await state.update_data(percent=percent)
        await message.reply("Für welchen Zeitraum?", reply_markup=percent_period_keyboard())
        await state.set_state(PercentAlarmStates.entering_period)
    except ValueError:
        await message.reply("Bitte gib eine gültige Zahl ein.")

@router.callback_query(lambda c: c.data.startswith("percent_period:"), StateFilter(PercentAlarmStates.entering_period))
async def percent_alarm_period_chosen(cq: types.CallbackQuery, state: FSMContext):
    period = int(cq.data.split(":")[1])
    await state.update_data(period=period)
    await cq.message.edit_text("Soll der Alarm einmalig oder immer wieder ausgelöst werden?", reply_markup=repeat_keyboard())
    await state.set_state(PercentAlarmStates.entering_repeat)
    await cq.answer()

@router.callback_query(lambda c: c.data.startswith("repeat:"), StateFilter(PercentAlarmStates.entering_repeat))
async def percent_alarm_repeat_chosen(cq: types.CallbackQuery, state: FSMContext):
    repeat = cq.data.split(":")[1]
    data = await state.get_data()
    user_id = str(cq.from_user.id)
    alarms = load_file(ALARM_FILE)
    if user_id not in alarms:
        alarms[user_id] = []
    alarms[user_id].append({
        "type": "percent",
        "coin": data["coin"],
        "percent": data["percent"],
        "period": data["period"],
        "repeat": (repeat == "always"),
        "triggered": False
    })
    await save_file_async(ALARM_FILE, alarms)
    await cq.message.edit_text(f"Prozent-Alarm für {data['coin']} gesetzt: {data['percent']}% in {data['period']}min, {'immer' if repeat=='always' else 'einmalig'}.", reply_markup=dashboard_keyboard())
    await state.clear()
    await cq.answer()

# --- Portfolio-Analyse ---
@router.message(Command("analyze"))
async def cmd_analyze(message: types.Message):
    user_id = str(message.from_user.id)
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    if not portfolio or (len(portfolio) == 1 and "fiat" in portfolio):
        await message.reply("Kein Portfolio vorhanden.")
        return
    coins = [c for c in portfolio if c != "fiat"]
    values = {}
    best, worst, best_perf, worst_perf = None, None, -99999, 99999
    total = 0
    for coin in coins:
        price = get_price(coin)
        amount = portfolio[coin]["amount"]
        value = price * amount if price else 0
        values[coin] = value
        total += value
        # Performance
        buys = [t for t in transactions if t["coin"] == coin and t["type"] == "buy"]
        sells = [t for t in transactions if t["coin"] == coin and t["type"] == "sell"]
        buy_sum = sum(t["amount"] * t["price"] for t in buys)
        sell_sum = sum(t["amount"] * t["price"] for t in sells)
        perf = (value + sell_sum - buy_sum) / buy_sum * 100 if buy_sum else 0
        if perf > best_perf:
            best, best_perf = coin, perf
        if perf < worst_perf:
            worst, worst_perf = coin, perf
    diversity = len(coins)
    tip = "Gut diversifiziert!" if diversity >= 5 else "Mehr Diversifikation empfohlen."
    resp = f"{t(user_id, 'analyze_title')}\n\n" \
           f"{t(user_id, 'analyze_diversity', diversity=diversity)}\n" \
           f"{t(user_id, 'analyze_best', best=best)} ({best_perf:.1f}%)\n" \
           f"{t(user_id, 'analyze_worst', worst=worst)} ({worst_perf:.1f}%)\n" \
           f"{t(user_id, 'analyze_tip', tip=tip)}"
    await message.reply(resp, parse_mode="Markdown")

# --- Sprachwahl ---
@router.message(Command("language"))
async def cmd_language(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Deutsch", callback_data="lang:de"),
         InlineKeyboardButton(text="English", callback_data="lang:en")]
    ])
    await message.reply(t(message.from_user.id, "choose_language"), reply_markup=kb)

@router.callback_query(lambda c: c.data.startswith("lang:"))
async def set_language(cq: types.CallbackQuery):
    lang = cq.data.split(":")[1]
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    settings["language"] = lang
    await save_file_async(USER_SETTINGS_FILE, {user_id: settings})
    await cq.message.answer(t(user_id, "language_set", lang="Deutsch" if lang=="de" else "English"))
    await cq.answer()

# --- Widgets (Lieblingscoins) ---
@router.message(Command("widgets"))
async def cmd_widgets(message: types.Message, state: FSMContext):
    await message.reply(t(message.from_user.id, "widgets_config") + "\nSende eine kommagetrennte Liste deiner Lieblingscoins (z.B. BTC,ETH,ADA):")
    await state.set_state(BotStates.manual_coin_input)

@router.message(StateFilter(BotStates.manual_coin_input))
async def save_favcoins(message: types.Message, state: FSMContext):
    coins = [c.strip().upper() for c in message.text.split(",") if c.strip()]
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    settings["favcoins"] = coins
    await save_file_async(USER_SETTINGS_FILE, {user_id: settings})
    await message.reply(t(user_id, "widget_favcoins"))
    await state.clear()

async def cmd_settings(message: types.Message):
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    # Rückblick-Button in die Settings einfügen
    settings_kb = settings_keyboard(
        dark_mode=settings.get("dark_mode", False),
        show_watchlist_rsi=settings.get("show_watchlist_rsi", True)
    )
    # Rückblick-Button ergänzen
    settings_kb.inline_keyboard.insert(-1, [types.InlineKeyboardButton(text="\U0001F4C8 Portfolio-Rückblick", callback_data="dash_review")])
    await message.reply(
        "⚙️ *Einstellungen*",
        parse_mode="Markdown",
        reply_markup=settings_kb
    )

router.message.register(cmd_settings, Command("settings"))

# --- Prozentualer Preis-Alert Dialog ---
@router.message(Command("setpercentalert"))
async def start_percent_alert(message: types.Message, state: FSMContext):
    await message.reply("Für welchen Coin möchtest du einen Prozent-Alert setzen?", reply_markup=coin_keyboard())
    await state.set_state(BotStates.percent_alert_coin)

@router.callback_query(StateFilter(BotStates.percent_alert_coin))
async def percent_alert_coin_chosen(cq: types.CallbackQuery, state: FSMContext):
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)
    await cq.message.edit_text(f"Prozent-Alert für {coin}. Gib den Schwellenwert in % an (z.B. 2 für 2%):")
    await state.set_state(BotStates.percent_alert_value)
    try:
        await cq.answer()
    except Exception:
        pass

@router.message(StateFilter(BotStates.percent_alert_value))
async def percent_alert_value_entered(message: types.Message, state: FSMContext):
    try:
        percent = float(message.text.replace(",", "."))
        if percent <= 0:
            raise ValueError
    except ValueError:
        await message.reply("Bitte gib eine positive Prozentzahl ein (z.B. 2 für 2%).")
        return
    await state.update_data(percent=percent)
    await message.reply("Für welches Zeitfenster?", reply_markup=percent_period_keyboard())
    await state.set_state(BotStates.percent_alert_period)

@router.callback_query(lambda c: c.data.startswith("percent_period:"), StateFilter(BotStates.percent_alert_period))
async def percent_alert_period_chosen(cq: types.CallbackQuery, state: FSMContext):
    period = int(cq.data.split(":")[1])
    await state.update_data(period=period)
    await cq.message.edit_text("Soll der Alert einmalig oder immer wieder ausgelöst werden?", reply_markup=repeat_keyboard())
    await state.set_state(BotStates.percent_alert_repeat)
    try:
        await cq.answer()
    except Exception:
        pass

@router.callback_query(lambda c: c.data.startswith("repeat:"), StateFilter(BotStates.percent_alert_repeat))
async def percent_alert_repeat_chosen(cq: types.CallbackQuery, state: FSMContext):
    repeat = cq.data.split(":")[1]
    data = await state.get_data()
    user_id = str(cq.from_user.id)
    alarms = load_file(ALARM_FILE)
    if user_id not in alarms:
        alarms[user_id] = []
    alarms[user_id].append({
        "type": "percent",
        "coin": data["coin"],
        "percent": data["percent"],
        "period": data["period"],
        "repeat": (repeat == "always"),
        "triggered": False
    })
    await save_file_async(ALARM_FILE, alarms)
    await cq.message.edit_text(f"Prozent-Alert für {data['coin']} gesetzt: {data['percent']}% in {data['period']}min, {'immer' if repeat=='always' else 'einmalig'}.", reply_markup=dashboard_keyboard())
    await state.clear()
    try:
        await cq.answer()
    except Exception:
        pass

# --- Indikator-Alert Dialog ---
@router.message(Command("setindicatoralert"))
async def start_indicator_alert(message: types.Message, state: FSMContext):
    await message.reply("Für welchen Coin möchtest du einen Indikator-Alert setzen?", reply_markup=coin_keyboard())
    await state.set_state(BotStates.indicator_alert_coin)

@router.callback_query(StateFilter(BotStates.indicator_alert_coin))
async def indicator_alert_coin_chosen(cq: types.CallbackQuery, state: FSMContext):
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)
    await cq.message.edit_text(f"Indikator-Alert für {coin}. Wähle den Indikator:", reply_markup=indicator_type_keyboard())
    await state.set_state(BotStates.indicator_alert_type)
    try:
        await cq.answer()
    except Exception:
        pass

@router.callback_query(lambda c: c.data.startswith("indicator_type:"), StateFilter(BotStates.indicator_alert_type))
async def indicator_alert_type_chosen(cq: types.CallbackQuery, state: FSMContext):
    indicator = cq.data.split(":")[1]
    await state.update_data(indicator=indicator)
    if indicator in ["rsi_overbought", "rsi_oversold"]:
        await cq.message.edit_text("Gib den Schwellenwert für den RSI ein (z.B. 70):")
    else:
        await cq.message.edit_text("Gib den Schwellenwert für den Indikator ein:")
    await state.set_state(BotStates.indicator_alert_value)
    try:
        await cq.answer()
    except Exception:
        pass

@router.message(StateFilter(BotStates.indicator_alert_value))
async def indicator_alert_value_entered(message: types.Message, state: FSMContext):
    try:
        value = float(message.text.replace(",", "."))
    except ValueError:
        await message.reply("Bitte gib eine gültige Zahl ein.")
        return
    await state.update_data(value=value)
    await message.reply("Soll der Alert einmalig oder immer wieder ausgelöst werden?", reply_markup=repeat_keyboard())
    await state.set_state(BotStates.indicator_alert_repeat)

@router.callback_query(lambda c: c.data.startswith("repeat:"), StateFilter(BotStates.indicator_alert_repeat))
async def indicator_alert_repeat_chosen(cq: types.CallbackQuery, state: FSMContext):
    repeat = cq.data.split(":")[1]
    data = await state.get_data()
    user_id = str(cq.from_user.id)
    alarms = load_file(ALARM_FILE)
    if user_id not in alarms:
        alarms[user_id] = []
    alarms[user_id].append({
        "type": "indicator",
        "coin": data["coin"],
        "indicator": data["indicator"],
        "value": data["value"],
        "repeat": (repeat == "always"),
        "triggered": False
    })
    await save_file_async(ALARM_FILE, alarms)
    await cq.message.edit_text(f"Indikator-Alert für {data['coin']} gesetzt: {data['indicator']} {data['value']}, {'immer' if repeat=='always' else 'einmalig'}.", reply_markup=dashboard_keyboard())
    await state.clear()
    try:
        await cq.answer()
    except Exception:
        pass
