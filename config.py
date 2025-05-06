import os
from datetime import time, datetime

# Trading time restrictions
TRADING_START_TIME = time(1, 0)  # 07:00 UTC
TRADING_END_TIME = time(23, 0)   # 22:00 UTC

# Risk management
RISK_REWARD_RATIO = 2.5  # Соотношение риск/прибыль для информационных целей
TRAILING_STOP_ACTIVATION_PERCENT = 0.7  # Процент прибыли для активации трейлинг-стопа
TRAILING_STEP_PERCENT = 0.25  # Шаг трейлинг-стопа в процентах
PRICE_CHECK_INTERVAL = 5.0  # Интервал проверки цены в секундах (не слишком частый, чтобы не превысить API лимиты)

# Indicator parameters for different timeframes
TIMEFRAME_PARAMS = {
    "5m": {  # Скальпинг на 5-минутном таймфрейме
        "frama_length": 10,
        "stc_length": 21,
        "vfi_length": 100,
        "trail_trigger_percent": 0.7,  # 0.7% для активации трейлинга
        "trail_step_percent": 0.25,    # 0.25% шаг трейлинга
        "fixed_stop_percent": 0.5,     # 0.5% фиксированный стоп-лосс
    },
    "15m": {
        "frama_length": 10,
        "stc_length": 21,
        "vfi_length": 100,
        "trail_trigger_percent": 0.7,  # 0.7% для активации трейлинга
        "trail_step_percent": 0.25,    # 0.25% шаг трейлинга
        "fixed_stop_percent": 0.5,     # 0.5% фиксированный стоп-лосс
    },
    "1h": {
        "frama_length": 10, 
        "stc_length": 21,
        "vfi_length": 100,
        "trail_trigger_percent": 0.7,  # 0.7% для активации трейлинга
        "trail_step_percent": 0.25,    # 0.25% шаг трейлинга
        "fixed_stop_percent": 0.5,     # 0.5% фиксированный стоп-лосс
    }
}

# Default timeframe
DEFAULT_TIMEFRAME = "15m"  # Среднесрочная торговля на 15-минутном таймфрейме

# Trading parameters
LEVERAGE = 20
POSITION_SIZE_PERCENT = 15 # Percentage of balance to use per trade

# Trade direction - set to "both" to allow long and short positions
TRADE_DIRECTION = "both"  # Options: "both", "long", "short"

# Excel report settings
REPORTS_DIR = "reports"
TRADES_EXCEL_FILE = "trades_history.xlsx"

# Last time trades were fetched (default to 7 days ago to get recent trade history on first run)
LAST_TIME = datetime.now().timestamp() - 7 * 24 * 60 * 60  # 7 days ago in milliseconds

# Excel styling
EXCEL_STYLES = {
    "header_color": "000080",  # Dark blue
    "profit_color": "C6EFCE",  # Light green
    "loss_color": "FFC7CE",    # Light red
    "font_color": "FFFFFF",    # White for headers
    "border_style": "thin"     # Border style for cells
}

# Create reports directory if it doesn't exist
if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR) 