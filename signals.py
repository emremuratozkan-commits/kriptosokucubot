# PREDATOR v4 — ELITE SIGNAL ENGINE
# Trade Scoring Engine | Order Flow Edge | Market Regime Detection
# Elite Setup: A-grade trades only

import numpy as np
import time
from config import (
    EMA_FAST, EMA_SLOW, MODES, DEFAULT_MODE,
    TP_MIN, TP_MAX, TP_ATR_MULT,
    SL_MIN, SL_MAX, SL_ATR_MULT,
    TS_DIST_MIN, TS_DIST_MAX, TS_ATR_MULT,
    MAKER_FEE, TAKER_FEE, LEVERAGE, MIN_ATR_PCT, MAX_SPREAD_PCT,
)


# Hurst regime filtreleri
HURST_TREND_MIN = 0.55      
HURST_CHOP_MAX = 0.45       
GARCH_HIGH_VOL = 0.0008     


class SignalEngine:
    def __init__(self, ws_manager, eco_engine=None):
        self.ws = ws_manager
        self.eco = eco_engine  
        self.mode = DEFAULT_MODE
        
        # Elite Engine Parametreleri
        self.SCORE_THRESHOLD = 0.65  # Sadece A-grade trade'ler
        self.SCORE_WEIGHTS = {
            'imbalance': 0.35,
            'delta': 0.25,
            'trend': 0.15,
            'volatility': 0.10,
            'liquidity': 0.15
        }

    def set_mode(self, mode: str):
        if mode in MODES:
            self.mode = mode

    def evaluate(self, symbol: str) -> dict | None:
        # ── 1. ANA VERİLER VE SPREAD KONTROLÜ ──────────────────────
        price = self.ws.get_price(symbol)
        spread = self.ws.get_spread(symbol) # WebSocket'ten anlık makas
        atr = self.ws.get_atr(symbol)
        atr_pct = atr / price if price > 0 else 0
        
        # LİKİDİTE MUHAFIZI: Makas, volatilitenin %10'undan fazlaysa işlem açma (7/24 Koruması)
        if spread > (atr * 0.10): #
            return None

        # ── 2. PİYASA REJİMİ TESPİTİ (HURST) ────────────────────────
        hurst = 0.5
        if self.eco is not None:
            closes = self.eco.get_closes(symbol)
            if len(closes) >= 30:
                hurst = self.eco.hurst(closes) #

        # REJİM BELİRLEME
        if hurst > 0.55:
            regime = 'TREND'
            self.SCORE_THRESHOLD = 0.70 # Trend varken daha seçici ol
        elif hurst < 0.45:
            regime = 'MEAN_REVERSION'
            self.SCORE_THRESHOLD = 0.60 # Yatayda tepki alımları için esne
        else:
            return None # 'CHAOS' (0.45-0.55): Belirsizlikte 50x açılmaz.

        # ── 3. ADAPTİF SİNYAL PUANLAMA ──────────────────────────────
        imbalance = self.ws.get_imbalance(symbol)
        delta = self.ws.get_volume_delta(symbol)
        ema_dir = self._ema_direction(symbol)
        side = 'buy' if imbalance > 0.5 else 'sell'
        
        score = 0.0
        # Trend Rejiminde EMA yönü zorunluluğu
        if regime == 'TREND':
            if side == 'buy' and ema_dir != 'long': return None
            if side == 'sell' and ema_dir != 'short': return None
            score += 0.20 # Trend uyumuna ekstra puan

        # Standart Flow Kontrolleri
        if (side == 'buy' and imbalance > 0.65) or (side == 'sell' and imbalance < 0.35):
            score += self.SCORE_WEIGHTS['imbalance']
        if abs(delta) > 0.20:
            score += self.SCORE_WEIGHTS['delta']

        if score < self.SCORE_THRESHOLD:
            return None

        return {
            'side': side,
            'regime': regime, # Engine'a rejim bilgisini gönder
            'score': score,
            'price': price,
            'atr_pct': atr_pct,
            'hurst': hurst,
            'signal_time': time.time()
        }

    def calc_trade_params(self, atr_pct: float, garch_var: float = 0.0002) -> dict:
        """
        ATR + GARCH adaptive TP/SL/TS.
        Yüksek GARCH → daha geniş TP/SL (noise'a takılma).
        """
        vol_mult = 1.0
        if garch_var > GARCH_HIGH_VOL:
            vol_mult = 1.3 

        tp_pct = max(TP_MIN, min(TP_MAX, atr_pct * TP_ATR_MULT * vol_mult))
        sl_pct = max(SL_MIN, min(SL_MAX, atr_pct * SL_ATR_MULT * vol_mult))
        ts_dist = max(TS_DIST_MIN, min(TS_DIST_MAX, atr_pct * TS_ATR_MULT))

        if garch_var > GARCH_HIGH_VOL:
            ts_dist = max(TS_DIST_MIN, ts_dist * 0.7)

        # Min TP: fee + spread + güvenlik marjı
        min_tp = (MAKER_FEE * 2) + 0.0003
        tp_pct = max(tp_pct, min_tp)

        return {
            'tp_pct': tp_pct,
            'sl_pct': sl_pct,
            'ts_dist': ts_dist,
            'tp_roi': tp_pct * LEVERAGE,
            'sl_roi': sl_pct * LEVERAGE,
        }

    def _ema_direction(self, symbol) -> str:
        closes = self.ws.get_closes(symbol)
        if len(closes) < EMA_SLOW + 1:
            return 'neutral'
        fast = self._ema(closes, EMA_FAST)
        slow = self._ema(closes, EMA_SLOW)
        if fast > slow:
            return 'long'
        elif fast < slow:
            return 'short'
        return 'neutral'

    @staticmethod
    def _ema(data, period):
        if len(data) < period:
            return float(data[-1])
        alpha = 2.0 / (period + 1)
        val = float(data[0])
        for x in data[1:]:
            val = alpha * float(x) + (1 - alpha) * val
        return val
