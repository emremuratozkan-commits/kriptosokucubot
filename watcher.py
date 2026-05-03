# PREDATOR v3 — POSITION WATCHER
# 100ms loop | BE at 50% TP | Trailing at 70% TP | ROI-based exit
# Debug Logger entegre

import asyncio
import time
from config import (
    BE_ACTIVATION, TS_ACTIVATION,
    MAKER_FEE, TAKER_FEE, WATCHER_INTERVAL, LEVERAGE,
)


class Watcher:
    def __init__(self, engine):
        self.engine = engine

    async def watch(self, symbol: str):
        """Per-position monitoring loop (100ms)."""
        print(f"[WATCH] {symbol} takibi başladı.")

        while True:
            try:
                pos = self.engine.active_slots.get(symbol)
                if pos is None:
                    break

                # Fiyatı WebSocket cache'den al (0ms latency)
                price = self.engine.ws.get_price(symbol)
                if price <= 0:
                    await asyncio.sleep(0.3)
                    continue

                entry = pos['entry']
                side = pos['side']
                sl = pos['sl']
                tp = pos['tp']
                tp_pct = pos['tp_pct']
                sl_pct = pos['sl_pct']
                ts_dist = pos['ts_dist']
                peak = pos.get('peak', entry)
                amount = pos['amount']
                notional = pos['notional']

                # --- PnL Hesaplaması ---
                if side == 'buy':
                    raw_pnl_pct = (price - entry) / entry
                else:
                    raw_pnl_pct = (entry - price) / entry

                # Çıkış işlemi muhtemelen maker olacak (Post-Only first).
                # Fallback taker olursa debug logger düzeltecek.
                assumed_fee_pct = MAKER_FEE * 2  
                net_pnl_pct = raw_pnl_pct - assumed_fee_pct
                roi = net_pnl_pct * LEVERAGE
                pos['current_roi'] = roi

                # --- Peak güncelle ---
                if side == 'buy' and price > peak:
                    pos['peak'] = price
                    peak = price
                elif side == 'sell' and price < peak:
                    pos['peak'] = price
                    peak = price

                # --- BREAK EVEN (TP'nin %50'si) ---
                tp_progress = raw_pnl_pct / tp_pct if tp_pct > 0 else 0
                if tp_progress >= BE_ACTIVATION and not pos.get('be_moved', False):
                    pos['sl'] = entry
                    sl = entry
                    pos['be_moved'] = True
                    print(f"[BE] {symbol} SL → giriş ({entry:.5f})")
                    from telegram_cmd import send
                    asyncio.create_task(send(
                        f"🔒 <b>BREAK-EVEN: {symbol}</b>\n"
                        f"SL giriş fiyatına taşındı\n"
                        f"ROI: %{roi*100:.1f}"
                    ))

                # --- TRAILING STOP (TP'nin %70'i) ---
                if tp_progress >= TS_ACTIVATION:
                    if side == 'buy':
                        trail_sl = peak * (1 - ts_dist)
                        trail_sl = max(trail_sl, entry) # BE'den geriye gitmesin
                        if trail_sl > sl:
                            pos['sl'] = trail_sl
                            sl = trail_sl
                    else:
                        trail_sl = peak * (1 + ts_dist)
                        trail_sl = min(trail_sl, entry)
                        if trail_sl < sl:
                            pos['sl'] = trail_sl
                            sl = trail_sl

                # --- EXIT LOGIC ---
                exit_reason = ""

                # ROI-based exit (fiyat hedefini bekleme, ROI'yi gördüğünde çak)
                target_roi = tp_pct * LEVERAGE - assumed_fee_pct * LEVERAGE
                if roi >= target_roi:
                    exit_reason = "TAKE PROFIT"
                elif roi <= -(sl_pct * LEVERAGE):
                    exit_reason = "STOP LOSS"
                # Fiyat-based fallback
                elif side == 'buy':
                    if price >= tp:
                        exit_reason = "TAKE PROFIT"
                    elif price <= sl:
                        exit_reason = "STOP LOSS (Trailing/Fixed)"
                    elif tp_progress > 0.2: # Sadece biraz kardayken veya riskliyken bak
                        # Smart Exit (Orderflow Flip)
                        imbalance = self.engine.ws.get_imbalance(symbol)
                        delta = self.engine.ws.get_volume_delta(symbol)
                        if imbalance < 0.40 and delta < -0.10:
                            exit_reason = "SMART EXIT (Orderflow Reversal)"
                else:
                    if price <= tp:
                        exit_reason = "TAKE PROFIT"
                    elif price >= sl:
                        exit_reason = "STOP LOSS (Trailing/Fixed)"
                    elif tp_progress > 0.2:
                        imbalance = self.engine.ws.get_imbalance(symbol)
                        delta = self.engine.ws.get_volume_delta(symbol)
                        if imbalance > 0.60 and delta > 0.10:
                            exit_reason = "SMART EXIT (Orderflow Reversal)"

                if not exit_reason:
                    await asyncio.sleep(WATCHER_INTERVAL)
                    continue

                # ==========================================
                # ─── ÇIKIŞ BAŞLIYOR ───────────────────────
                # ==========================================
                
                # Executor ile çıkış yap
                closed = await self.engine.executor.place_close(symbol, side, amount)
                exit_price = self.engine.ws.get_price(symbol) # Çıkış fiyatı tahmini
                t_exit = time.time()
                hold_seconds = t_exit - pos['open_time']

                if not closed:
                    print(f"[WATCH] {symbol} kapatılamadı, retry loop'a girecek.")
                    await asyncio.sleep(0.5)
                    continue

                # Gerçek PnL ve Fee hesaplaması (yaklaşık)
                # Taker çıkış olduysa taker fee kes (IOC veya Market fallback var)
                # Tam kesinliği API response'dan almadığımız için tahmin yapıyoruz.
                is_taker_exit = "Market" in str(closed) or "IOC" in str(closed)
                actual_fee_pct = MAKER_FEE + (TAKER_FEE if is_taker_exit else MAKER_FEE)
                
                if side == 'buy':
                    gross_pnl_usdt = (exit_price - entry) / entry * notional
                else:
                    gross_pnl_usdt = (entry - exit_price) / entry * notional
                
                fees_paid = actual_fee_pct * notional
                net_pnl_usdt = gross_pnl_usdt - fees_paid
                final_roi = (net_pnl_usdt / notional) * LEVERAGE

                print(f"[EXIT] {symbol} | {exit_reason} | PnL: {net_pnl_usdt:+.2f}$ | Fee: {fees_paid:.3f}$")

                # Debug Logger Kaydı
                if self.engine.debug:
                    self.engine.debug.log_trade_exit(
                        symbol, side, entry, exit_price,
                        gross_pnl_usdt, net_pnl_usdt, fees_paid,
                        exit_reason, hold_seconds
                    )

                # İstatistik
                self.engine.stats['total'] += 1
                if net_pnl_usdt > 0:
                    self.engine.stats['wins'] += 1
                self.engine.stats['pnl'] += net_pnl_usdt

                # Risk / Bakiye güncelleme
                self.engine.risk.update_balance(self.engine.risk.balance + net_pnl_usdt)
                self.engine.risk.record_pnl(net_pnl_usdt)
                self.engine.risk.set_cooldown(symbol)

                # Telegram Bildirimi
                from telegram_cmd import send
                emoji = '🟢' if net_pnl_usdt >= 0 else '🔴'
                await send(
                    f"🏁 <b>CLOSE: {symbol}</b>\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"Sebep: {exit_reason}\n"
                    f"PnL: {emoji} <b>{net_pnl_usdt:+.3f} USDT</b>\n"
                    f"💸 Fee: -{fees_paid:.3f}$\n"
                    f"⏱️ Süre: {hold_seconds:.0f}s\n"
                    f"ROI: %{final_roi*100:.1f}\n"
                    f"Giriş: {entry:.5f} → Çıkış: {exit_price:.5f}\n"
                    f"💰 Bakiye: ${self.engine.risk.balance:.2f}\n"
                    f"📊 Günlük PnL: {self.engine.risk.daily_pnl:+.2f}$"
                )

                # Supabase'e log (background)
                from store import store
                asyncio.create_task(store.log_trade_close(
                    symbol, exit_reason, net_pnl_usdt, final_roi
                ))

                # Pozisyonu slot'tan sil
                self.engine.active_slots.pop(symbol, None)
                break

            except Exception as e:
                print(f"[WATCH ERROR] {symbol}: {e}")
                await asyncio.sleep(1)

        print(f"[WATCH] {symbol} takibi bitti.")
