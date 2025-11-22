"""Application configuration and well-known file paths.

This module loads the runtime configuration from `config.json` and
exposes constants used across the application, including the bot
token and the canonical paths for data files. All paths are built
relative to this module's location so the project can be relocated
without changing code.

Do not store secrets in this file; keep them in `config.json` which
is read at import time.
"""

from pathlib import Path
import json

# Directory where this file resides
BASE_DIR = Path(__file__).resolve().parent

# Load `config.json` located alongside this module. The file is
# expected to contain runtime values such as `BOT_TOKEN`.
config_path = BASE_DIR / "config.json"
with config_path.open("r", encoding="utf-8") as f:
    config = json.load(f)

BOT_TOKEN = config["BOT_TOKEN"]

# Define data folder paths relative to project root
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"

# Canonical data files used by the application
ALARM_FILE = DATA_DIR / "alarms.json"
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
SAVINGS_FILE = DATA_DIR / "savings.json"
BUDGET_FILE = DATA_DIR / "budget.json"
TRANSACTIONS_FILE = DATA_DIR / "transactions.json"
USER_SETTINGS_FILE = DATA_DIR / "settings.json"
ACHIEVEMENTS_FILE = DATA_DIR / "achievements.json"
FIAT_TRANSACTIONS_FILE = DATA_DIR / "fiat_transactions.json"


# Small curated coin list used by the UI for quick selection.
COIN_LIST = ["BTC", "ETH", "SOL", "ADA", "TON", "XRP", "DOGE", "BNB", "LTC", "MATIC"]
