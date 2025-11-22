"""Callback handlers for interactive bot flows.

This module implements callback-query handlers, FSM-driven flows, and
utility helpers used to build interactive experiences in the bot. It
focuses on rendering inline keyboard UIs, responding to dashboard
navigation, generating charts, and orchestrating multi-step
interactions such as adding portfolio entries, setting alarms, and
managing watchlists.

Design notes:
- Handlers are intentionally thin: business logic and persistence are
    delegated to helpers in `utils` and `utils_cache`.
- User-visible strings remain unchanged; this file adds English
    docstrings and replaces German code comments with English
    equivalents for maintainability.
"""

import json
import io
import aiogram.exceptions
from aiogram import Router, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from config.config import BOT_TOKEN, COIN_LIST, ALARM_FILE, PORTFOLIO_FILE, WATCHLIST_FILE, SAVINGS_FILE, BUDGET_FILE, TRANSACTIONS_FILE, USER_SETTINGS_FILE, ACHIEVEMENTS_FILE, FIAT_TRANSACTIONS_FILE
from utils import get_price, get_24h_change, get_volatility, get_historical_prices, calculate_rsi, load_file, save_file_async
from utils_cache import (
    get_price_cached_from_file, get_24h_change_cached_from_file, calculate_rsi_cached_from_file,
    get_price_cached_from_file_async, get_24h_change_cached_from_file_async, calculate_rsi_cached_from_file_async
)
from keyboards import coin_keyboard, dashboard_keyboard, chart_select_keyboard, watchlist_alarm_keyboard, slider_keyboard, settings_keyboard, percent_period_keyboard, indicator_type_keyboard, repeat_keyboard
from states import BotStates
from datetime import datetime
from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
from handlers.commands import LANGUAGES, t
from aiogram.types.input_file import BufferedInputFile

# Helper function to safely edit a message's text
async def safe_edit_text(message, text, **kwargs):
    """Safely edit a message's text, falling back to sending a new message.

    Telegram API calls to `edit_text` can fail if the original message
    is no longer editable (e.g. too old or already replaced). This
    helper attempts to edit the message and falls back to `answer`
    (sending a new message) when editing fails with a
    `TelegramBadRequest`.

    Args:
        message: The message object to edit.
        text: The new text to set on the message.
        **kwargs: Additional keyword arguments forwarded to the
            underlying aiogram methods (e.g. `parse_mode`, `reply_markup`).
    """
    try:
        await message.edit_text(text, **kwargs)
    except aiogram.exceptions.TelegramBadRequest:
        await message.answer(text, **kwargs)

# Add chart timeframes
CHART_TIMEFRAMES = [
    ("24h", "1h", 24),
    ("7d", "4h", 42),
    ("1m", "1d", 30)
]

def chart_timeframe_keyboard(selected="24h"):
    from keyboards import InlineKeyboardButton, InlineKeyboardMarkup
    row = [InlineKeyboardButton(text=("✅ " if tf[0]==selected else "")+tf[0], callback_data=f"charttf:{tf[0]}") for tf in CHART_TIMEFRAMES]
    return InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]])

router = Router()

async def handle_dashboard(cq: types.CallbackQuery, state: FSMContext):
    action = cq.data
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")

    if action == "dash_portfolio":
        portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
        if not portfolio or (len(portfolio) == 1 and "fiat" in portfolio):
            await safe_edit_text(
                cq.message,
                "💼 *Portfolio leer.*\nFüge Coins oder Fiat hinzu:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Kaufen", callback_data="portfolio_buy"),
                     InlineKeyboardButton(text="💵 Einzahlen", callback_data="fiat_deposit")],
                    [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
        else:
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
            await safe_edit_text(cq.message, response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Kaufen", callback_data="portfolio_buy"),
                 InlineKeyboardButton(text="➖ Verkaufen", callback_data="portfolio_sell")],
                [InlineKeyboardButton(text="📜 Historie", callback_data="portfolio_history"),
                 InlineKeyboardButton(text="💵 Einzahlen", callback_data="fiat_deposit")],
                [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ]), parse_mode="Markdown")
    elif action == "dash_watchlist":
        watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
        response = "👀 *Deine Watchlist*\n\n"
        if not watchlist:
            response += "Leer. Füge Coins hinzu!"
        else:
            for coin in watchlist:
                price = get_price_cached_from_file(coin, currency)
                change = get_24h_change_cached_from_file(coin)
                rsi = calculate_rsi_cached_from_file(coin)
                if price is not None and change is not None:
                    response += f"- *{coin}*: **{price:.2f} {currency}** ({'+' if change > 0 else ''}{change:.2f}%"
                    if rsi is not None:
                        response += f", RSI: {rsi:.1f}"
                    response += ")\n"
                elif price is not None:
                    response += f"- *{coin}*: **{price:.2f} {currency}** (Daten unvollständig)\n"
                else:
                    response += f"- *{coin}*: Daten nicht verfügbar\n"
        await safe_edit_text(cq.message, response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Hinzufügen", callback_data="watchlist_add"),
             InlineKeyboardButton(text="➖ Entfernen", callback_data="watchlist_remove")],
            [InlineKeyboardButton(text="🔔 Watchlist-Alarme", callback_data="watchlist_alarms"),
             InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
        ]), parse_mode="Markdown")
    elif action == "dash_alarms":
        alarms = load_file(ALARM_FILE).get(user_id, [])
        if not alarms:
            await safe_edit_text(
                cq.message,
                "ℹ️ Keine aktiven Alarme.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔔 Alarm setzen", callback_data="set_alarm"),
                     InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
        else:
            response = "🔔 *Deine Alarme*\n\n"
            for i, alarm in enumerate(alarms):
                direction = "📉 unter" if alarm["direction"] == "below" else "📈 über" if alarm["direction"] == "above" else "📊 ±"
                target = alarm["target"]
                if alarm["type"] == "watchlist" and alarm["alarm_type"] == "volatility":
                    target = f"{target:.1f}%"
                elif alarm["type"] == "watchlist" and alarm["alarm_type"].startswith("rsi_"):
                    target = f"{target:.0f}"
                else:
                    target = f"{target:.0f} {currency}"
                response += f"- {alarm['coin']} {direction} {target} (Ausgelöst: {alarm['trigger_count']})\n"
            await safe_edit_text(cq.message, response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗑️ Alle löschen", callback_data="delete_all"),
                 InlineKeyboardButton(text="🔔 Neuen Alarm", callback_data="set_alarm")],
                [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ]), parse_mode="Markdown")
    elif action == "dash_savings":
        savings = load_file(SAVINGS_FILE).get(user_id, {})
        if not savings:
            await safe_edit_text(
                cq.message,
                "🎯 *Keine Sparziele.*\nFüge ein Ziel hinzu:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Sparziel", callback_data="savings_add"),
                     InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
        else:
            response = "🎯 *Deine Sparziele*\n\n"
            portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
            for coin, data in savings.items():
                current = portfolio.get(coin, {"amount": 0})["amount"]
                progress = (current / data["target"]) * 100
                response += f"- *{coin}*: {current:.4f}/{data['target']:.4f} ({progress:.1f}%)\n"
            await safe_edit_text(cq.message, response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Sparziel", callback_data="savings_add"),
                 InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ]), parse_mode="Markdown")
    elif action == "dash_budget":
        budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
        await safe_edit_text(
            cq.message,
            f"💸 *Budget*\n\nMonatliches Budget: {budget['amount']:.2f} {currency}\nAusgegeben: {budget['spent']:.2f} {currency}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Budget setzen", callback_data="budget_set"),
                 InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ]), parse_mode="Markdown")
    elif action == "dash_chart":
        await safe_edit_text(
            cq.message,
            "📊 *Chart auswählen*",
            parse_mode="Markdown",
            reply_markup=chart_select_keyboard()
        )
        await state.set_state(BotStates.chart_select)
    elif action == "dash_achievements":
        achievements = load_file(ACHIEVEMENTS_FILE).get(user_id, {})
        response = "🏆 *Deine Erfolge*\n\n"
        if not achievements:
            response += "Keine Erfolge bisher. Führe Aktionen aus, um welche freizuschalten!"
        else:
            for key, data in achievements.items():
                response += f"- *{data['name']}* ({data['date'][:10]}): {data['description']}\n"
        await safe_edit_text(cq.message, response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Statistik", callback_data="dash_stats"),
             InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
        ]), parse_mode="Markdown")
    elif action == "dash_fiatbudget":
        portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
        fiat = portfolio.get("fiat", {})
        budget = load_file(BUDGET_FILE).get(user_id, {"amount": 0, "spent": 0})
        response = "💸💵 *Fiat & Budget Übersicht*\n\n"
        if not fiat:
            response += "Keine Fiat-Bestände. Zahle etwas ein!\n"
        else:
            for curr, amount in fiat.items():
                response += f"- *{curr}*: {amount:.2f}\n"
        response += f"\n💸 *Budget*: {budget['amount']:.2f} {currency} (Ausgegeben: {budget['spent']:.2f})\n"
        response += "\n💡 Tipp: Du kannst dein Budget direkt auf Basis deiner Fiat-Bestände setzen."
        await safe_edit_text(
            cq.message,
            response,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Budget setzen", callback_data="budget_set"),
                 InlineKeyboardButton(text="➕ Einzahlen", callback_data="fiat_deposit"),
                 InlineKeyboardButton(text="➖ Auszahlen", callback_data="fiat_withdraw")],
                [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ]),
            parse_mode="Markdown"
        )
    elif action == "dash_settings":
        show_watchlist_rsi = settings.get("show_watchlist_rsi", True)
        await safe_edit_text(
            cq.message,
            "⚙️ *Einstellungen*\nHier kannst du Widgets und Sprache anpassen:",
            parse_mode="Markdown",
            reply_markup=settings_keyboard(
                dark_mode=settings.get("dark_mode", False),
                show_watchlist_rsi=show_watchlist_rsi
            )
        )
    elif action == "dash_currency":
        # Show currency selection separately
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=("✅ " if currency=="USD" else "")+"USD", callback_data="currency:USD"),
                InlineKeyboardButton(text=("✅ " if currency=="EUR" else "")+"EUR", callback_data="currency:EUR")
            ],
            [InlineKeyboardButton(text="🔙 Einstellungen", callback_data="dash_settings")]
        ])
        await safe_edit_text(
            cq.message,
            "🔄 *Währung wählen*",
            parse_mode="Markdown",
            reply_markup=kb
        )
    elif action.startswith("currency:"):
        # Currency change logic
        new_currency = action.split(":", 1)[1]
        user_settings = load_file(USER_SETTINGS_FILE)
        if user_id not in user_settings:
            user_settings[user_id] = {}
        user_settings[user_id]["currency"] = new_currency
        await save_file_async(USER_SETTINGS_FILE, user_settings)
        # Nach Wechsel zurück zur Währungsauswahl
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=("✅ " if new_currency=="USD" else "")+"USD", callback_data="currency:USD"),
                InlineKeyboardButton(text=("✅ " if new_currency=="EUR" else "")+"EUR", callback_data="currency:EUR")
            ],
            [InlineKeyboardButton(text="🔙 Einstellungen", callback_data="dash_settings")]
        ])
        await safe_edit_text(
            cq.message,
            f"🔄 Währung geändert zu {new_currency}.",
            reply_markup=kb
        )
    elif action == "set_alarm":
        from .commands import cmd_setalarm
        await cmd_setalarm(cq.message, state)
    elif action == "watchlist_alarms":
        await safe_edit_text(
            cq.message,
            "🔔 *Watchlist-Alarm auswählen*",
            parse_mode="Markdown",
            reply_markup=watchlist_alarm_keyboard()
        )
        await state.set_state(BotStates.watchlist_alarm_type)
    elif action == "dash_widgets":
        await cq.message.answer(t(user_id, "widgets_config") + "\nSende eine kommagetrennte Liste deiner Lieblingscoins (z.B. BTC,ETH,ADA):")
        await state.set_state(BotStates.manual_coin_input)
    elif action == "dash_language":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Deutsch", callback_data="lang:de"),
             InlineKeyboardButton(text="English", callback_data="lang:en")]
        ])
        await cq.message.answer(t(user_id, "choose_language"), reply_markup=kb)
    await cq.answer()
router.callback_query.register(handle_dashboard, lambda c: c.data.startswith("dash_") and c.data != "dash_back" or c.data.startswith("currency:") or c.data == "set_alarm" or c.data == "watchlist_alarms")

async def handle_chart_select(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    chart_type = cq.data.split(":")[1] if ":" in cq.data else cq.data
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    await state.update_data(chart_timeframe="24h")
    if chart_type == "portfolio":
        labels, values = [], []
        for coin, data in portfolio.items():
            if coin != "fiat":
                labels.append(coin)
                price = get_price_cached_from_file(coin, currency)
                if price:
                    values.append(price * data["amount"])
        if labels and values:
            total = sum(values)
            text = "\n".join([f"{l}: {v:.2f} {currency} ({v/total*100:.1f}%)" for l, v in zip(labels, values)])
            await safe_edit_text(
                cq.message,
                f"📊 *Portfolio-Verteilung*\n\n{text}",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
            # Pie-Chart visualisieren
            import matplotlib.pyplot as plt
            import numpy as np
            plt.figure(figsize=(6, 6))
            dark_mode = settings.get("dark_mode", False)
            if dark_mode:
                plt.style.use("dark_background")
                colors = ["#4ECDC4", "#FF6B6B", "#FFD93D", "#1A535C", "#F7FFF7", "#5F4B8B", "#B4656F", "#2E2E2E"]
                # Fallback falls mehr Coins als Farben
                while len(colors) < len(labels):
                    colors += colors
            else:
                plt.style.use("default")
                colors = plt.cm.Paired.colors
            patches, texts, autotexts = plt.pie(values, labels=labels, autopct="%1.1f%%", colors=colors[:len(labels)])
            for text in texts + autotexts:
                text.set_color("white" if dark_mode else "black")
            plt.title("Portfolio-Verteilung", color=("white" if dark_mode else "black"))
            plt.gcf().patch.set_facecolor("#222" if dark_mode else "white")
            plt.tight_layout()
            import io
            buf = io.BytesIO()
            plt.savefig(buf, format="png", bbox_inches="tight", facecolor=plt.gcf().get_facecolor())
            plt.close()
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="portfolio_pie.png")
            await cq.message.answer_photo(
                photo,
                caption="📊 *Portfolio-Verteilung als Chart*",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
        else:
            await safe_edit_text(cq.message, "Kein Portfolio vorhanden.", reply_markup=chart_select_keyboard())
    elif chart_type == "price":
        await safe_edit_text(
            cq.message,
            "Wähle einen Coin für den Preisverlauf:",
            reply_markup=coin_keyboard()
        )
        await state.update_data(chart_type="price")
        await state.update_data(chart_timeframe="24h")
    elif chart_type == "value":
        if not transactions:
            await safe_edit_text(cq.message, "Keine Transaktionen vorhanden.", reply_markup=chart_select_keyboard())
        else:
            import matplotlib.pyplot as plt
            import numpy as np
            import io
            dark_mode = settings.get("dark_mode", False)
            # Zeitleiste und Wert berechnen
            txs = sorted(transactions, key=lambda t: t["date"])
            times = []
            values = []
            portfolio = {}
            for t in txs:
                date = t["date"][:10]
                coin = t["coin"] if "coin" in t else None
                amount = t.get("amount", 0)
                price = t.get("price", 0)
                if t["type"] == "buy":
                    portfolio[coin] = portfolio.get(coin, 0) + amount
                elif t["type"] == "sell":
                    portfolio[coin] = portfolio.get(coin, 0) - amount
                # Wert berechnen
                total = 0
                for c, a in portfolio.items():
                    p = get_price(c, "USD")  # Immer USD holen
                    if p:
                        if currency == "EUR":
                            total += a * p * 0.9  # Umrechnung USD -> EUR
                        else:
                            total += a * p
                times.append(date)
                values.append(total)
            plt.close('all')
            fig, ax = plt.subplots(figsize=(8, 4))
            if dark_mode:
                fig.patch.set_facecolor("#222")
                ax.set_facecolor("#222")
                plt.style.use("dark_background")
                linecolor = "#FFD93D"
                labelcolor = "white"
            else:
                fig.patch.set_facecolor("white")
                ax.set_facecolor("white")
                plt.style.use("default")
                linecolor = "#1A535C"
                labelcolor = "black"
            ax.plot(times, values, marker="o", color=linecolor)
            ax.set_title("Portfolio-Wert-Verlauf", color=labelcolor)
            ax.set_xlabel("Datum", color=labelcolor)
            ax.set_ylabel(f"Wert ({currency})", color=labelcolor)
            ax.tick_params(axis='x', colors=labelcolor, rotation=45)
            ax.tick_params(axis='y', colors=labelcolor)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="portfolio_value.png")
            await cq.message.answer_photo(
                photo,
                caption="📈 *Portfolio-Wert-Verlauf*\nJede Markierung: Wert nach Transaktion",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
    elif chart_type == "dca":
        # DCA/Backtest-Chart
        await safe_edit_text(
            cq.message,
            "📅 DCA/Backtest: Wähle einen Coin für die Simulation:",
            parse_mode="Markdown",
            reply_markup=coin_keyboard()
        )
        await state.update_data(dca_flow=True)
        await state.set_state(BotStates.choosing_coin)
    elif chart_type == "heatmap":
        import matplotlib.pyplot as plt
        import numpy as np
        coins = [c for c in portfolio if c != "fiat"]
        values = [get_price(c, currency) * portfolio[c]["amount"] if get_price(c, currency) else 0 for c in coins]
        perf = [(get_price(c, currency) - portfolio[c]["buy_price"]) / portfolio[c]["buy_price"] * 100 if portfolio[c]["buy_price"] else 0 for c in coins]
        if not coins or not any(values):
            await safe_edit_text(cq.message, "Keine Daten für Heatmap vorhanden.", reply_markup=chart_select_keyboard())
            return
        fig, ax = plt.subplots(figsize=(max(4, len(coins)), 4))
        # Darkmode Support
        if settings.get("dark_mode", False):
            fig.patch.set_facecolor("#222")
            ax.set_facecolor("#222")
            ax.tick_params(colors="white")
            ax.yaxis.label.set_color("white")
            ax.xaxis.label.set_color("white")
            ax.title.set_color("white")
        norm = plt.Normalize(min(perf), max(perf))
        colors = plt.cm.RdYlGn(norm(perf))
        bars = ax.bar(coins, values, color=colors)
        for bar, p in zip(bars, perf):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{p:+.1f}%", ha='center', va='bottom', fontsize=10, color=("white" if settings.get("dark_mode", False) else "black"))
        ax.set_ylabel(f"Wert ({currency})")
        ax.set_title("Portfolio-Heatmap (Grün=Gewinn, Rot=Verlust)")
        plt.tight_layout()
        import io
        buf = io.BytesIO()
        plt.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close()
        buf.seek(0)
        photo = BufferedInputFile(buf.read(), filename="heatmap.png")
        await cq.message.answer_photo(
            photo,
            caption="🔥 *Portfolio-Heatmap*\nJede Spalte: Coin-Wert, Farbe: Performance",
            parse_mode="Markdown",
            reply_markup=chart_select_keyboard()
        )
    await cq.answer()

router.callback_query.register(handle_chart_select, lambda c: c.data.startswith("chart:"), StateFilter(BotStates.chart_select))

# Add handler for timeframe selection
@router.callback_query(lambda c: c.data.startswith("charttf:"), StateFilter(BotStates.chart_select))
async def chart_timeframe_selected(cq: types.CallbackQuery, state: FSMContext):
    """Set the selected chart timeframe and regenerate the chart when applicable.

    This handler updates the FSM with the selected timeframe and,
    when a chart coin is already selected, regenerates the corresponding
    chart image for the new timeframe.
    """
    tf = cq.data.split(":")[1]
    await state.update_data(chart_timeframe=tf)
    data = await state.get_data()
    chart_type = data.get("chart_type")
    coin = data.get("coin")
    if chart_type == "price" and coin:
        # Trigger chart generation for new timeframe
        # (reuse logic from coin_chosen_for_chart)
        user_id = str(cq.from_user.id)
        settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
        currency = settings.get("currency", "USD")
        tf_map = {tf[0]: (tf[1], tf[2]) for tf in CHART_TIMEFRAMES}
        interval, limit = tf_map.get(tf, ("1h", 24))
        prices = get_historical_prices(coin, interval, limit)
        if not prices:
            await cq.message.answer(
                "❌ *Fehler*: Keine Daten verfügbar.",
                parse_mode="Markdown",
                reply_markup=chart_timeframe_keyboard(tf)
            )
        else:
            import matplotlib.pyplot as plt
            # Dark Mode Support
            dark_mode = settings.get("dark_mode", False)
            if dark_mode:
                plt.style.use("dark_background")
            else:
                plt.style.use("default")
            times = [p["time"][5:16] for p in prices]
            values = [p["price"] * (0.9 if currency == "EUR" else 1) for p in prices]
            plt.figure(figsize=(8, 4))
            plt.plot(times, values, color="#4ECDC4", marker="o")
            plt.title(f"{coin} Preisverlauf ({tf})")
            plt.xlabel("Zeit")
            plt.ylabel(f"Preis ({currency})")
            plt.xticks(rotation=45)
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close()
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="chart.png")
            await cq.message.answer_photo(
                photo,
                caption=f"📈 *{coin} Preisverlauf* ({tf})",
                parse_mode="Markdown",
                reply_markup=chart_timeframe_keyboard(tf)
            )
    else:
        await cq.answer(f"Zeitraum gesetzt: {tf}")

async def coin_chosen_for_chart(cq: types.CallbackQuery, state: FSMContext):
    """Generate and send the requested chart for the chosen coin.

    Reads FSM variables (`chart_type`, `chart_timeframe`) to determine
    which chart to generate. Produces a Matplotlib image and sends it
    as a photo. Clears the FSM on completion.
    """
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)  # Save coin for timeframe switching
    data = await state.get_data()
    chart_type = data.get("chart_type")
    chart_timeframe = data.get("chart_timeframe", "24h")
    # Map timeframe to interval/limit
    tf_map = {tf[0]: (tf[1], tf[2]) for tf in CHART_TIMEFRAMES}
    interval, limit = tf_map.get(chart_timeframe, ("1h", 24))
    if chart_type == "price":
        prices = get_historical_prices(coin, interval, limit)
        if not prices:
            await cq.message.answer(
                "❌ *Fehler*: Keine Daten verfügbar.",
                parse_mode="Markdown",
                reply_markup=chart_timeframe_keyboard(chart_timeframe)
            )
        else:
            import matplotlib.pyplot as plt
            # Dark Mode Support
            dark_mode = settings.get("dark_mode", False)
            if dark_mode:
                plt.style.use("dark_background")
            else:
                plt.style.use("default")
            times = [p["time"][5:16] for p in prices]
            values = [p["price"] * (0.9 if currency == "EUR" else 1) for p in prices]
            plt.figure(figsize=(8, 4))
            plt.plot(times, values, color="#4ECDC4", marker="o")
            plt.title(f"{coin} Preisverlauf ({chart_timeframe})")
            plt.xlabel("Zeit")
            plt.ylabel(f"Preis ({currency})")
            plt.xticks(rotation=45)
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close()
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="chart.png")
            await cq.message.answer_photo(
                photo,
                caption=f"📈 *{coin} Preisverlauf* ({chart_timeframe})",
                parse_mode="Markdown",
                reply_markup=chart_timeframe_keyboard(chart_timeframe)
            )
    await state.clear()
    await cq.answer()

router.callback_query.register(coin_chosen_for_chart, lambda c: c.data.startswith("coin:"), StateFilter(BotStates.chart_select))

async def coin_page(cq: types.CallbackQuery, state: FSMContext):
    page = int(cq.data.split(":")[1])
    for_price = state.get_state() == BotStates.choosing_coin
    await cq.message.edit_reply_markup(reply_markup=coin_keyboard(page, for_price))
    await cq.answer()
router.callback_query.register(coin_page, lambda c: c.data.startswith("page:"))

async def fiat_deposit(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    await cq.message.edit_text(
        f"Gib den Betrag in {currency} für die Einzahlung ein (z.B. 1000):",
        parse_mode="Markdown"
    )
    await state.set_state(BotStates.fiat_deposit)
    await cq.answer()
router.callback_query.register(fiat_deposit, lambda c: c.data == "fiat_deposit")

async def fiat_withdraw(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    await cq.message.edit_text(
        f"Gib den Betrag in {currency} für die Auszahlung ein (z.B. 500):",
        parse_mode="Markdown"
    )
    await state.set_state(BotStates.fiat_withdraw)
    await cq.answer()
router.callback_query.register(fiat_withdraw, lambda c: c.data == "fiat_withdraw")

async def watchlist_action(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    action = cq.data
    if action == "watchlist_add":
        await cq.message.edit_text("Wähle einen Coin für die Watchlist:", reply_markup=coin_keyboard())
        await state.set_state(BotStates.choosing_coin)
        await state.update_data(watchlist_action="add")
    elif action == "watchlist_remove":
        watchlist = load_file(WATCHLIST_FILE).get(user_id, [])
        if not watchlist:
            await cq.message.edit_text(
                "👀 *Watchlist leer.*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Hinzufügen", callback_data="watchlist_add"),
                     InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[])
            for coin in watchlist:
                kb.inline_keyboard.append([InlineKeyboardButton(text=coin, callback_data=f"remove:{coin}")])
            kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")])
            await cq.message.edit_text("Wähle einen Coin zum Entfernen:", reply_markup=kb)
    await cq.answer()
router.callback_query.register(watchlist_action, lambda c: c.data in ["watchlist_add", "watchlist_remove"])

async def delete_alarm(cq: types.CallbackQuery):
    user_id = str(cq.from_user.id)
    alarms = load_file(ALARM_FILE).get(user_id, [])
    if cq.data == "delete_all":
        alarms.clear()
    else:
        index = int(cq.data.split(":")[1])
        if 0 <= index < len(alarms):
            alarms.pop(index)
    await save_file_async(ALARM_FILE, {user_id: alarms})
    await cq.message.edit_text(
        "✅ *Alarme aktualisiert*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Meine Alarme", callback_data="dash_alarms"),
             InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
        ])
    )
    await cq.answer()
router.callback_query.register(delete_alarm, lambda c: c.data and (c.data.startswith("delete:") or c.data == "delete_all"))

async def handle_trending_action(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    if cq.data.startswith("trend_"):
        parts = cq.data.split(":", 1)
        action = parts[0].split("_", 1)[1]
        coin = parts[1]
        if action == "price":
            price = get_price(coin, currency)
            if price is None:
                await cq.message.edit_text(
                    "❌ *Fehler*: Ungültiger Coin oder API-Probleme.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                    ])
                )
            else:
                await cq.message.edit_text(
                    f"💰 *{coin}*: **{price:.2f} {currency}**",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔔 Alarm setzen", callback_data=f"trend_alarm:{coin}"),
                         InlineKeyboardButton(text="⚡ Volatilität", callback_data=f"trend_vol:{coin}")],
                        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                    ])
                )
        elif action == "alarm":
            await state.update_data(coin=coin, target=get_price(coin, currency) or 0, type="price")
            await cq.message.edit_text(
                f"🚀 *{coin}* aktuell bei **{(get_price(coin, currency) or 0):.2f} {currency}**\nWähle die Alarmrichtung:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📉 Falls unter", callback_data="direction:below"),
                     InlineKeyboardButton(text="📈 Falls über", callback_data="direction:above")],
                    [InlineKeyboardButton(text="📊 % Änderung", callback_data="direction:percent"),
                     InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ])
            )
            await state.set_state(BotStates.choosing_direction)
        elif action == "vol":
            volatility_data = get_volatility(coin)
            if not volatility_data:
                await cq.message.edit_text(
                    "❌ *Fehler*: Ungültiger Coin oder API-Probleme.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                    ])
                )
            else:
                response = (
                    f"⚡ *{coin} Volatilität (24h)*:\n\n"
                    f"- Höchster Preis: **{volatility_data['high']:.2f} {currency}**\n"
                    f"- Tiefster Preis: **{volatility_data['low']:.2f} {currency}**\n"
                    f"- Schwankung: ±**{volatility_data['volatility']:.2f}%**"
                )
                await cq.message.edit_text(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💰 Preis", callback_data=f"trend_price:{coin}"),
                     InlineKeyboardButton(text="🔔 Alarm", callback_data=f"trend_alarm:{coin}")],
                    [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
                ]), parse_mode="Markdown")
    await cq.answer()
router.callback_query.register(handle_trending_action, lambda c: c.data.startswith("trend_"))

# --- Portfolio UX: Simple add flow ---
from aiogram.fsm.state import StatesGroup, State

class PortfolioAddStates(StatesGroup):
    """Finite-state machine states for the portfolio add flow.

    States:
    - `choosing_coin`: user selects a coin or types one manually.
    - `entering_amount`: user enters the quantity to add.
    - `entering_price`: optional custom buy price entry.
    - `entering_date`: optional purchase date entry.
    """
    choosing_coin = State()
    entering_amount = State()
    entering_price = State()
    entering_date = State()  # state for date entry

@router.callback_query(lambda c: c.data == "portfolio_buy")
async def portfolio_buy(cq: types.CallbackQuery, state: FSMContext):
    await cq.message.edit_text(
        "Welchen Coin möchtest du hinzufügen? Wähle aus der Liste oder tippe den Namen ein (z.B. BTC):",
        reply_markup=coin_keyboard()
    )
    await state.set_state(PortfolioAddStates.choosing_coin)
    await cq.answer()

@router.callback_query(lambda c: c.data.startswith("coin:"), StateFilter(PortfolioAddStates.choosing_coin))
async def portfolio_coin_chosen(cq: types.CallbackQuery, state: FSMContext):
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)
    await cq.message.edit_text(f"Wie viel *{coin}* möchtest du hinzufügen? (z.B. 0.5)", parse_mode="Markdown")
    await state.set_state(PortfolioAddStates.entering_amount)
    await cq.answer()

@router.message(StateFilter(PortfolioAddStates.choosing_coin))
async def portfolio_coin_typed(message: types.Message, state: FSMContext):
    coin = message.text.strip().upper()
    await state.update_data(coin=coin)
    await message.answer(f"Wie viel *{coin}* möchtest du hinzufügen? (z.B. 0.5)", parse_mode="Markdown")
    await state.set_state(PortfolioAddStates.entering_amount)

@router.message(StateFilter(PortfolioAddStates.entering_amount))
async def portfolio_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except Exception:
        await message.reply("❌ Ungültige Menge. Bitte gib eine positive Zahl ein.")
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    coin = data["coin"]
    # Aktuellen Preis holen
    settings = load_file(USER_SETTINGS_FILE).get(str(message.from_user.id), {})
    currency = settings.get("currency", "USD")
    price = get_price_cached_from_file(coin, currency)
    if price:
        await message.answer(f"Möchtest du einen eigenen Kaufpreis angeben? (Standard: {price:.2f} {currency})\nAntworte mit Preis oder tippe 'ok' für Standardpreis.")
        await state.set_state(PortfolioAddStates.entering_price)
    else:
        await message.answer("Konnte aktuellen Preis nicht abrufen. Bitte gib den Kaufpreis manuell ein:")
        await state.set_state(PortfolioAddStates.entering_price)

@router.message(StateFilter(PortfolioAddStates.entering_price))
async def portfolio_price_entered(message: types.Message, state: FSMContext):
    data = await state.get_data()
    coin = data["coin"]
    amount = data["amount"]
    settings = load_file(USER_SETTINGS_FILE).get(str(message.from_user.id), {})
    currency = settings.get("currency", "USD")
    price = get_price_cached_from_file(coin, currency) or 0
    text = message.text.strip().lower()
    if text == "ok":
        buy_price = price
    else:
        try:
            buy_price = float(text.replace(",", "."))
        except Exception:
            await message.reply("❌ Ungültiger Preis. Bitte gib eine Zahl ein oder 'ok' für Standardpreis.")
            return
    await state.update_data(buy_price=buy_price)
    # Nach Preis jetzt Datum abfragen
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    await message.answer(f"Gib das Kaufdatum ein (Format: JJJJ-MM-TT, z.B. {today}) oder tippe 'heute':")
    await state.set_state(PortfolioAddStates.entering_date)

@router.message(StateFilter(PortfolioAddStates.entering_date))
async def portfolio_date_entered(message: types.Message, state: FSMContext):
    from datetime import datetime
    data = await state.get_data()
    coin = data["coin"]
    amount = data["amount"]
    buy_price = data["buy_price"]
    user_id = str(message.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    text = message.text.strip().lower()
    if text == "heute":
        date = datetime.utcnow().isoformat()
    else:
        try:
            # Akzeptiere nur Datumsteil, setze Zeit auf 12:00
            date_obj = datetime.strptime(text, "%Y-%m-%d")
            date = date_obj.replace(hour=12, minute=0, second=0).isoformat()
        except Exception:
            await message.reply("❌ Ungültiges Datum. Bitte nutze das Format JJJJ-MM-TT oder 'heute'.")
            return
    # Portfolio speichern
    portfolio = load_file(PORTFOLIO_FILE)
    if user_id not in portfolio:
        portfolio[user_id] = {}
    if coin not in portfolio[user_id]:
        portfolio[user_id][coin] = {"amount": 0, "buy_price": buy_price}
    old_amount = portfolio[user_id][coin]["amount"]
    old_price = portfolio[user_id][coin]["buy_price"]
    new_total = old_amount + amount
    if new_total > 0:
        avg_price = ((old_amount * old_price) + (amount * buy_price)) / new_total
    else:
        avg_price = buy_price
    portfolio[user_id][coin]["amount"] = new_total
    portfolio[user_id][coin]["buy_price"] = avg_price
    await save_file_async(PORTFOLIO_FILE, portfolio)

    # --- TRANSACTION HISTORY UPDATE ---
    transactions = load_file(TRANSACTIONS_FILE)
    if user_id not in transactions:
        transactions[user_id] = []
    transactions[user_id].append({
        "type": "buy",
        "coin": coin,
        "amount": amount,
        "price": buy_price,
        "currency": currency,
        "date": date
    })
    await save_file_async(TRANSACTIONS_FILE, transactions)

    await message.answer(f"✅ *{amount} {coin}* zum Portfolio hinzugefügt!\nKaufpreis: {avg_price:.2f} {currency}", parse_mode="Markdown", reply_markup=dashboard_keyboard())
    await state.clear()

async def portfolio_history(cq: types.CallbackQuery):
    user_id = str(cq.from_user.id)
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    fiat_transactions = load_file(FIAT_TRANSACTIONS_FILE).get(user_id, [])
    if not transactions and not fiat_transactions:
        await cq.message.edit_text(
            "📜 *Keine Transaktionen.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
                 InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
            ])
        )
        await cq.answer()
        return
    response = "📜 *Transaktionshistorie*\n\n"
    all_transactions = transactions + fiat_transactions
    all_transactions.sort(key=lambda x: x["date"], reverse=True)
    for t in all_transactions[:10]:  # Letzte 10 Transaktionen
        if "coin" in t:
            response += f"- {t['date'][:10]}: {'Kauf' if t['type'] == 'buy' else 'Verkauf'} {t['amount']:.4f} {t['coin']} @ {t['price']:.2f} {t['currency']}\n"
        else:
            response += f"- {t['date'][:10]}: {'Einzahlung' if t['type'] == 'deposit' else 'Auszahlung'} {t['amount']:.2f} {t['currency']}\n"
    await cq.message.edit_text(response, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
         InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ]), parse_mode="Markdown")
    await cq.answer()
router.callback_query.register(portfolio_history, lambda c: c.data == "portfolio_history")

# --- Universal handler for "🔙 Dashboard" (dash_back) ---
@router.callback_query(lambda c: c.data == "dash_back")
async def universal_dash_back(cq: types.CallbackQuery, state: FSMContext):
    """Return the user to the main dashboard view.

    This universal handler is bound to the 'dash_back' callback and
    attempts to edit the originating message to show the full
    dashboard. It gracefully handles messages that cannot be edited by
    sending a fresh message instead.
    """
    import logging
    logging.getLogger("CoinTrackerBot").info(f"universal_dash_back handler triggered by user {cq.from_user.id}")
    try:
        if getattr(cq.message, 'text', None):
            await cq.message.edit_text(
                "🏠 *Dashboard*\nWähle eine Funktion:",
                parse_mode="Markdown",
                reply_markup=dashboard_keyboard()
            )
        else:
            await cq.message.answer(
                "🏠 *Dashboard*\nWähle eine Funktion:",
                parse_mode="Markdown",
                reply_markup=dashboard_keyboard()
            )
    except aiogram.exceptions.TelegramBadRequest:
        await cq.message.answer(
            "🏠 *Dashboard*\nWähle eine Funktion:",
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
    except Exception as e:
        logging.getLogger("CoinTrackerBot").exception(f"Exception in universal_dash_back: {e}")
        await cq.message.answer(
            "🏠 *Dashboard*\nWähle eine Funktion:",
            parse_mode="Markdown",
            reply_markup=dashboard_keyboard()
        )
    await state.clear()
    await cq.answer()

# Dashboard-Handler: alle dash_ außer dash_back
router.callback_query.register(handle_dashboard, lambda c: c.data.startswith("dash_") and c.data != "dash_back" or c.data.startswith("currency:") or c.data == "set_alarm" or c.data == "watchlist_alarms")

@router.callback_query(lambda c: c.data.startswith("chart:"), StateFilter(BotStates.chart_select))
async def handle_chart_select(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    chart_type = cq.data.split(":")[1] if ":" in cq.data else cq.data
    portfolio = load_file(PORTFOLIO_FILE).get(user_id, {})
    transactions = load_file(TRANSACTIONS_FILE).get(user_id, [])
    await state.update_data(chart_timeframe="24h")
    if chart_type == "portfolio":
        labels, values = [], []
        for coin, data in portfolio.items():
            if coin != "fiat":
                labels.append(coin)
                price = get_price_cached_from_file(coin, currency)
                if price:
                    values.append(price * data["amount"])
        if labels and values:
            total = sum(values)
            text = "\n".join([f"{l}: {v:.2f} {currency} ({v/total*100:.1f}%)" for l, v in zip(labels, values)])
            await safe_edit_text(
                cq.message,
                f"📊 *Portfolio-Verteilung*\n\n{text}",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
            # Pie-Chart visualisieren
            import matplotlib.pyplot as plt
            import numpy as np
            plt.figure(figsize=(6, 6))
            dark_mode = settings.get("dark_mode", False)
            if dark_mode:
                plt.style.use("dark_background")
                colors = ["#4ECDC4", "#FF6B6B", "#FFD93D", "#1A535C", "#F7FFF7", "#5F4B8B", "#B4656F", "#2E2E2E"]
                # Fallback falls mehr Coins als Farben
                while len(colors) < len(labels):
                    colors += colors
            else:
                plt.style.use("default")
                colors = plt.cm.Paired.colors
            patches, texts, autotexts = plt.pie(values, labels=labels, autopct="%1.1f%%", colors=colors[:len(labels)])
            for text in texts + autotexts:
                text.set_color("white" if dark_mode else "black")
            plt.title("Portfolio-Verteilung", color=("white" if dark_mode else "black"))
            plt.gcf().patch.set_facecolor("#222" if dark_mode else "white")
            plt.tight_layout()
            import io
            buf = io.BytesIO()
            plt.savefig(buf, format="png", bbox_inches="tight", facecolor=plt.gcf().get_facecolor())
            plt.close()
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="portfolio_pie.png")
            await cq.message.answer_photo(
                photo,
                caption="📊 *Portfolio-Verteilung als Chart*",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
        else:
            await safe_edit_text(cq.message, "Kein Portfolio vorhanden.", reply_markup=chart_select_keyboard())
    elif chart_type == "price":
        await safe_edit_text(
            cq.message,
            "Wähle einen Coin für den Preisverlauf:",
            reply_markup=coin_keyboard()
        )
        await state.update_data(chart_type="price")
        await state.update_data(chart_timeframe="24h")
    elif chart_type == "value":
        if not transactions:
            await safe_edit_text(cq.message, "Keine Transaktionen vorhanden.", reply_markup=chart_select_keyboard())
        else:
            import matplotlib.pyplot as plt
            import numpy as np
            import io
            dark_mode = settings.get("dark_mode", False)
            # Zeitleiste und Wert berechnen
            txs = sorted(transactions, key=lambda t: t["date"])
            times = []
            values = []
            portfolio = {}
            for t in txs:
                date = t["date"][:10]
                coin = t["coin"] if "coin" in t else None
                amount = t.get("amount", 0)
                price = t.get("price", 0)
                if t["type"] == "buy":
                    portfolio[coin] = portfolio.get(coin, 0) + amount
                elif t["type"] == "sell":
                    portfolio[coin] = portfolio.get(coin, 0) - amount
                # Wert berechnen
                total = 0
                for c, a in portfolio.items():
                    p = get_price(c, "USD")  # Immer USD holen
                    if p:
                        if currency == "EUR":
                            total += a * p * 0.9  # Umrechnung USD -> EUR
                        else:
                            total += a * p
                times.append(date)
                values.append(total)
            plt.close('all')
            fig, ax = plt.subplots(figsize=(8, 4))
            if dark_mode:
                fig.patch.set_facecolor("#222")
                ax.set_facecolor("#222")
                plt.style.use("dark_background")
                linecolor = "#FFD93D"
                labelcolor = "white"
            else:
                fig.patch.set_facecolor("white")
                ax.set_facecolor("white")
                plt.style.use("default")
                linecolor = "#1A535C"
                labelcolor = "black"
            ax.plot(times, values, marker="o", color=linecolor)
            ax.set_title("Portfolio-Wert-Verlauf", color=labelcolor)
            ax.set_xlabel("Datum", color=labelcolor)
            ax.set_ylabel(f"Wert ({currency})", color=labelcolor)
            ax.tick_params(axis='x', colors=labelcolor, rotation=45)
            ax.tick_params(axis='y', colors=labelcolor)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            photo = BufferedInputFile(buf.read(), filename="portfolio_value.png")
            await cq.message.answer_photo(
                photo,
                caption="📈 *Portfolio-Wert-Verlauf*\nJede Markierung: Wert nach Transaktion",
                parse_mode="Markdown",
                reply_markup=chart_select_keyboard()
            )
    elif chart_type == "dca":
        # DCA/Backtest-Chart
        await safe_edit_text(
            cq.message,
            "📅 DCA/Backtest: Wähle einen Coin für die Simulation:",
            parse_mode="Markdown",
            reply_markup=coin_keyboard()
        )
        await state.update_data(dca_flow=True)
        await state.set_state(BotStates.choosing_coin)
    elif chart_type == "heatmap":
        import matplotlib.pyplot as plt
        import numpy as np
        coins = [c for c in portfolio if c != "fiat"]
        values = [get_price(c, currency) * portfolio[c]["amount"] if get_price(c, currency) else 0 for c in coins]
        perf = [(get_price(c, currency) - portfolio[c]["buy_price"]) / portfolio[c]["buy_price"] * 100 if portfolio[c]["buy_price"] else 0 for c in coins]
        if not coins or not any(values):
            await safe_edit_text(cq.message, "Keine Daten für Heatmap vorhanden.", reply_markup=chart_select_keyboard())
            return
        fig, ax = plt.subplots(figsize=(max(4, len(coins)), 4))
        # Darkmode Support
        if settings.get("dark_mode", False):
            fig.patch.set_facecolor("#222")
            ax.set_facecolor("#222")
            ax.tick_params(colors="white")
            ax.yaxis.label.set_color("white")
            ax.xaxis.label.set_color("white")
            ax.title.set_color("white")
        norm = plt.Normalize(min(perf), max(perf))
        colors = plt.cm.RdYlGn(norm(perf))
        bars = ax.bar(coins, values, color=colors)
        for bar, p in zip(bars, perf):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), f"{p:+.1f}%", ha='center', va='bottom', fontsize=10, color=("white" if settings.get("dark_mode", False) else "black"))
        ax.set_ylabel(f"Wert ({currency})")
        ax.set_title("Portfolio-Heatmap (Grün=Gewinn, Rot=Verlust)")
        plt.tight_layout()
        import io
        buf = io.BytesIO()
        plt.savefig(buf, format="png", facecolor=fig.get_facecolor())
        plt.close()
        buf.seek(0)
        photo = BufferedInputFile(buf.read(), filename="heatmap.png")
        await cq.message.answer_photo(
            photo,
            caption="🔥 *Portfolio-Heatmap*\nJede Spalte: Coin-Wert, Farbe: Performance",
            parse_mode="Markdown",
            reply_markup=chart_select_keyboard()
        )
    await cq.answer()

# --- Coin-Auswahl: Dispatcher für verschiedene Flows (Watchlist, Savings, Alarm, Preisabfrage) ---
@router.callback_query(lambda c: c.data.startswith("coin:"), StateFilter(BotStates.choosing_coin))
async def choosing_coin_router(cq: types.CallbackQuery, state: FSMContext):
    """Route a coin selection to the appropriate active flow.

    Depending on the FSM context, a coin selection can belong to the
    watchlist flow, savings flow, chart flow, alarm flow, or a simple
    price query. This router dispatches the callback to the correct
    handler and preserves the user experience for multi-step dialogs.
    """
    data = await state.get_data()
    if data.get("whatif_flow"):
        # Was-wäre-wenn: Nach Coin jetzt Datum abfragen
        coin = cq.data.split(":", 1)[1]
        await state.update_data(whatif_coin=coin)
        await cq.message.edit_text(
            f"🗓️ Gib das Kaufdatum ein (Format: JJJJ-MM-TT, z.B. 2022-01-01):",
            parse_mode="Markdown"
        )
        await state.set_state(BotStates.manual_target)
        return
    # Vorrang: Watchlist-Flow
    if data.get("watchlist_action") == "add":
        coin = cq.data.split(":", 1)[1]
        # Watchlist laden und Coin hinzufügen, falls noch nicht drin
        watchlist = load_file(WATCHLIST_FILE)
        user_id = str(cq.from_user.id)
        user_watchlist = watchlist.get(user_id, [])
        if coin not in user_watchlist:
            user_watchlist.append(coin)
            watchlist[user_id] = user_watchlist
            await save_file_async(WATCHLIST_FILE, watchlist)
            await cq.message.answer(f"✅ {coin} zur Watchlist hinzugefügt.")
        else:
            await cq.message.answer(f"{coin} ist bereits in deiner Watchlist.")
        # Nach Hinzufügen wieder Auswahl anzeigen
        await cq.message.answer("Wähle einen weiteren Coin für die Watchlist oder gehe zurück:", reply_markup=coin_keyboard())
        await state.set_state(BotStates.choosing_coin)
        await state.update_data(watchlist_action="add")
        await cq.answer()
        return
    if data.get("watchlist_action") == "remove":
        await watchlist_action(cq, state)
        return
    # Vorrang: Savings-Flow
    if data.get("savings_action") == "add":
        await savings_coin_chosen(cq, state)
        return
    # Vorrang: Chart-Alarm-Flow (Watchlist-Alarm)
    if data.get("alarm_type") in ("volatility", "rsi_overbought", "rsi_oversold"):
        await watchlist_alarm_coin(cq, state)
        return
    # Standard: Preisabfrage/Alarm/Portfolio
    current_state = await state.get_state()
    if current_state == BotStates.choosing_coin:
        await coin_chosen_for_price(cq, state)
        return
    await cq.answer()

# --- Handler für Sparziel Coin-Auswahl ---
async def savings_coin_chosen(cq: types.CallbackQuery, state: FSMContext):
    coin = cq.data.split(":", 1)[1]
    await state.update_data(coin=coin)
    await cq.message.edit_text(f"Gib die Zielmenge für *{coin}* ein (z.B. 1.5):", parse_mode="Markdown")
    await state.set_state(BotStates.savings_add)
    await cq.answer()

# --- Handler für Watchlist-Alarm Coin-Auswahl ---
async def watchlist_alarm_coin(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    coin = cq.data.split(":")[1]
    data = await state.get_data()
    alarm_type = data.get("alarm_type")
    await state.update_data(coin=coin)
    if alarm_type == "volatility":
        await cq.message.edit_text(
            f"⚡ *Volatilitäts-Alarm für {coin}*\nGib die Volatilitäts-Schwelle in % ein (z.B. 5):",
            parse_mode="Markdown"
        )
    elif alarm_type == "rsi_overbought":
        await cq.message.edit_text(
            f"📈 *RSI-Überkauft-Alarm für {coin}*\nGib den RSI-Schwellenwert ein (z.B. 70):",
            parse_mode="Markdown"
        )
    elif alarm_type == "rsi_oversold":
        await cq.message.edit_text(
            f"📉 *RSI-Überverkauft-Alarm für {coin}*\nGib den RSI-Schwellenwert ein (z.B. 30):",
            parse_mode="Markdown"
        )
    await state.set_state(BotStates.watchlist_alarm_value)
    await cq.answer()

# --- Handler für Preisabfrage Coin-Auswahl ---
async def coin_chosen_for_price(cq: types.CallbackQuery, state: FSMContext):
    """Handle a coin selection specifically for price lookup flows.

    This handler attempts to serve a cached price and falls back to
    a live API call. It then presents the price and the watchlist
    alarm keyboard.
    """
    user_id = str(cq.from_user.id)
    settings = load_file(USER_SETTINGS_FILE).get(user_id, {})
    currency = settings.get("currency", "USD")
    coin = cq.data.split(":", 1)[1]
    # Async cache first, fallback to live
    price = await get_price_cached_from_file_async(coin, currency)
    if price is None:
        price = await get_price(coin, currency)
    if price is not None:
        await cq.message.edit_text(
            f"💰 *{coin}*: **{price:.2f} {currency}**",
            parse_mode="Markdown",
            reply_markup=watchlist_alarm_keyboard()
        )
    else:
        await cq.message.edit_text(
            f"❌ Preis für {coin} konnte nicht abgerufen werden.",
            parse_mode="Markdown"
        )
    await state.clear()
    await cq.answer()

# --- Datumseingabe für Was-wäre-wenn ---
@router.message(StateFilter(BotStates.manual_target))
async def whatif_date_entered(message: types.Message, state: FSMContext):
    import re
    from datetime import datetime
    date_str = message.text.strip()
    # Prüfe Datumsformat
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        await message.reply("❌ Ungültiges Datum. Bitte im Format JJJJ-MM-TT eingeben.")
        await state.clear()
        return
    try:
        kaufdatum = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        await message.reply("❌ Ungültiges Datum. Bitte im Format JJJJ-MM-TT eingeben.")
        await state.clear()
        return
    data = await state.get_data()
    coin = data.get("whatif_coin")
    # Hier könnte die Was-wäre-wenn-Berechnung erfolgen (Platzhalter)
    await message.answer(f"Was-wäre-wenn für {coin} ab {date_str} (Feature folgt)")
    await state.clear()

# --- Debugging: Alle States zurücksetzen ---
@router.callback_query(lambda c: c.data == "debug_reset_states")
async def debug_reset_states(cq: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("✅ Alle States zurückgesetzt.", reply_markup=dashboard_keyboard())
    await cq.answer()

# --- Debugging: Aktuellen State anzeigen ---
@router.callback_query(lambda c: c.data == "debug_show_state")
async def debug_show_state(cq: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_state = await state.get_state()
    await cq.message.edit_text(f"🔍 Aktueller State: {current_state}\nDaten: {data}", reply_markup=dashboard_keyboard())
    await cq.answer()

# --- Settings Keyboard anpassen ---
def settings_keyboard(dark_mode: bool = False, show_watchlist_rsi: bool = True):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🌙 Dark Mode: ON" if dark_mode else "☀️ Dark Mode: OFF"), callback_data="toggle_darkmode")],
        [InlineKeyboardButton(text=("📈 Watchlist RSI: AN" if show_watchlist_rsi else "📈 Watchlist RSI: AUS"), callback_data="toggle_watchlist_rsi")],
        [InlineKeyboardButton(text="ℹ️ Info & Rechtliches", callback_data="show_info")],
        [InlineKeyboardButton(text="🔄 Währung", callback_data="dash_currency")],
        [InlineKeyboardButton(text="⚙️ Widgets", callback_data="dash_widgets")],
        [InlineKeyboardButton(text="🌐 Sprache / Language", callback_data="dash_language")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])

# --- Settings Handler für RSI-Toggle ---
@router.callback_query(lambda c: c.data == "toggle_watchlist_rsi")
async def toggle_watchlist_rsi(cq: types.CallbackQuery, state: FSMContext):
    user_id = str(cq.from_user.id)
    user_settings = load_file(USER_SETTINGS_FILE)
    show_rsi = user_settings.get(user_id, {}).get("show_watchlist_rsi", True)
    user_settings.setdefault(user_id, {})["show_watchlist_rsi"] = not show_rsi
    await save_file_async(USER_SETTINGS_FILE, user_settings)
    await cq.message.edit_text(
        "⚙️ *Einstellungen*\nHier kannst du Widgets und Sprache anpassen:",
        parse_mode="Markdown",
        reply_markup=settings_keyboard(
            dark_mode=user_settings[user_id].get("dark_mode", False),
            show_watchlist_rsi=not show_rsi
        )
    )
    await cq.answer()

# --- Info & Rechtliches Handler ---
@router.callback_query(lambda c: c.data == "show_info")
async def show_info(cq: types.CallbackQuery, state: FSMContext):
    text = (
        "ℹ️ *Info & Rechtliches*\n\n"
        "- Die Kursdaten, Preisänderungen und Volatilitäten werden über die öffentliche Binance API (https://binance.com) bezogen.\n"
        "- Die Chart-Bilder werden mit matplotlib erzeugt.\n"
        "- Die Bot-Plattform ist Telegram.\n"
        "- Die Daten (Portfolio, Alarme, Watchlist etc.) werden lokal auf dem Server gespeichert und nicht an Dritte weitergegeben.\n"
        "- Es handelt sich um keine Finanzberatung. Die bereitgestellten Informationen dienen nur zu Informationszwecken.\n"
        "- Für die Richtigkeit und Aktualität der Daten wird keine Haftung übernommen.\n"
        "- Anbieter der Kursdaten: Binance\n"
        "- Anbieter der Plattform: Telegram\n"
        "- Anbieter der Chart-Bibliothek: matplotlib (https://matplotlib.org)\n"
        "- Kontakt: PortfolioWatchBot@proton.me\n"
    )
    await cq.message.edit_text(text, parse_mode="Markdown", reply_markup=settings_keyboard())
    await cq.answer()
