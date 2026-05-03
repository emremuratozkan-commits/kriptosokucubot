# PREDATOR v4 — ELITE SIGNAL ENGINE
# Trade Scoring Engine | Order Flow Edge | Market Regime Detection
# Elite Setup: A-grade trades only

import numpy as np
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
        """
        Elite Sinyal Motoru: Sadece A-grade orderflow setup'ları alır.
        Fake sinyalleri eler.
        """
        # ── 1. FİYAT / LİKİDİTE KONTROLÜ ────────────────────────
        price = self.ws.get_price(symbol)
        if price <= 0:
            return None

        atr = self.ws.get_atr(symbol)
        atr_pct = atr / price if price > 0 else 0
        if atr_pct < MIN_ATR_PCT:
            return None  # Ölü piyasa (volatilite yok)

        spread = self.ws.get_spread(symbol)
        if spread > MAX_SPREAD_PCT:
            return None  # Spread çok geniş (coin seçimi: temiz tahta)

        # ── 2. MARKET REGIME (HURST) ────────────────────────────
        hurst = 0.5
        garch_var = 0.0002
        if self.eco is not None:
            closes = self.eco.get_closes(symbol)
            if len(closes) >= 30:
                hurst = self.eco.hurst(closes)
                if hurst < HURST_CHOP_MAX:
                    return None  # Chop (testere) piyasasında işlem yapma
            garch_var = self.eco.get_garch(symbol)

        # ── 3. ELITE ORDER FLOW VERİLERİ ────────────────────────
        imbalance = self.ws.get_imbalance(symbol)
        delta = self.ws.get_volume_delta(symbol)
        ema_dir = self._ema_direction(symbol)
        
        absorption = self.ws.get_absorption(symbol)
        pull = self.ws.get_liquidity_pull(symbol)

        # ── 4. TRADE SCORING ENGINE ─────────────────────────────
        # Long/Short yönünü baştan belirle
        side = 'buy' if imbalance > 0.5 else 'sell'
        
        score = 0.0
        is_fake = False
        
        if side == 'buy':
            # ✔ Imbalance (0.62+ elite level)
            if imbalance > 0.62:
                score += self.SCORE_WEIGHTS['imbalance']
            elif imbalance > 0.55:
                score += self.SCORE_WEIGHTS['imbalance'] * 0.5
                
            # ✔ Aggressive Buyers (Delta > 20%)
            if delta > 0.20:
                score += self.SCORE_WEIGHTS['delta']
                
            # ✔ Trend Alignment
            if ema_dir == 'long':
                score += self.SCORE_WEIGHTS['trend']
                
            # ✔ Volatility (Hurst > 0.55 trending)
            if hurst > HURST_TREND_MIN:
                score += self.SCORE_WEIGHTS['volatility']
                
            # ✔ Liquidity Absorption / Pull (Edge)
            if absorption['bid']: # Ayıların satışı karşılanıyor (Bullish)
                score += self.SCORE_WEIGHTS['liquidity']
            if pull['ask']: # Yukarıdaki direnç çekildi
                score += self.SCORE_WEIGHTS['liquidity'] * 0.5
                
            # ❌ Fake Signal Filter
            if delta < 0.05 and imbalance > 0.65:
                is_fake = True # Sadece tahtaya emir yazıldı ama alan yok (Spoofing)
            if pull['bid']: 
                is_fake = True # Alt kademe desteği birden kayboldu
                
        else:
            # ✔ Imbalance (< 0.38 elite level)
            if imbalance < 0.38:
                score += self.SCORE_WEIGHTS['imbalance']
            elif imbalance < 0.45:
                score += self.SCORE_WEIGHTS['imbalance'] * 0.5
                
            # ✔ Aggressive Sellers
            if delta < -0.20:
                score += self.SCORE_WEIGHTS['delta']
                
            # ✔ Trend Alignment
            if ema_dir == 'short':
                score += self.SCORE_WEIGHTS['trend']
                
            # ✔ Volatility
            if hurst > HURST_TREND_MIN:
                score += self.SCORE_WEIGHTS['volatility']
                
            # ✔ Liquidity Absorption / Pull
            if absorption['ask']: # Boğaların alışı karşılanıyor (Bearish)
                score += self.SCORE_WEIGHTS['liquidity']
            if pull['bid']: # Alttaki destek çekildi
                score += self.SCORE_WEIGHTS['liquidity'] * 0.5
                
            # ❌ Fake Signal Filter
            if delta > -0.05 and imbalance < 0.35:
                is_fake = True # Satış baskısı sadece görüntü, hacim yok (Spoofing)
            if pull['ask']:
                is_fake = True # Üst direnç birden kayboldu, short squeeze gelebilir

        # Elite Filter: Yalnızca A-grade setuplar
        if is_fake or score < self.SCORE_THRESHOLD:
            return None

        # ── 5. FEE & EDGE PROTECTION ────────────────────────────
        # Hedeflenen kâr > fee + spread + buffer kontrolü
        trade_params = self.calc_trade_params(atr_pct, garch_var)
        expected_profit_pct = trade_params['tp_pct']
        
        # Taker fallback ihtimali ve slippage (buffer) hesaplaması
        max_fee_cost = (MAKER_FEE + TAKER_FEE) # En kötü senaryo fee
        edge_buffer = 0.0002 # Slippage ve belirsizlik buffer'ı
        
        if expected_profit_pct < (max_fee_cost + spread + edge_buffer):
            return None # Trade potansiyeli riske/masrafa değmez
            
        return {
            'side': side,
            'strength': int(score * 10), # 0-10 arası
            'score': score,
            'imbalance': imbalance,
            'delta': delta,
            'ema_dir': ema_dir,
            'atr_pct': atr_pct,
            'hurst': hurst,
            'garch_var': garch_var,
            'price': price,
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
