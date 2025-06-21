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

# Indicator parameters for selected timeframes
TIMEFRAME_PARAMS = {
    "1h": {
        "frama_length": 14,
        "adx_length": 14,
        "rsi_length": 14,
        "ema_length": 200,
        "stop_loss_percent": 1.0,
        "trail_trigger_percent": 1.5,
        "trail_step_percent": 0.7,
        "adx_min": 15,
        "rsi_entry_margin": 5,
        "stc_length": 23,
        "vfi_length": 120,
    },
    "4h": {
        "frama_length": 14,
        "adx_length": 14,
        "rsi_length": 14,
        "ema_length": 200,
        "fixed_stop_percent": 1.0,
        "trail_trigger_percent": 1.5,
        "trail_step_percent": 0.7,
        "adx_min": 15,
        "rsi_entry_margin": 5,
        "stc_length": 23,
        "vfi_length": 120,
        "stop_loss_percent": 1.0,
    }
}

# Default timeframe
DEFAULT_TIMEFRAME = "4h"

# Trading parameters
LEVERAGE = 5
POSITION_SIZE_PERCENT = 6  # Percentage of balance to use per trade

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
    "border_style": "thin"      # Border style for cells
}

# Create reports directory if it doesn't exist
if not os.path.exists(REPORTS_DIR):
    os.makedirs(REPORTS_DIR)