# PREDATOR v3 — DYNAMIC REPRICING EXECUTOR
# Post-Only | 4-attempt adaptive chase | Volatility-aware delay
# Taker fallback sadece exit'te (zorunlu çıkış)

import asyncio
import time
from config import (
    REPRICING_DELAY, MAX_REPRICING_ATTEMPTS,
    POST_ONLY_TIMEOUT, LEVERAGE,
    MAKER_FEE, TAKER_FEE,
)


class Executor:
    def __init__(self, exchange, ws_manager, debug_logger=None):
        self.exchange = exchange
        self.ws = ws_manager
        self.debug = debug_logger  # DebugLogger (opsiyonel)

    async def place_entry(
        self, symbol: str, side: str, amount: float,
        atr_pct: float = 0.001
    ) -> dict | None:
        """
        Dynamic repricing Post-Only entry.
        - Volatiliteye göre adaptif delay
        - Her denemede 1 tick daha agresif
        - Debug log ile latency tracking
        """
        t_signal = time.time()
        try:
            # ── LEVERAGE ─────────────────────────────────────────
            try:
                await self.exchange.set_leverage(LEVERAGE, symbol)
            except Exception:
                for fb in [20, 15, 10, 5]:
                    try:
                        await self.exchange.set_leverage(fb, symbol)
                        break
                    except Exception:
                        continue

            try:
                await self.exchange.set_margin_mode('isolated', symbol)
            except Exception:
                pass

            amount = float(self.exchange.amount_to_precision(symbol, amount))
            if amount <= 0:
                return None

            # ── SPREAD / TICK ─────────────────────────────────────
            bb = self.ws.get_best_bid(symbol)
            ba = self.ws.get_best_ask(symbol)
            if bb <= 0 or ba <= 0:
                return None

            tick = ba - bb
            if tick <= 0:
                tick = bb * 0.00001

            # ── ADAPTIF DELAY ─────────────────────────────────────
            # Yüksek volatilite → daha sık reprice (agresif)
            # Düşük volatilite → bekle (pasif)
            if atr_pct > 0.002:
                reprice_delay = 0.1   # 100ms — yüksek vol
            elif atr_pct > 0.001:
                reprice_delay = 0.15  # 150ms — normal
            else:
                reprice_delay = 0.25  # 250ms — düşük vol / pasif

            # ── DYNAMIC REPRICING LOOP ───────────────────────────
            t_order_sent = None
            for attempt in range(MAX_REPRICING_ATTEMPTS):
                # Taze fiyat (WebSocket cache — 0ms latency)
                if side == 'buy':
                    price = self.ws.get_best_bid(symbol)
                else:
                    price = self.ws.get_best_ask(symbol)

                if price <= 0:
                    return None

                # Chase: her denemede 1 tick yaklaş (maker olarak)
                if attempt > 0:
                    if side == 'buy':
                        price += tick * attempt
                    else:
                        price -= tick * attempt

                price = float(self.exchange.price_to_precision(symbol, price))
                t_order_sent = time.time()

                try:
                    order = await self.exchange.create_order(
                        symbol, 'limit', side, amount, price,
                        params={'postOnly': True, 'timeInForce': 'GTX'}
                    )
                except Exception as e:
                    err = str(e)
                    # Post-Only reject → hemen reprice (taker olurdu)
                    if (
                        '-2015' in err or '-4131' in err or
                        'would immediately' in err.lower() or
                        'PostOnly' in err
                    ):
                        await asyncio.sleep(reprice_delay)
                        continue
                    print(f"[EXEC] {symbol} order err: {e}")
                    return None

                # ── FILL BEKLE ──────────────────────────────────
                filled = await self._wait_fill(
                    symbol, order['id'],
                    timeout=POST_ONLY_TIMEOUT
                )
                if filled:
                    t_fill = time.time()
                    avg_price = float(filled.get('average') or filled.get('price') or price)
                    is_maker = filled.get('fee', {}).get('type', '') == 'maker'

                    # Debug log
                    if self.debug:
                        self.debug.log_execution(
                            symbol, side,
                            signal_time=t_signal,
                            order_sent_time=t_order_sent,
                            fill_time=t_fill,
                            fill_price=avg_price,
                            attempt=attempt + 1,
                            is_maker=is_maker,
                        )

                    print(
                        f"[FILL] {symbol} {side.upper()} @ {avg_price:.5f} | "
                        f"{int((t_fill-t_signal)*1000)}ms | "
                        f"try#{attempt+1} | {'MAKER' if is_maker else 'TAKER'}"
                    )
                    return filled

                # Dolmadı → iptal + reprice
                await self._cancel_safe(symbol, order['id'])
                await asyncio.sleep(reprice_delay)

            # MAX_REPRICING_ATTEMPTS tükendi → None döndür (market fallback yok giriş için)
            print(f"[EXEC] {symbol} max reprice tükendi, sinyal atlandı.")
            return None

        except Exception as e:
            print(f"[EXEC ERROR] {symbol}: {e}")
            return None

    async def place_close(self, symbol: str, side: str, amount: float) -> bool:
        """
        Çıkış stratejisi:
        1. Post-Only dene (0.8s timeout)
        2. Dolmazsa → Limit IOC (0 tick agresif)
        3. Son çare → Market (acil, taker fee)
        """
        try:
            close_side = 'sell' if side == 'buy' else 'buy'
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            if amount <= 0:
                return False

            # ── 1. POST-ONLY ÇIKIŞ ──────────────────────────────
            try:
                if close_side == 'sell':
                    price = self.ws.get_best_ask(symbol)  # ask'a yap → maker
                else:
                    price = self.ws.get_best_bid(symbol)  # bid'e yap → maker

                if price > 0:
                    price = float(self.exchange.price_to_precision(symbol, price))
                    order = await self.exchange.create_order(
                        symbol, 'limit', close_side, amount, price,
                        params={
                            'postOnly': True,
                            'reduceOnly': True,
                            'timeInForce': 'GTX'
                        }
                    )
                    filled = await self._wait_fill(symbol, order['id'], timeout=0.8)
                    if filled:
                        print(f"[CLOSE] {symbol} maker çıkış OK @ {price:.5f}")
                        return True
                    await self._cancel_safe(symbol, order['id'])
            except Exception:
                pass

            # ── 2. LİMİT IOC (1 tick agresif) ──────────────────
            try:
                bb = self.ws.get_best_bid(symbol)
                ba = self.ws.get_best_ask(symbol)
                tick = (ba - bb) if ba > bb else bb * 0.00001

                if close_side == 'sell':
                    ioc_price = ba - tick  # ask içine gir → hızlı fill
                else:
                    ioc_price = bb + tick

                ioc_price = float(self.exchange.price_to_precision(symbol, ioc_price))
                order = await self.exchange.create_order(
                    symbol, 'limit', close_side, amount, ioc_price,
                    params={'timeInForce': 'IOC', 'reduceOnly': True}
                )
                filled = await self._wait_fill(symbol, order['id'], timeout=0.5)
                if filled:
                    print(f"[CLOSE] {symbol} IOC çıkış OK @ {ioc_price:.5f}")
                    return True
            except Exception:
                pass

            # ── 3. MARKET FALLBACK (acil) ────────────────────────
            print(f"[CLOSE] {symbol} market fallback (TAKER)")
            await self.exchange.create_order(
                symbol, 'market', close_side, amount,
                params={'reduceOnly': True}
            )
            return True

        except Exception as e:
            print(f"[EXEC CLOSE ERROR] {symbol}: {e}")
            return False

    async def _wait_fill(self, symbol: str, order_id: str, timeout: float = None) -> dict | None:
        """Emir fill olana kadar poll et (WebSocket fill event yok, REST poll)."""
        if timeout is None:
            timeout = POST_ONLY_TIMEOUT
        poll_interval = 0.15  # 150ms poll
        checks = max(2, int(timeout / poll_interval))
        for _ in range(checks):
            await asyncio.sleep(poll_interval)
            try:
                o = await self.exchange.fetch_order(order_id, symbol)
                if o['status'] == 'closed':
                    return o
                if o['status'] in ('canceled', 'rejected', 'expired'):
                    return None
            except Exception:
                continue
        return None

    async def _cancel_safe(self, symbol: str, order_id: str):
        try:
            await self.exchange.cancel_order(order_id, symbol)
        except Exception:
            pass
