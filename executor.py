import asyncio
import time

class Executor:
    def __init__(self, exchange, ws_manager, debug_logger=None):
        self.exchange = exchange
        self.ws = ws_manager
        self.debug = debug_logger

    async def place_entry(self, symbol: str, side: str, amount: float, atr_pct: float = 0.001):
        try:
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            if amount <= 0: return None

            reprice_delay = 0.1 # API spam'i önlemek için 50ms'den 100ms'ye çekildi
            
            for attempt in range(4):
                price = self.ws.get_best_bid(symbol) if side == 'buy' else self.ws.get_best_ask(symbol)
                if price <= 0: return None

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
                    # Sadece postOnly reddini atla, diğer kritik hataları (Bakiye, Limit) logla!
                    err_msg = str(e).lower()
                    if 'postonly' in err_msg or 'would immediately' in err_msg:
                        await asyncio.sleep(reprice_delay)
                        continue
                    else:
                        print(f"[EXEC ERROR] {symbol} Entry Hatası: {e}")
                        return None

                # Polling interval artırıldı (REST API Ban yememek için)
                filled = await self._wait_fill_ultra_fast(symbol, order['id'], timeout=0.8)
                if filled:
                    real_price = filled.get('average', filled.get('price', price))
                    print(f"[EXEC] {symbol} {side.upper()} GİRİŞ BAŞARILI @ {real_price}")
                    return filled

                await self._cancel_safe(symbol, order['id'])
                await asyncio.sleep(reprice_delay)

            return None
        except Exception as e:
            print(f"[EXEC FATAL] {symbol} {e}")
            return None

    async def place_close(self, symbol: str, side: str, amount: float) -> bool:
        try:
            close_side = 'sell' if side == 'buy' else 'buy'
            amount = float(self.exchange.amount_to_precision(symbol, amount))
            
            bb = self.ws.get_best_bid(symbol)
            ba = self.ws.get_best_ask(symbol)
            # +++ YENİ KODU YAPŞTIR (HFT Agresif Çaprazlama) +++
            if close_side == 'sell':
                # Alıcının %0.1 altına fırlat (Borsa zaten en iyi fiyattan satar, emrin iptal olmaz)
                ioc_price = bb * 0.999
            else:
                # Satıcının %0.1 üstüne fırlat
                ioc_price = ba * 1.001
            
            ioc_price = float(self.exchange.price_to_precision(symbol, ioc_price))

            try:
                order = await self.exchange.create_order(
                    symbol, 'limit', close_side, amount, ioc_price,
                    params={'timeInForce': 'IOC', 'reduceOnly': True}
                )
                filled = await self._wait_fill_ultra_fast(symbol, order['id'], timeout=0.5)
                if filled: return True
            except Exception as e:
                print(f"[EXEC] {symbol} IOC Çıkış Hatası: {e}")

            # IOC dolmazsa acil Market Exit ve GERÇEK FİYATI bekle (Telegram uyumsuzluğunu çözer)
            print(f"[EXEC] {symbol} IOC kaçtı, Market Exit atılıyor!")
            m_order = await self.exchange.create_order(symbol, 'market', close_side, amount, params={'reduceOnly': True})
            
            # Market emrinin borsada gerçekleştiğini teyit et
            m_filled = await self._wait_fill_ultra_fast(symbol, m_order['id'], timeout=1.0)
            if m_filled:
                real_exit = m_filled.get('average', m_filled.get('price', 'Bilinmiyor'))
                print(f"[EXEC] {symbol} MARKET ÇIKIŞI TEYİT EDİLDİ @ {real_exit}")
            
            return True
        except Exception as e:
            print(f"[EXEC CLOSE ERROR] {symbol} {e}")
            return False

    async def _wait_fill_ultra_fast(self, symbol: str, order_id: str, timeout: float):
        # 50ms Binance için intihardır. 200ms (0.2) ideal HFT REST limitidir.
        poll_interval = 0.2 
        for _ in range(int(timeout / poll_interval)):
            await asyncio.sleep(poll_interval)
            try:
                o = await self.exchange.fetch_order(order_id, symbol)
                if o['status'] == 'closed': return o
                if o['status'] in ('canceled', 'rejected'): return None
            except: 
                continue
        return None

    async def _cancel_safe(self, symbol: str, order_id: str):
        try: await self.exchange.cancel_order(order_id, symbol)
        except: pass
