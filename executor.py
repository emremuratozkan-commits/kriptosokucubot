# executor.py
import asyncio
import time

class Executor:
    def __init__(self, exchange, ws_manager, debug_logger=None):
        self.exchange = exchange
        self.ws = ws_manager
        self.debug = debug_logger

    async def place_entry(self, symbol: str, side: str, amount: float, atr_pct: float = 0.001):
        t_signal = time.time()
        try:
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            if amount <= 0: return None

            # 50ms ULTRA HIZLI RE-PRICING
            reprice_delay = 0.05 
            
            for attempt in range(4):
                # Anlık taze fiyatı al
                price = self.ws.get_best_bid(symbol) if side == 'buy' else self.ws.get_best_ask(symbol)
                if price <= 0: return None

                # Chase (Kovala): Her denemede 1 tick agresifleş
                tick = self.ws.get_tick_size(symbol)
                if attempt > 0:
                    price = (price + tick) if side == 'buy' else (price - tick)

                price = float(self.exchange.price_to_precision(symbol, price))
                
                try:
                    order = await self.exchange.create_order(
                        symbol, 'limit', side, amount, price,
                        params={'postOnly': True, 'timeInForce': 'GTX'}
                    )
                except Exception as e:
                    if 'PostOnly' in str(e) or 'would immediately' in str(e).lower():
                        await asyncio.sleep(reprice_delay)
                        continue
                    return None

                # 50ms polling ile fill bekle
                filled = await self._wait_fill_ultra_fast(symbol, order['id'], timeout=0.6)
                if filled:
                    print(f"[EXEC] {symbol} {side.upper()} GİRİŞ BAŞARILI @ {price}")
                    return filled

                # Dolmadıysa iptal et, tekrar dene
                await self._cancel_safe(symbol, order['id'])
                await asyncio.sleep(reprice_delay)

            return None
        except Exception:
            return None

    async def place_close(self, symbol: str, side: str, amount: float) -> bool:
        """Çıkışta acımak yok. Kârı gördün mü al çık."""
        try:
            close_side = 'sell' if side == 'buy' else 'buy'
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            # Direkt IOC (Limit emri ama anında dolmazsa iptal olur, Taker gibi hızlıdır)
            bb = self.ws.get_best_bid(symbol)
            ba = self.ws.get_best_ask(symbol)
            tick = (ba - bb) if ba > bb else bb * 0.00001
            ioc_price = ba - tick if close_side == 'sell' else bb + tick
            ioc_price = float(self.exchange.price_to_precision(symbol, ioc_price))

            order = await self.exchange.create_order(
                symbol, 'limit', close_side, amount, ioc_price,
                params={'timeInForce': 'IOC', 'reduceOnly': True}
            )
            filled = await self._wait_fill_ultra_fast(symbol, order['id'], timeout=0.5)
            if filled: return True

            # IOC dolmazsa acil Market Exit
            await self.exchange.create_order(symbol, 'market', close_side, amount, params={'reduceOnly': True})
            return True
        except Exception:
            return False

    async def _wait_fill_ultra_fast(self, symbol: str, order_id: str, timeout: float):
        poll_interval = 0.05 
        for _ in range(int(timeout / poll_interval)):
            await asyncio.sleep(poll_interval)
            try:
                o = await self.exchange.fetch_order(order_id, symbol)
                if o['status'] == 'closed': return o
                if o['status'] in ('canceled', 'rejected'): return None
            except: continue
        return None

    async def _cancel_safe(self, symbol: str, order_id: str):
        try: await self.exchange.cancel_order(order_id, symbol)
        except: pass
