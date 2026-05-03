# PREDATOR v3 — CORE ENGINE
# WebSocket-first | Order Flow Signals | Adaptive TP/SL | Post-Only Execution
# GARCH & Hurst integrated | Debug Logger wired

import asyncio
import time
from config import SYMBOLS, MAX_SLOTS, SIGNAL_INTERVAL


class OmniEngine:
    def __init__(self, exchange, ws, signals, risk, executor, eco, debug):
        self.exchange = exchange
        self.ws = ws
        self.signals = signals
        self.risk = risk
        self.executor = executor
        self.eco = eco
        self.debug = debug
        self.watcher = None  # main.py'de set edilecek

        self.active_slots: dict[str, dict] = {}
        self.trade_gate = asyncio.Lock()
        self.running = False
        self.stats = {'wins': 0, 'total': 0, 'pnl': 0.0}

    # ─── ANA DÖNGÜ ──────────────────────────────────────────────
    async def run(self):
        self.running = True
        print(f"[ENGINE] {len(SYMBOLS)} sembol taranıyor. Max slot: {MAX_SLOTS}")
        while self.running:
            try:
                tasks = [self._evaluate(sym) for sym in SYMBOLS]
                await asyncio.gather(*tasks)
                await asyncio.sleep(SIGNAL_INTERVAL)
            except Exception as e:
                print(f"[ENGINE LOOP ERROR] {e}")
                await asyncio.sleep(1)

    async def stop(self):
        self.running = False

    # ─── SİNYAL DEĞERLENDİR ─────────────────────────────────────
    async def _evaluate(self, symbol: str):
        # Hızlı ön kontrol
        if symbol in self.active_slots:
            return

        async with self.trade_gate:
            if len(self.active_slots) >= MAX_SLOTS:
                return
            if not self.risk.can_open(symbol, len(self.active_slots)):
                return

        signal_time = time.time()
        sig = self.signals.evaluate(symbol)
        if sig is None:
            return

        side = sig['side']
        price = sig['price']
        atr_pct = sig['atr_pct']
        garch_var = sig['garch_var']

        # Trade parametreleri (ATR/GARCH-adaptive TP/SL)
        trade_params = self.signals.calc_trade_params(atr_pct, garch_var)
        sl_pct = trade_params['sl_pct']
        pos_params = self.risk.calc_position(price, sl_pct=sl_pct)
        amount = pos_params['amount']

        # ─── EMİR GÖNDER ────────────────────────────────────────
        async with self.trade_gate:
            # Çift kontrol
            if symbol in self.active_slots or len(self.active_slots) >= MAX_SLOTS:
                return

            order = await self.executor.place_entry(symbol, side, amount, atr_pct)

            if order is None:
                return

            fill_time = time.time()
            fill_price = float(order.get('average') or order.get('price') or price)
            fill_amount = float(order.get('filled', amount))

            # Debug Entry Log
            tp_pct = trade_params['tp_pct']
            sl_pct = trade_params['sl_pct']
            
            if self.debug:
                self.debug.log_trade_entry(
                    symbol, side, sig['imbalance'], sig['delta'],
                    sig['ema_dir'], atr_pct, sig['hurst'], garch_var,
                    fill_price, tp_pct, sl_pct, price, sig['score']
                )

            # TP/SL fiyatları
            if side == 'buy':
                tp = fill_price * (1 + tp_pct)
                sl = fill_price * (1 - sl_pct)
            else:
                tp = fill_price * (1 - tp_pct)
                sl = fill_price * (1 + sl_pct)

            pos = {
                'symbol': symbol,
                'side': side,
                'entry': fill_price,
                'tp': tp,
                'sl': sl,
                'tp_pct': tp_pct,
                'sl_pct': sl_pct,
                'ts_dist': trade_params['ts_dist'],
                'amount': fill_amount,
                'notional': pos_params['notional'],
                'leverage': pos_params['leverage'],
                'peak': fill_price,
                'be_moved': False,
                'current_roi': 0.0,
                'open_time': fill_time,
                'signal': sig,
            }
            self.active_slots[symbol] = pos

        # ─── TELEGRAM BİLDİRİM ──────────────────────────────────
        from telegram_cmd import send
        asyncio.create_task(send(
            f"🟢 <b>OPEN: {symbol} {side.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 Giriş: {fill_price:.5f}\n"
            f"🛑 SL: {sl:.5f} (%{sl_pct*100:.2f})\n"
            f"🎯 TP: {tp:.5f} (%{tp_pct*100:.2f})\n"
            f"⚙️ Kaldıraç: {pos_params['leverage']}x\n"
            f"📊 İmb: {sig['imbalance']:.2f} | Δ: {sig['delta']:.2f} | H: {sig['hurst']:.2f}\n"
            f"💰 Notional: ${pos_params['notional']:.1f}\n"
            f"⚡ Fill: {int((fill_time-signal_time)*1000)}ms\n"
            f"🎰 Slot: {len(self.active_slots)}/{MAX_SLOTS}"
        ))

        # ─── SUPABASE LOG ────────────────────────────────────────
        from store import store
        asyncio.create_task(store.log_trade_open({
            'symbol': symbol,
            'side': side,
            'entry': fill_price,
            'sl': sl,
            'tp': tp,
            'leverage': pos_params['leverage'],
            'notional': pos_params['notional'],
            'imbalance': sig['imbalance'],
            'delta': sig['delta'],
            'ema_dir': sig['ema_dir'],
            'atr_pct': atr_pct,
            'fill_latency_ms': int((fill_time - signal_time) * 1000),
            'status': 'open',
        }))

        # ─── WATCHER BAŞLAT ─────────────────────────────────────
        if self.watcher:
            asyncio.create_task(self.watcher.watch(symbol))

    # ─── STAT / DEBUG ────────────────────────────────────────────
    def avg_latency_ms(self) -> float:
        if not self.debug: return 0.0
        return self.debug.avg_latency_ms()

    def winrate(self) -> float:
        if not self.debug: return 0.0
        return self.debug.winrate()

