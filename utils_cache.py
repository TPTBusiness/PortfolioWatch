"""Async and sync helpers for reading a process-local JSON cache (data/cache.json).

Purpose:
- Provide non-blocking accessors to cached price, 24h-change, RSI and MACD values stored in cache.json.
- Maintain an in-memory copy of the cache with simple mtime-based invalidation to reduce disk reads.
- Preserve synchronous accessors for legacy code while encouraging async usage for new code.

Concurrency and guarantees:
- Async loader serializes file reloads with an asyncio.Lock to prevent races.
- On any read error the functions log the exception and return None or an empty dict as appropriate.
- Cache keys use the canonical "SYMBOL_CURRENCY" uppercase form; callers should normalize symbols/currencies.

Example:
    price = await get_price_cached_from_file_async("BTC", "USD")
    price_sync = get_price_cached_from_file("BTC", "USD")  # legacy synchronous usage
"""
import os
import json
import logging
import aiofiles
import asyncio
from config.config import USER_SETTINGS_FILE

CACHE_FILE = "data/cache.json"
logger = logging.getLogger("CoinTrackerBot.Cache")

# --- RAM Cache for cache.json ---
_cache_data = None
_cache_mtime = None
_cache_lock = asyncio.Lock()

async def _load_cache_async():
    """Load cache.json into RAM (async). Refreshes when file mtime changes.

    Returns:
        dict: Parsed cache contents or {} on error.
    """
    global _cache_data, _cache_mtime
    async with _cache_lock:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            if _cache_data is None or _cache_mtime != mtime:
                async with aiofiles.open(CACHE_FILE, "r") as f:
                    content = await f.read()
                    _cache_data = json.loads(content)
                _cache_mtime = mtime
                logger.debug(f"[CACHE] cache.json loaded from disk (mtime={mtime})")
            else:
                logger.debug(f"[CACHE] cache.json served from RAM (mtime={mtime})")
            return _cache_data
        except Exception as e:
            logger.error(f"[CACHE] Error loading cache.json: {e}")
            return {}

async def get_price_cached_from_file_async(symbol: str, currency: str = "USD"):
    """Async accessor for cached price.

    Returns:
        float | None: Cached price or None if not found / on error.
    """
    try:
        cache = await _load_cache_async()
        key = f"{symbol.upper()}_{currency.upper()}"
        price = cache.get(key, {}).get("price")
        logger.info(f"[CACHE] get_price_cached_from_file_async: {key} -> {price}")
        return price
    except Exception as e:
        logger.error(f"[CACHE] Error reading price from cache: {e}")
        return None

async def get_24h_change_cached_from_file_async(symbol: str, currency: str = "USD"):
    """Async accessor for cached 24h percent change.

    Returns:
        float | None: Cached 24h change or None.
    """
    try:
        cache = await _load_cache_async()
        key = f"{symbol.upper()}_{currency.upper()}"
        change = cache.get(key, {}).get("24h_change")
        logger.info(f"[CACHE] get_24h_change_cached_from_file_async: {key} -> {change}")
        return change
    except Exception as e:
        logger.error(f"[CACHE] Error reading 24h change from cache: {e}")
        return None

async def calculate_rsi_cached_from_file_async(symbol: str, period: int = 14, currency: str = "USD"):
    """Async accessor for cached RSI for a given period.

    Returns:
        float | None: Cached RSI value or None.
    """
    try:
        cache = await _load_cache_async()
        key = f"{symbol.upper()}_{currency.upper()}"
        rsi = cache.get(key, {}).get(f"rsi_{period}")
        logger.info(f"[CACHE] calculate_rsi_cached_from_file_async: {key} (period={period}) -> {rsi}")
        return rsi
    except Exception as e:
        logger.error(f"[CACHE] Error reading RSI from cache: {e}")
        return None

async def get_macd_cached_from_file_async(symbol: str, currency: str = "USD"):
    """Async accessor for cached MACD payload.

    Returns:
        dict | None: Cached MACD data or None.
    """
    try:
        cache = await _load_cache_async()
        key = f"{symbol.upper()}_{currency.upper()}"
        macd = cache.get(key, {}).get("macd")
        logger.info(f"[CACHE] get_macd_cached_from_file_async: {key} -> {macd}")
        return macd
    except Exception as e:
        logger.error(f"[CACHE] Error reading MACD from cache: {e}")
        return None


def _load_cache():
    """Synchronous loader for cache.json (legacy). Mirrors async loader behavior synchronously."""
    global _cache_data, _cache_mtime
    try:
        mtime = os.path.getmtime(CACHE_FILE)
        if _cache_data is None or _cache_mtime != mtime:
            with open(CACHE_FILE, "r") as f:
                _cache_data = json.load(f)
            _cache_mtime = mtime
            logger.debug(f"[CACHE] cache.json loaded from disk (mtime={mtime})")
        else:
            logger.debug(f"[CACHE] cache.json served from RAM (mtime={mtime})")
        return _cache_data
    except Exception as e:
        logger.error(f"[CACHE] Error loading cache.json: {e}")
        return {}

def get_price_cached_from_file(symbol: str, currency: str = "USD"):
    """Synchronous accessor for cached price (legacy)."""
    try:
        cache = _load_cache()
        key = f"{symbol.upper()}_{currency.upper()}"
        price = cache.get(key, {}).get("price")
        logger.info(f"[CACHE] get_price_cached_from_file: {key} -> {price}")
        return price
    except Exception as e:
        logger.error(f"[CACHE] Error reading price from cache: {e}")
        return None

def get_24h_change_cached_from_file(symbol: str, currency: str = "USD"):
    """Synchronous accessor for cached 24h change (legacy)."""
    try:
        cache = _load_cache()
        key = f"{symbol.upper()}_{currency.upper()}"
        change = cache.get(key, {}).get("24h_change")
        logger.info(f"[CACHE] get_24h_change_cached_from_file: {key} -> {change}")
        return change
    except Exception as e:
        logger.error(f"[CACHE] Error reading 24h change from cache: {e}")
        return None

def calculate_rsi_cached_from_file(symbol: str, period: int = 14, currency: str = "USD"):
    """Synchronous accessor for cached RSI (legacy)."""
    try:
        cache = _load_cache()
        key = f"{symbol.upper()}_{currency.upper()}"
        rsi = cache.get(key, {}).get(f"rsi_{period}")
        logger.info(f"[CACHE] calculate_rsi_cached_from_file: {key} (period={period}) -> {rsi}")
        return rsi
    except Exception as e:
        logger.error(f"[CACHE] Error reading RSI from cache: {e}")
        return None

def get_macd_cached_from_file(symbol: str, currency: str = "USD"):
    """Synchronous accessor for cached MACD (legacy)."""
    try:
        cache = _load_cache()
        key = f"{symbol.upper()}_{currency.upper()}"
        macd = cache.get(key, {}).get("macd")
        logger.info(f"[CACHE] get_macd_cached_from_file: {key} -> {macd}")
        return macd
    except Exception as e:
        logger.error(f"[CACHE] Error reading MACD from cache: {e}")
        return None

# Prefer the async helpers for non-blocking access patterns in new code.
# Example:
#   price = await get_price_cached_from_file_async("BTC", "USD")
#   change = await get_24h_change_cached_from_file_async("BTC", "USD")
#   rsi = await calculate_rsi_cached_from_file_async("BTC", 14, "USD")
