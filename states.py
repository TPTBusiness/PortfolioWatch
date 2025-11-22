"""Finite state definitions for the bot's conversational flows.

This module centralizes all aiogram FSM States used across dialogs (watchlist management, portfolio
operations, alarm creation, budget/savings flows, chart selection, etc.). Keep this list authoritative
so handlers can import BotStates for state checks and transitions.

Usage:
    from states import BotStates
    await state.set_state(BotStates.choosing_coin)

Notes:
- State names are intentionally descriptive to make handlers readable.
- Add new states here when introducing new multi-step interactions; keep naming consistent with existing patterns.
"""

from aiogram.fsm.state import StatesGroup, State

class BotStates(StatesGroup):
    """Named FSM states used by the Telegram bot.

    Each State represents a discrete step in a user flow. Handlers set and check these states
    to implement multi-message interactions (e.g., multi-step alarm creation).

    Example:
        @dp.message_handler(state=BotStates.manual_coin_input)
        async def handle_manual_coin(message: types.Message, state: FSMContext):
            # process manual coin input...
            await state.clear()
    """
    choosing_coin = State()
    choosing_direction = State()
    adjusting_target = State()
    manual_target = State()
    manual_coin_input = State()
    confirm_reset = State()
    watchlist_action = State()
    portfolio_add_amount = State()
    portfolio_buy = State()
    portfolio_sell = State()
    volatility_select = State()
    savings_add = State()
    budget_set = State()
    confirm_reset_code = State()
    fiat_deposit = State()
    fiat_withdraw = State()
    chart_select = State()
    watchlist_alarm_type = State()
    watchlist_alarm_value = State()
    percent_alert_coin = State()
    percent_alert_value = State()
    percent_alert_period = State()
    percent_alert_repeat = State()
    indicator_alert_coin = State()
    indicator_alert_type = State()
    indicator_alert_value = State()
    indicator_alert_repeat = State()
