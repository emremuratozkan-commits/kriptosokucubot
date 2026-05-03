# PREDATOR v4 — AGGRESSIVE SCALP BOT CONFIG EXAMPLE
# Fill in your own values and rename this file to config.py

# --- EXCHANGE ---
BINANCE_API_KEY = "YOUR_BINANCE_API_KEY"
BINANCE_API_SECRET = "YOUR_BINANCE_API_SECRET"

# --- SUPABASE ---
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-supabase-key"

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = "your-bot-token"
TELEGRAM_CHAT_ID = ["your-chat-id"]

# --- SYMBOLS (Volatile + Liquid) ---
SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    '1000PEPE/USDT', 'WIF/USDT', 'DOGE/USDT', '1000BONK/USDT',
    'FLOKI/USDT', '1000SHIB/USDT', 'ORDI/USDT',
    'SUI/USDT', 'SEI/USDT', 'TIA/USDT', 'INJ/USDT',
    'FET/USDT', 'RENDER/USDT', 'APT/USDT',
    'OP/USDT', 'ARB/USDT', 'NEAR/USDT',
]

# --- RISK ---
MAX_SLOTS = 4
INITIAL_BALANCE = 100.0
MAX_DAILY_LOSS_PCT = 0.03
SYMBOL_COOLDOWN = 30
LEVERAGE = 40

# --- FEES ---
MAKER_FEE = 0.0002
TAKER_FEE = 0.0005

# --- MODE SYSTEM ---
MODES = {
    'aggressive': {
        'imbalance_long': 0.58,
        'imbalance_short': 0.42,
        'delta_threshold': 0.3,
        'ema_required': True,
    },
    'safe': {
        'imbalance_long': 0.65,
        'imbalance_short': 0.35,
        'delta_threshold': 0.5,
        'ema_required': True,
    }
}
DEFAULT_MODE = 'aggressive'

# --- EMA ---
EMA_FAST = 9
EMA_SLOW = 21

# --- ADAPTIVE TP/SL (ATR-driven) ---
TP_MIN = 0.0015
TP_MAX = 0.004
TP_ATR_MULT = 1.0

SL_MIN = 0.001
SL_MAX = 0.0025
SL_ATR_MULT = 0.7

# --- BREAK EVEN ---
BE_ACTIVATION = 0.5

# --- TRAILING STOP ---
TS_ACTIVATION = 0.7
TS_DIST_MIN = 0.0005
TS_DIST_MAX = 0.0015
TS_ATR_MULT = 0.3

# --- EXECUTION ---
REPRICING_DELAY = 0.15
MAX_REPRICING_ATTEMPTS = 4
POST_ONLY_TIMEOUT = 0.6

# --- TIMING ---
SIGNAL_INTERVAL = 0.2
WATCHER_INTERVAL = 0.1
DELTA_WINDOW = 30

# --- MIN VOLATILITY ---
MIN_ATR_PCT = 0.0005
MAX_SPREAD_PCT = 0.002
