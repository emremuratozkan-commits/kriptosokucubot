# SUPREME OMNI-FLOW v4.0 — ECONOMETRICS ENGINE
# GARCH(1,1) + Engle-Granger Cointegration + Z-Score + Hurst
# Tüm hesaplamalar numpy RAM üzerinde — veritabanı dokunulmaz.

import numpy as np
import warnings
warnings.filterwarnings('ignore')

try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False
    print("[WARN] arch kütüphanesi yok, GARCH devre dışı.")

try:
    from statsmodels.tsa.stattools import coint
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False
    print("[WARN] statsmodels yok, Cointegration devre dışı.")


class EconometricsEngine:
    """Tüm matematik burada. Dışarıya sadece sonuçlar çıkar."""

    def __init__(self):
        self.garch_cache = {}      # {symbol: conditional_variance}
        self.coint_cache = {}      # {(symA, symB): {'beta': float, 'z': float, 'valid': bool}}
        self.price_history = {}    # {symbol: np.array of closes}

    # ─── PRICE HISTORY ────────────────────────────────────────
    def update_prices(self, symbol: str, closes: list):
        self.price_history[symbol] = np.array(closes, dtype=np.float64)

    def get_closes(self, symbol: str) -> np.ndarray:
        return self.price_history.get(symbol, np.array([]))

    # ─── Z-SCORE ──────────────────────────────────────────────
    @staticmethod
    def zscore(arr: np.ndarray, window: int = 20) -> float:
        if len(arr) < window:
            return 0.0
        sub = arr[-window:]
        mean = np.mean(sub)
        std = np.std(sub)
        if std == 0:
            return 0.0
        return float((arr[-1] - mean) / std)

    # ─── RSI ──────────────────────────────────────────────────
    @staticmethod
    def rsi(closes: np.ndarray, period: int = 7) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes[-(period + 1):])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = float(np.mean(gains))
        avg_loss = float(np.mean(losses))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    # ─── HURST EXPONENT ──────────────────────────────────────
    @staticmethod
    def hurst(ts: np.ndarray) -> float:
        if len(ts) < 20:
            return 0.5
        try:
            lags = range(2, min(20, len(ts) // 2))
            tau = []
            valid_lags = []
            for lag in lags:
                diff = ts[lag:] - ts[:-lag]
                std_val = np.std(diff)
                if std_val > 0:
                    tau.append(np.sqrt(std_val))
                    valid_lags.append(lag)
            if len(tau) < 2:
                return 0.5
            poly = np.polyfit(np.log(valid_lags), np.log(tau), 1)
            h = float(poly[0] * 2.0)
            return max(0.0, min(1.0, h))
        except Exception:
            return 0.5

    # ─── GARCH(1,1) ──────────────────────────────────────────
    def fit_garch(self, symbol: str) -> float:
        """GARCH(1,1) conditional variance hesaplar.
        Returns: float — sonraki mumun beklenen varyansı
        """
        closes = self.get_closes(symbol)
        if len(closes) < 50 or not ARCH_AVAILABLE:
            return 0.0002  # default normal rejim

        try:
            returns = np.diff(np.log(closes[-100:])) * 100  # yüzde log-return
            model = arch_model(returns, vol='GARCH', p=1, q=1,
                               mean='Zero', rescale=False)
            result = model.fit(disp='off', show_warning=False)
            forecast = result.forecast(horizon=1)
            cond_var = float(forecast.variance.iloc[-1, 0]) / 10000
            self.garch_cache[symbol] = cond_var
            return cond_var
        except Exception:
            return self.garch_cache.get(symbol, 0.0002)

    def get_garch(self, symbol: str) -> float:
        return self.garch_cache.get(symbol, 0.0002)

    def fit_all_garch(self, symbols: list):
        """Tüm sembollerin GARCH'ını güncelle (5dk'da bir çağrılır)."""
        for sym in symbols:
            self.fit_garch(sym)

    # ─── COINTEGRATION ───────────────────────────────────────
    def test_cointegration(self, sym_a: str, sym_b: str) -> dict:
        """Engle-Granger cointegration testi.
        Returns: {'valid': bool, 'beta': float, 'z': float, 'spread_mean': float, 'spread_std': float}
        """
        closes_a = self.get_closes(sym_a)
        closes_b = self.get_closes(sym_b)

        if len(closes_a) < 50 or len(closes_b) < 50 or not STATSMODELS_AVAILABLE:
            return {'valid': False, 'beta': 0, 'z': 0, 'spread_mean': 0, 'spread_std': 0}

        min_len = min(len(closes_a), len(closes_b))
        a = closes_a[-min_len:]
        b = closes_b[-min_len:]

        try:
            _, pvalue, _ = coint(a, b)
            if pvalue >= 0.05:
                result = {'valid': False, 'beta': 0, 'z': 0, 'spread_mean': 0, 'spread_std': 0}
                self.coint_cache[(sym_a, sym_b)] = result
                return result

            # OLS hedge ratio
            if np.std(b) == 0 or np.std(a) == 0:
                result = {'valid': False, 'beta': 0, 'z': 0, 'spread_mean': 0, 'spread_std': 0}
                self.coint_cache[(sym_a, sym_b)] = result
                return result

            beta = float(np.polyfit(b, a, 1)[0])
            spread = a - beta * b
            spread_mean = float(np.mean(spread))
            spread_std = float(np.std(spread))
            z = float((spread[-1] - spread_mean) / spread_std) if spread_std > 0 else 0.0

            result = {'valid': True, 'beta': beta, 'z': z,
                      'spread_mean': spread_mean, 'spread_std': spread_std}
            self.coint_cache[(sym_a, sym_b)] = result
            return result
        except Exception:
            return self.coint_cache.get((sym_a, sym_b),
                   {'valid': False, 'beta': 0, 'z': 0, 'spread_mean': 0, 'spread_std': 0})

    def test_all_cointegrations(self, pairs: list):
        """Tüm çiftleri test et (15dk'da bir çağrılır)."""
        for sym_a, sym_b in pairs:
            self.test_cointegration(sym_a, sym_b)

    def get_coint(self, sym_a: str, sym_b: str) -> dict:
        return self.coint_cache.get((sym_a, sym_b),
               {'valid': False, 'beta': 0, 'z': 0, 'spread_mean': 0, 'spread_std': 0})

    # ─── EWMA VOLATILITY ─────────────────────────────────────
    @staticmethod
    def ewma_volatility(closes: np.ndarray, span: int = 20) -> float:
        if len(closes) < 3:
            return 0.0
        returns = np.diff(closes) / closes[:-1]
        weights = np.exp(np.linspace(-1, 0, min(span, len(returns))))
        weights /= weights.sum()
        recent = returns[-len(weights):]
        return float(np.sqrt(np.average(recent**2, weights=weights)))
