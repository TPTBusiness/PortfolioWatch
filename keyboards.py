"""Keyboards module

This module defines a set of helper functions that build Telegram
InlineKeyboardMarkup objects used throughout the bot. Each function
returns a ready-to-use keyboard for a specific interaction (coin
selection, dashboard navigation, settings toggles, chart selection,
alerts, etc.). The functions are intentionally small and focused — they
only construct markup and do not perform any business logic.

The visual labels include emoji and short localized labels; callback
data follows a simple colon-separated convention that handlers can
parse (e.g. "coin:BTC", "page:1", "toggle_indicator:rsi").
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config.config import COIN_LIST


def coin_keyboard(page: int = 0, for_price: bool = False):
    """Return a paginated keyboard for selecting a coin.

    Args:
        page: Zero-based page index. Six coins are shown per page.
        for_price: When True, include an option to enter a custom coin
            (used in price-related flows).

    Returns:
        An `InlineKeyboardMarkup` instance containing coin buttons,
        optional navigation buttons, and an optional "other coin"
        entry.
    """
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    buttons = [InlineKeyboardButton(text=c, callback_data=f"coin:{c}") for c in COIN_LIST[page*6:(page+1)*6]]
    for i in range(0, len(buttons), 3):
        kb.inline_keyboard.append(buttons[i:i+3])
    if for_price:
        kb.inline_keyboard.append([InlineKeyboardButton(text="✏️ Other coin", callback_data="other_coin")])
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Back", callback_data=f"page:{page-1}"))
    if (page+1)*6 < len(COIN_LIST):
        nav_row.append(InlineKeyboardButton(text="➡️ Next", callback_data=f"page:{page+1}"))
    if nav_row:
        kb.inline_keyboard.append(nav_row)
    return kb


def dashboard_keyboard():
    """Return the main dashboard keyboard.

    The dashboard provides quick access to common sections such as the
    portfolio, watchlist, alarms, savings, charts and settings.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Portfolio", callback_data="dash_portfolio"),
         InlineKeyboardButton(text="👀 Watchlist", callback_data="dash_watchlist")],
        [InlineKeyboardButton(text="🔔 Alarms", callback_data="dash_alarms"),
         InlineKeyboardButton(text="🎯 Savings", callback_data="dash_savings")],
        [InlineKeyboardButton(text="📊 Chart", callback_data="dash_chart"),
         InlineKeyboardButton(text="💸💵 Fiat & Budget", callback_data="dash_fiatbudget")],
        [InlineKeyboardButton(text="⚙️ Settings", callback_data="dash_settings")]
    ])


def settings_keyboard(dark_mode: bool = False, show_watchlist_rsi: bool = True):
    """Return a keyboard to toggle and navigate user settings.

    Args:
        dark_mode: Whether dark mode is currently enabled (affects label).
        show_watchlist_rsi: Currently unused here, kept for potential
            extension where per-widget visibility may be shown.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("🌙 Dark Mode: ON" if dark_mode else "☀️ Dark Mode: OFF"), callback_data="toggle_darkmode")],
        [InlineKeyboardButton(text="🔄 Currency", callback_data="dash_currency")],
        [InlineKeyboardButton(text="⚙️ Widgets", callback_data="dash_widgets")],
        [InlineKeyboardButton(text="📊 Indicators", callback_data="dash_indicators")],
        [InlineKeyboardButton(text="🌐 Language", callback_data="dash_language")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])


def chart_select_keyboard():
    """Return a keyboard for selecting different chart types and tools."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Portfolio Distribution", callback_data="chart:portfolio"),
         InlineKeyboardButton(text="📈 Price History", callback_data="chart:price")],
        [InlineKeyboardButton(text="📉 Portfolio Value", callback_data="chart:value")],
        [InlineKeyboardButton(text="🧮 What-if", callback_data="chart:whatif"),
         InlineKeyboardButton(text="📅 DCA/Backtest", callback_data="chart:dca")],
        [InlineKeyboardButton(text="🔥 Heatmap", callback_data="chart:heatmap")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])


def watchlist_alarm_keyboard():
    """Return a keyboard for adding watchlist alarms based on indicators."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 RSI Overbought (>70)", callback_data="alarm_type:rsi_overbought"),
         InlineKeyboardButton(text="📉 RSI Oversold (<30)", callback_data="alarm_type:rsi_oversold")],
        [InlineKeyboardButton(text="⚡ High Volatility", callback_data="alarm_type:volatility"),
         InlineKeyboardButton(text="🔙 Watchlist", callback_data="dash_watchlist")]
    ])


def slider_keyboard(value: float):
    """Return a numeric slider-like keyboard for adjusting a value.

    The keyboard shows decrement/increment buttons and a central readout.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖ 10", callback_data="dec:10"),
            InlineKeyboardButton(text="➖ 1", callback_data="dec:1"),
            InlineKeyboardButton(text=f"{value:.0f}", callback_data="noop"),
            InlineKeyboardButton(text="➕ 1", callback_data="inc:1"),
            InlineKeyboardButton(text="➕ 10", callback_data="inc:10")
        ],
        [InlineKeyboardButton(text="✏️ Manual input", callback_data="manual")],
        [InlineKeyboardButton(text="✅ Confirm", callback_data="confirm"),
         InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])


def nft_keyboard():
    """Return navigation options for NFT-related features."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👾 NFT Watchlist", callback_data="nft_watchlist")],
        [InlineKeyboardButton(text="📈 NFT Values", callback_data="nft_values")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])


def rebalancing_keyboard():
    """Return a small keyboard for portfolio rebalancing actions."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Rebalance Suggestions", callback_data="rebalance_suggest")],
        [InlineKeyboardButton(text="🔙 Dashboard", callback_data="dash_back")]
    ])


# Popular technical indicators used across the UI
INDICATOR_LIST = [
    ("RSI", "rsi"),
    ("MACD", "macd"),
    ("EMA", "ema"),
    ("SMA", "sma"),
    ("Bollinger Bands", "bbands"),
    ("Stochastic", "stoch"),
    ("CCI", "cci"),
    ("ADX", "adx"),
    ("ATR", "atr"),
    ("OBV", "obv")
]


def indicators_keyboard(user_indicators: set):
    """Return a keyboard listing available indicators with toggles.

    Args:
        user_indicators: A set of indicator keys currently enabled for
            the user (e.g. {"rsi", "macd"}). Buttons reflect the
            enabled/disabled state.
    """
    rows = []
    for name, key in INDICATOR_LIST:
        active = key in user_indicators
        btn = InlineKeyboardButton(
            text=("✅ " if active else "❌ ") + name,
            callback_data=f"toggle_indicator:{key}"
        )
        rows.append([btn])
    rows.append([InlineKeyboardButton(text="🔙 Settings", callback_data="dash_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Configuration for periodic portfolio review settings
REVIEW_TIMES = [f"{h:02d}:00" for h in range(0, 24)]
REVIEW_FREQUENCIES = [
    ("Daily", "daily"),
    ("Weekly", "weekly")
]


def review_settings_keyboard(current_enabled, current_freq, current_time):
    """Return a keyboard to configure automated portfolio review.

    Args:
        current_enabled: Bool indicating whether automatic reviews are
            currently enabled.
        current_freq: Current frequency value (e.g. "daily" or
            "weekly").
        current_time: Current scheduled time string (e.g. "08:00").
    """
    rows = []
    rows.append([
        InlineKeyboardButton(
            text=("✅ Review: ON" if current_enabled else "❌ Review: OFF"),
            callback_data=f"review_toggle:{'off' if current_enabled else 'on'}"
        )
    ])
    if current_enabled:
        freq_row = [
            InlineKeyboardButton(
                text=("✅ " if current_freq == val else "") + label,
                callback_data=f"review_freq:{val}"
            ) for label, val in REVIEW_FREQUENCIES
        ]
        rows.append(freq_row)
        time_row = [
            InlineKeyboardButton(
                text=("✅ " if current_time == t else "") + t,
                callback_data=f"review_time:{t}"
            ) for t in REVIEW_TIMES[::4]
        ]
        rows.append(time_row)
    rows.append([InlineKeyboardButton(text="🔙 Settings", callback_data="dash_settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Period options used for percent-change alerts
PERCENT_PERIODS = [
    ("15 minutes", 15),
    ("30 minutes", 30),
    ("1 hour", 60),
    ("4 hours", 240),
    ("24 hours", 1440)
]


def percent_period_keyboard(current=None):
    """Return a keyboard to select a time period for percent-change alerts."""
    row = [InlineKeyboardButton(text=("✅ " if current == val else "")+label, callback_data=f"percent_period:{val}") for label, val in PERCENT_PERIODS]
    return InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="Cancel", callback_data="dash_back")]])


INDICATOR_ALERTS = [
    ("RSI > 70", "rsi_overbought"),
    ("RSI < 30", "rsi_oversold"),
    ("MACD Cross", "macd_cross"),
    ("EMA Cross", "ema_cross")
]


def indicator_type_keyboard(current=None):
    """Return a keyboard to choose the indicator alert type."""
    row = [InlineKeyboardButton(text=("✅ " if current == val else "")+label, callback_data=f"indicator_type:{val}") for label, val in INDICATOR_ALERTS]
    return InlineKeyboardMarkup(inline_keyboard=[row, [InlineKeyboardButton(text="Cancel", callback_data="dash_back")]])


def repeat_keyboard(current=None):
    """Return a keyboard for choosing repeat behaviour for alerts.

    Options currently are one-time ("once") or always ("always").
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ " if current=="once" else "")+"One-time", callback_data="repeat:once"),
         InlineKeyboardButton(text=("✅ " if current=="always" else "")+"Always", callback_data="repeat:always")],
        [InlineKeyboardButton(text="Cancel", callback_data="dash_back")]
    ])
