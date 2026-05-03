# PREDATOR v3 — DEBUG LOGGER
# Checklist-driven: execution latency | fee bleed | entry quality | signal log
# Her trade'den öğren → sistematik debug

import time
import asyncio
from collections import deque


class DebugLogger:
    """
    Debug Checklist implementasyonu:
    1. Execution latency check
    2. Fee bleed check
    3. Entry quality check (imbalance / delta değerleri)
    4. Exit reason tracking
    """

    def __init__(self, maxlen: int = 500):
        self.trades: deque = deque(maxlen=maxlen)
        self.latency_log: deque = deque(maxlen=200)
        self._lock = asyncio.Lock() if False else None  # sync-safe deque

    # ─── EXECUTION LOG ───────────────────────────────────────────
    def log_execution(self, symbol: str, side: str,
                      signal_time: float, order_sent_time: float,
                      fill_time: float, fill_price: float,
                      attempt: int, is_maker: bool):
        """Her girişi logla — latency + maker/taker analizi."""
        latency_ms = int((fill_time - signal_time) * 1000)
        send_delay_ms = int((order_sent_time - signal_time) * 1000)
        fill_delay_ms = int((fill_time - order_sent_time) * 1000)

        entry = {
            'ts': fill_time,
            'symbol': symbol,
            'side': side,
            'signal_time': signal_time,
            'order_sent_time': order_sent_time,
            'fill_time': fill_time,
            'total_latency_ms': latency_ms,
            'send_delay_ms': send_delay_ms,
            'fill_delay_ms': fill_delay_ms,
            'fill_price': fill_price,
            'attempt': attempt,
            'is_maker': is_maker,
        }
        self.latency_log.append(entry)

        # Uyarı: 200ms üstü BAD
        tag = '🟢' if latency_ms < 200 else ('🟡' if latency_ms < 400 else '🔴')
        maker_tag = 'MAKER' if is_maker else 'TAKER(!)'
        print(f"[DEBUG EXEC] {tag} {symbol} {side.upper()} | "
              f"Total:{latency_ms}ms Send:{send_delay_ms}ms Fill:{fill_delay_ms}ms | "
              f"{maker_tag} | Deneme#{attempt}")

    # ─── TRADE ENTRY LOG ─────────────────────────────────────────
    def log_trade_entry(self, symbol: str, side: str,
                        imbalance: float, delta: float,
                        ema_dir: str, atr_pct: float,
                        hurst: float, garch_var: float,
                        entry_price: float, tp_pct: float, sl_pct: float,
                        signal_price: float, score: float):
        """Sinyal kalitesini kaydet → entry quality analysis."""
        
        # Calculate Slippage (Expected vs Filled)
        if side == 'buy':
            slippage = entry_price - signal_price
            slippage_pct = (slippage / signal_price) * 100
        else:
            slippage = signal_price - entry_price
            slippage_pct = (slippage / signal_price) * 100
        record = {
            'type': 'entry',
            'ts': time.time(),
            'symbol': symbol,
            'side': side,
            'imbalance': round(imbalance, 4),
            'delta': round(delta, 4),
            'ema_dir': ema_dir,
            'atr_pct': round(atr_pct, 6),
            'hurst': round(hurst, 4),
            'garch_var': round(garch_var, 8),
            'entry_price': entry_price,
            'signal_price': signal_price,
            'slippage_pct': round(slippage_pct, 4),
            'tp_pct': round(tp_pct, 6),
            'sl_pct': round(sl_pct, 6),
            'score': round(score, 2),
        }
        self.trades.append(record)

        # Slippage Uyarısı
        if slippage_pct > 0.1: # 0.1% negative slippage
            print(f"[SLIPPAGE ⚠️] {symbol} Negatif Kayma: %{slippage_pct:.3f} | Sinyal: {signal_price:.5f} -> Doldu: {entry_price:.5f}")

    # ─── TRADE EXIT LOG ──────────────────────────────────────────
    def log_trade_exit(self, symbol: str, side: str,
                       entry_price: float, exit_price: float,
                       gross_pnl: float, net_pnl: float,
                       fees_paid: float, exit_reason: str,
                       hold_seconds: float):
        """Çıkışı kaydet → fee bleed + exit quality analysis."""
        record = {
            'type': 'exit',
            'ts': time.time(),
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'gross_pnl': round(gross_pnl, 4),
            'net_pnl': round(net_pnl, 4),
            'fees_paid': round(fees_paid, 4),
            'fee_ate_pct': round(fees_paid / max(abs(gross_pnl), 0.0001) * 100, 1),
            'exit_reason': exit_reason,
            'hold_seconds': round(hold_seconds, 1),
            'profitable': net_pnl > 0,
        }
        self.trades.append(record)

        # Fee bleed uyarısı
        if record['fee_ate_pct'] > 50:
            print(f"[FEE BLEED ⚠️] {symbol}: "
                  f"Gross={gross_pnl:.4f}$ Fee={fees_paid:.4f}$ → "
                  f"Fee oranı %{record['fee_ate_pct']:.0f}")

    # ─── ANALİZ ──────────────────────────────────────────────────
    def avg_latency_ms(self) -> float:
        if not self.latency_log:
            return 0.0
        return sum(x['total_latency_ms'] for x in self.latency_log) / len(self.latency_log)

    def taker_ratio(self) -> float:
        """Taker fallback oranı → %20 üstü tehlikeli."""
        entries = [x for x in self.latency_log]
        if not entries:
            return 0.0
        takers = sum(1 for x in entries if not x['is_maker'])
        return takers / len(entries)

    def winrate(self) -> float:
        exits = [t for t in self.trades if t['type'] == 'exit']
        if not exits:
            return 0.0
        wins = sum(1 for t in exits if t['profitable'])
        return wins / len(exits)

    def net_pnl(self) -> float:
        exits = [t for t in self.trades if t['type'] == 'exit']
        return sum(t['net_pnl'] for t in exits)

    def avg_hold_seconds(self) -> float:
        exits = [t for t in self.trades if t['type'] == 'exit']
        if not exits:
            return 0.0
        return sum(t['hold_seconds'] for t in exits) / len(exits)
        
    def avg_slippage_pct(self) -> float:
        entries = [t for t in self.trades if t['type'] == 'entry']
        if not entries:
            return 0.0
        return sum(t.get('slippage_pct', 0) for t in entries) / len(entries)

    def avg_imbalance_on_loss(self) -> float:
        """Kaybeden trade'lerin ortalama imbalance'ı → sinyal kalitesi."""
        entries = {t['symbol'] + str(t['ts']): t
                   for t in self.trades if t['type'] == 'entry'}
        exits = [t for t in self.trades if t['type'] == 'exit' and not t['profitable']]
        if not exits or not entries:
            return 0.0
        # Yakın zamanlı entry'leri say (basit yaklaşım)
        recent_entries = [t for t in self.trades if t['type'] == 'entry']
        if not recent_entries:
            return 0.0
        return sum(t['imbalance'] for t in recent_entries[-20:]) / len(recent_entries[-20:])

    def expected_value(self) -> float:
        """EV = (winrate * avg_win) - (lossrate * avg_loss)"""
        exits = [t for t in self.trades if t['type'] == 'exit']
        if not exits:
            return 0.0
        wins = [t['net_pnl'] for t in exits if t['net_pnl'] > 0]
        losses = [abs(t['net_pnl']) for t in exits if t['net_pnl'] <= 0]
        wr = len(wins) / len(exits)
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        return (wr * avg_win) - ((1 - wr) * avg_loss)

    def full_report(self) -> str:
        """Telegram /debug komutu için tam rapor."""
        exits = [t for t in self.trades if t['type'] == 'exit']
        total = len(exits)
        ev = self.expected_value()
        ev_tag = '🟢' if ev > 0 else '🔴'
        taker_r = self.taker_ratio() * 100
        taker_tag = '🟢' if taker_r < 20 else '🔴'
        avg_lat = self.avg_latency_ms()
        lat_tag = '🟢' if avg_lat < 200 else '🔴'

        return (
            f"🔍 <b>DEBUG RAPORU</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Trade Sayısı: {total}\n"
            f"🏆 Winrate: %{self.winrate()*100:.1f}\n"
            f"💰 Net PnL: {self.net_pnl():+.3f}$\n"
            f"{ev_tag} Expected Value: {ev:+.4f}$/trade\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{lat_tag} Ort. Latency: {avg_lat:.0f}ms\n"
            f"{taker_tag} Taker Oranı: %{taker_r:.0f}\n"
            f"⏱ Ort. Tutma: {self.avg_hold_seconds():.0f}s\n"
            f"📉 Avg İmbalance (kayıp): {self.avg_imbalance_on_loss():.3f}\n"
            f"🧊 Ort. Slippage: %{self.avg_slippage_pct():.3f}"
        )
