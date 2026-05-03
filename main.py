# PREDATOR v4 — ELITE ENTRY POINT
# Tüm bileşenleri bağlar: exchange → ws → signals → executor → engine → telegram

import asyncio
import sys

# uvloop: Linux/VPS'de aktif, Windows'da devre dışı
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    print("[MAIN] uvloop aktif (ultra-low-latency mod).")
except ImportError:
    print("[MAIN] uvloop yok, standart asyncio kullanılıyor.")

import ccxt.pro as ccxtpro
from config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    SYMBOLS, LEVERAGE,
)
from ws_manager import WebSocketManager
from signals import SignalEngine
from executor import Executor
from risk import RiskManager
from watcher import Watcher
from engine import OmniEngine
from telegram_cmd import TelegramBot, send
from econometrics import EconometricsEngine
from debug_logger import DebugLogger


async def prepare_exchange_for_sniper(exchange, symbols, leverage=50):
    print("[INIT] Sniper modu için borsaya kaldıraçlar tanımlanıyor...")
    for sym in symbols:
        try:
            await exchange.set_leverage(leverage, sym)
            await exchange.set_margin_mode('isolated', sym)
        except Exception as e:
            # Bazı coinler 50x desteklemezse fallback yap
            pass
    print("[INIT] Tüm silahlar doldu. Bot başlatılıyor.")


async def bootstrap():
    print("=" * 50)
    print("  PREDATOR v4 — AGRESİF SCALP BOT")
    print("  Post-Only | Order Flow | Adaptive TP/SL")
    print("=" * 50)

    # ── 1. EXCHANGE ──────────────────────────────────────
    exchange = ccxtpro.binanceusdm({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_API_SECRET,
        'enableRateLimit': False,       # WS-first, rate limit devre dışı
        'options': {
            'defaultType': 'future',
            'adjustForTimeDifference': True,
        },
        'asyncio_loop': asyncio.get_event_loop(),
    })
    print("[MAIN] Exchange bağlandı: Binance USDM Futures")

    # ── 2. MARKETS YÜKLEMESİ ─────────────────────────────
    await exchange.load_markets()
    print(f"[MAIN] Piyasa verileri yüklendi.")

    # ── 2.5 KALDIRAÇ AYARLARI ────────────────────────────
    await prepare_exchange_for_sniper(exchange, SYMBOLS, LEVERAGE)

    # ── 3. WEBSOCKET MANAGER ─────────────────────────────
    ws = WebSocketManager(exchange)
    await ws.start(SYMBOLS)

    # ── 4. ECONOMETRICS ──────────────────────────────────
    eco = EconometricsEngine()

    # ── 5. DEBUG LOGGER ──────────────────────────────────
    debug = DebugLogger()

    # ── 6. SIGNALS ───────────────────────────────────────
    signals = SignalEngine(ws, eco)

    # ── 7. RISK ──────────────────────────────────────────
    risk = RiskManager()

    # ── 8. EXECUTOR ──────────────────────────────────────
    executor = Executor(exchange, ws, debug)

    # ── 9. ENGINE ────────────────────────────────────────
    engine = OmniEngine(exchange, ws, signals, risk, executor, eco, debug)

    # ── 10. WATCHER ──────────────────────────────────────
    watcher = Watcher(engine)
    engine.watcher = watcher  # cross-reference

    # ── 11. TELEGRAM ─────────────────────────────────────
    tg = TelegramBot(engine)

    # ── 12. GARCH BACKGROUND TASK ────────────────────────
    async def garch_updater():
        """Her 5 dakikada GARCH + Hurst güncelle."""
        while True:
            try:
                for sym in SYMBOLS:
                    closes = ws.get_closes(sym).tolist()
                    if closes:
                        eco.update_prices(sym, closes)
                eco.fit_all_garch(SYMBOLS)
                print(f"[ECO] GARCH güncellendi ({len(SYMBOLS)} sembol).")
            except Exception as e:
                print(f"[ECO ERROR] {e}")
            await asyncio.sleep(300)

    # ── BAŞLAT ───────────────────────────────────────────
    await send(
        "🚀 <b>PREDATOR v4 ELITE BAŞLADI</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📊 Semboller: {len(SYMBOLS)}\n"
        f"🎰 Max Slot: 4\n"
        f"⚙️ Kaldıraç: {LEVERAGE}x\n"
        f"🔒 Mod: AGGRESSIVE\n"
        "⚡ Post-Only | Maker-First | Elite Engine v4"
    )

    await asyncio.gather(
        engine.run(),
        tg.run(),
        garch_updater(),
    )

    # ── KAPANIŞ ──────────────────────────────────────────
    await ws.close()
    await exchange.close()
    print("[MAIN] Bot kapatıldı.")


if __name__ == "__main__":
    try:
        asyncio.run(bootstrap())
    except KeyboardInterrupt:
        print("\n[MAIN] Ctrl+C ile durduruldu.")
        sys.exit(0)
