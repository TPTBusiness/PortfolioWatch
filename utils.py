"""Utilities for exchange API access, indicator computations and simple file I/O.

This module exposes small, async-first helpers to:
- Fetch current prices, 24h changes and historical klines from Binance public endpoints.
- Compute a simple RSI indicator from historical hourly closes.
- Read/write JSON files (sync read, async write).
- Provide lightweight, process-local caches for short-lived values.

Concurrency and error semantics:
- Network calls are async to avoid blocking an event loop. Callers should await these functions.
- Functions return None on failure; callers must handle None appropriately.
- The provided caching wrappers are intentionally synchronous and store coroutine objects for backward compatibility — consider refactoring them to fully async in future.

Example:
    price = await get_price("BTC")
    rsi = await calculate_rsi("ETH", period=14)
"""

import aiohttp
import asyncio
from datetime import datetime
import json
import aiofiles
import time

async def get_price(symbol: str, currency: str = "USD") -> float | None:
    """Fetch current price for symbol (Binance USDT pair).

    Parameters:
        symbol: Asset ticker (e.g., "BTC", "ETH"). 'USDT' is appended internally.
        currency: "USD" (default) or "EUR" (simple conversion factor applied).

    Returns:
        float | None: Price in the requested currency, or None on error.
    """
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
        price = float(data["price"]) if "price" in data else None
        if currency == "EUR":
            return price * 0.9  # Simplified conversion factor: replace with FX API for production.
        return price
    except Exception:
        # Intentionally broad for resilience; callers should treat None as failure.
        return None

async def get_24h_change(symbol: str) -> float | None:
    """Return 24-hour percent price change for the given symbol.

    Parameters:
        symbol: Asset ticker (without quote currency).

    Returns:
        float | None: Percent change (e.g. 2.5 for +2.5%), or None on error.
    """
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}USDT"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
        return float(data["priceChangePercent"]) if "priceChangePercent" in data else None
    except Exception:
        return None

async def get_volatility(symbol: str, interval: str = "1d") -> dict | None:
    """Compute simple volatility metrics (high, low, volatility%) from klines.

    Parameters:
        symbol: Asset ticker.
        interval: Kline interval (e.g., "1h", "1d").

    Returns:
        dict | None: {"high": float, "low": float, "volatility": float} or None on error.
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval={interval}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
        if isinstance(data, list) and data:
            prices = [float(candle[4]) for candle in data]  # Closing prices
            high, low = max(prices), min(prices)
            volatility = ((high - low) / low) * 100 if low != 0 else 0
            return {"high": high, "low": low, "volatility": volatility}
        return None
    except Exception:
        return None

async def get_historical_prices(symbol: str, interval: str = "1h", limit: int = 24) -> list | None:
    """Fetch historical closing prices and return timestamped entries.

    Parameters:
        symbol: Asset ticker.
        interval: Kline interval string.
        limit: Number of klines to retrieve.

    Returns:
        list[dict] | None: [{"time": ISO8601, "price": float}, ...] ordered oldest->newest, or None on error.
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}USDT&interval={interval}&limit={limit}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
        if isinstance(data, list) and data:
            return [{"time": datetime.fromtimestamp(candle[0]/1000).isoformat(), "price": float(candle[4])} for candle in data]
        return None
    except Exception:
        return None

async def calculate_rsi(symbol: str, period: int = 14) -> float | None:
    """Compute the Relative Strength Index (RSI) using Wilder smoothing.

    Parameters:
        symbol: Asset ticker.
        period: Number of periods to compute RSI (default 14).

    Returns:
        float | None: RSI value in [0,100], or None if insufficient data or on error.
    """
    prices = await get_historical_prices(symbol, "1h", period + 1)
    if not prices or len(prices) < period + 1:
        return None
    changes = [prices[i]["price"] - prices[i-1]["price"] for i in range(1, len(prices))]
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    for i in range(len(gains) - period):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else float('inf')
    rsi = 100 - (100 / (1 + rs)) if rs != float('inf') else 100
    return rsi

def load_file(file: str) -> dict:
    """Synchronous JSON file reader with safe defaults.

    Returns:
        dict: Parsed JSON object or {} when file missing/empty/invalid.
    """
    try:
        with open(file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

async def save_file_async(file: str, data: dict):
    """Asynchronously write dict to file as pretty JSON.

    Notes:
        Uses aiofiles to avoid blocking the event loop.
    """
    async with aiofiles.open(file, "w") as f:
        await f.write(json.dumps(data, indent=2))

# --- Caching for price/24h-change/RSI (in-memory, process-local) ---
_price_cache = {}
_change_cache = {}
_rsi_cache = {}
_CACHE_TTL = 10  # Time-to-live for cache entries in seconds

def get_price_cached(symbol: str, currency: str = "USD"):
    """Lightweight cache wrapper for get_price.

    Returns:
        If a cached, fresh value exists, the cached value is returned immediately.
        Otherwise, the coroutine returned by get_price(...) is stored and returned.
        Callers should await the returned value when it is a coroutine.

    Note:
        This wrapper is currently synchronous to preserve existing call patterns.
        Consider making this function async and awaiting get_price internally for clearer semantics.
    """
    key = f"{symbol}_{currency}"
    now = time.time()
    if key in _price_cache and now - _price_cache[key][1] < _CACHE_TTL:
        return _price_cache[key][0]
    price = get_price(symbol, currency)
    _price_cache[key] = (price, now)
    return price

def get_24h_change_cached(symbol: str):
    """Lightweight cache wrapper for get_24h_change.

    Semantics same as get_price_cached regarding coroutine return.
    """
    now = time.time()
    if symbol in _change_cache and now - _change_cache[symbol][1] < _CACHE_TTL:
        return _change_cache[symbol][0]
    change = get_24h_change(symbol)
    _change_cache[symbol] = (change, now)
    return change

def calculate_rsi_cached(symbol: str, period: int = 14):
    """Cache wrapper for calculate_rsi.

    Returns either a cached float or the coroutine from calculate_rsi(...) which should be awaited.
    """
    key = f"{symbol}_{period}"
    now = time.time()
    if key in _rsi_cache and now - _rsi_cache[key][1] < _CACHE_TTL:
        return _rsi_cache[key][0]
    rsi = calculate_rsi(symbol, period)
    _rsi_cache[key] = (rsi, now)
    return rsi

# Hint: The synchronous caching wrappers should be converted to async in the future for full async semantics.
