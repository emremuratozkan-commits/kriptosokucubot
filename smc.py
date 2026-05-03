# SUPREME OMNI-FLOW v4.0 — SMART MONEY CONCEPTS
# Order Block, Fair Value Gap, Liquidity Hunt
# Saf numpy — veritabanı dokunulmaz.

import numpy as np


class SMCEngine:
    """Smart Money Concepts: Balina ayak izlerini takip eder."""

    # ─── ORDER BLOCK TESPİTİ ─────────────────────────────────
    @staticmethod
    def detect_order_blocks(opens, highs, lows, closes, volumes, lookback=30):
        """
        Bullish OB: Düşüş öncesi son yeşil, yüksek hacimli mum
        Bearish OB: Yükseliş öncesi son kırmızı, yüksek hacimli mum
        Returns: list of {'type': 'bullish'|'bearish', 'high': float, 'low': float}
        """
        n = len(closes)
        if n < lookback + 2:
            return []

        avg_vol = np.mean(volumes[-lookback:])
        blocks = []

        for i in range(n - lookback, n - 1):
            # Bullish OB
            if (closes[i] > opens[i] and               # yeşil mum
                closes[i + 1] < lows[i] and             # sonraki mum kırdı
                volumes[i] > avg_vol * 1.5):            # yüksek hacim
                blocks.append({
                    'type': 'bullish',
                    'high': float(highs[i]),
                    'low': float(lows[i]),
                    'idx': i
                })

            # Bearish OB
            if (closes[i] < opens[i] and               # kırmızı mum
                closes[i + 1] > highs[i] and            # sonraki mum kırdı
                volumes[i] > avg_vol * 1.5):
                blocks.append({
                    'type': 'bearish',
                    'high': float(highs[i]),
                    'low': float(lows[i]),
                    'idx': i
                })

        return blocks

    # ─── FAIR VALUE GAP ──────────────────────────────────────
    @staticmethod
    def detect_fvg(highs, lows, lookback=20):
        """
        Bullish FVG: candle[i-1].high < candle[i+1].low → boşluk
        Bearish FVG: candle[i-1].low > candle[i+1].high → boşluk
        Returns: list of {'type': 'bullish'|'bearish', 'top': float, 'bottom': float}
        """
        n = len(highs)
        if n < lookback + 2:
            return []

        gaps = []
        for i in range(n - lookback, n - 1):
            if i < 1 or i + 1 >= n:
                continue

            # Bullish FVG
            if highs[i - 1] < lows[i + 1]:
                gaps.append({
                    'type': 'bullish',
                    'top': float(lows[i + 1]),
                    'bottom': float(highs[i - 1]),
                    'idx': i
                })

            # Bearish FVG
            if lows[i - 1] > highs[i + 1]:
                gaps.append({
                    'type': 'bearish',
                    'top': float(lows[i - 1]),
                    'bottom': float(highs[i + 1]),
                    'idx': i
                })

        return gaps

    # ─── LIQUIDITY HUNT ──────────────────────────────────────
    @staticmethod
    def detect_liquidity_sweep(highs, lows, lookback=20):
        """
        Equal highs/lows arkasındaki stop patlatma iğnesi.
        Returns: {'sweep_long': bool, 'sweep_short': bool,
                  'prev_low': float, 'prev_high': float}
        """
        if len(highs) < lookback + 1:
            return {'sweep_long': False, 'sweep_short': False,
                    'prev_low': 0, 'prev_high': 0}

        recent_lows = lows[-(lookback + 1):-1]
        recent_highs = highs[-(lookback + 1):-1]
        prev_low = float(np.min(recent_lows))
        prev_high = float(np.max(recent_highs))

        current_low = float(lows[-1])
        current_high = float(highs[-1])

        return {
            'sweep_long': current_low < prev_low,    # dip kırdı → long sinyali
            'sweep_short': current_high > prev_high,  # tepe kırdı → short sinyali
            'prev_low': prev_low,
            'prev_high': prev_high
        }

    # ─── SMC SKORU ───────────────────────────────────────────
    @staticmethod
    def smc_score(side: str, price: float, order_blocks: list,
                  fvg_gaps: list, sweep: dict) -> float:
        """
        SMC güven skoru (0.0 — 1.0).
        Yüksek skor = balina desteği güçlü.
        """
        score = 0.0

        # Order Block desteği (+0.35)
        for ob in order_blocks:
            if side == 'buy' and ob['type'] == 'bullish':
                if ob['low'] <= price <= ob['high']:
                    score += 0.35
                    break
            elif side == 'sell' and ob['type'] == 'bearish':
                if ob['low'] <= price <= ob['high']:
                    score += 0.35
                    break

        # FVG desteği (+0.30)
        for gap in fvg_gaps:
            if side == 'buy' and gap['type'] == 'bullish':
                if gap['bottom'] <= price <= gap['top']:
                    score += 0.30
                    break
            elif side == 'sell' and gap['type'] == 'bearish':
                if gap['bottom'] <= price <= gap['top']:
                    score += 0.30
                    break

        # Liquidity Sweep (+0.35)
        if side == 'buy' and sweep.get('sweep_long', False):
            score += 0.35
        elif side == 'sell' and sweep.get('sweep_short', False):
            score += 0.35

        return min(score, 1.0)
