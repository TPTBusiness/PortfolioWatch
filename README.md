# CoinTrackerBot

A Telegram bot for tracking cryptocurrencies, managing portfolios, setting alarms, and more.  
Built with **Python**, **aiogram** for Telegram integration, and **APScheduler** for scheduled tasks.

This project is now open-sourced to encourage community-driven development.  
The original developer has stepped back from active maintenance, but the codebase is stable and ready for new contributors.  
Feel free to fork, extend, and evolve it—add advanced charting, more indicators, new APIs, or anything the community needs.

---

## Features

### Portfolio Management
- Buy and sell coins  
- Track portfolio value  
- View fiat balances

### Watchlist
- Monitor your favorite coins  
- View prices, 24h changes, RSI, MACD, and other indicators

### Alarms
- Price thresholds  
- Percentage change alerts  
- Indicator-based triggers (e.g., RSI overbought/oversold)

### Budget & Savings
- Define budgets  
- Set savings goals  
- Track spending over time

### Achievements
- Unlock badges for milestones (first purchase, portfolio value targets, etc.)

### Monthly Reports
- Automatic summaries of portfolio performance

### Spam Protection
- Rate limiting to avoid abuse

### Caching
- File-based price caching for efficient API usage

### Dashboard
- Interactive interface with Telegram keyboards for easy navigation

---

## Requirements

- **Python 3.12+**
- Libraries:
  - `aiogram`
  - `apscheduler`
  - `requests` (for APIs such as CoinGecko)
  - `json`
  - Other dependencies as imported in `main.py`
- **Telegram Bot Token** from `@BotFather`
- **API Access:** Uses the free CoinGecko API (no token required)

---

## Setup

1. Clone the repository
   ```bash
   git clone https://github.com/TPTBusiness/PortfolioWatch.git
   ```

2. Install dependencies
   ```bash
   pip install aiogram apscheduler requests
   ```

3. Create configuration file  
   In `config/config.py`:
   ```python
   # Example config/config.py
   BOT_TOKEN = "your_bot_token_here"
   ALARM_FILE = "data/alarms.json"
   # add other paths and settings as needed
   ```

4. Prepare data directory  
   Create a `data/` folder for JSON files (these are created automatically if missing, but you can pre-create them):
   - `data/cache.json` – price cache  
   - `data/portfolio.json` – user portfolios  
   - other JSON files for alarms, watchlists, etc.

5. Run the bot
   ```bash
   python main.py
   ```

---

## Usage

- Start the bot in Telegram with `/start`
- Navigate via the on-screen dashboard buttons
- For manual coin lookup, type a symbol (e.g., `BTC`)
- Set alarms using the callback buttons provided in the interface

---

## Contributing

Contributions are welcome and highly encouraged. With the original developer stepping back, this is an opportunity to shape the future of the project.

Ideas for enhancements:
- Add new cryptocurrencies, exchanges, or alternative data sources
- Expand technical indicators
- Improve UI/UX with richer keyboards or visual tools
- Fix bugs, improve performance, refactor structure, or add tests

Contribution workflow:
```bash
# Fork the repository, then:
git checkout -b feature/new-feature
git commit -m "Add new feature"
git push origin feature/new-feature
# Open a Pull Request on GitHub
```

Please follow Python best practices and include tests when possible.

---

## License

MIT License — see the LICENSE file for details.

---

## Disclaimer

This bot uses public APIs; data such as prices may not be real-time or fully accurate. This is not financial advice—use the bot at your own risk.

Originally developed in 2025 and released to the public for community contribution.
