# PREDATOR v4 — WEBSOCKET MANAGER (ELITE)
# Real-time orderbook + trade stream + OHLCV via ccxt.pro
# Spoofing, Absorption, Liquidity Pull Detection

import asyncio
import time
import numpy as np
from config import DELTA_WINDOW


class WebSocketManager:
    """Manages WebSocket feeds: orderbook, trades, OHLCV, and Advanced Orderflow."""

    def __init__(self, exchange):
        self.exchange = exchange
        self.orderbooks = {}
        self.imbalances = {}
        self.best_bids = {}
        self.best_asks = {}
        self.spreads = {}
        self.trade_buffer = {}
        self.volume_deltas = {}
        self.candles = {}
        
        # Elite Edge Trackers
        self.bid_liquidity_history = {}
        self.ask_liquidity_history = {}
        self.spoof_flags = {}
        self.pull_flags = {}
        self.absorption_flags = {}

        self._running = False
        self._tasks = []

    async def start(self, symbols: list):
        self._running = True
        for sym in symbols:
            self.trade_buffer[sym] = []
            self.bid_liquidity_history[sym] = []
            self.ask_liquidity_history[sym] = []
            self.spoof_flags[sym] = {'bid': False, 'ask': False}
            self.pull_flags[sym] = {'bid': False, 'ask': False}
            self.absorption_flags[sym] = {'bid': False, 'ask': False}
            
            self._tasks.append(asyncio.create_task(self._feed_orderbook(sym)))
            self._tasks.append(asyncio.create_task(self._feed_trades(sym)))
            self._tasks.append(asyncio.create_task(self._feed_ohlcv(sym)))
            
            # Binance'in bağlantı limitine (Rate Limit) takılmamak için 200ms bekle
            await asyncio.sleep(0.2) 
            
        print(f"[WS] {len(symbols)} sembol için {len(self._tasks)} WebSocket stream başlatıldı (ELITE MODE).")

    async def _feed_orderbook(self, symbol):
        while self._running:
            try:
                ob = await self.exchange.watch_order_book(symbol, limit=10)
                self.orderbooks[symbol] = ob
                if ob['bids'] and ob['asks']:
                    bb = ob['bids'][0][0]
                    ba = ob['asks'][0][0]
                    self.best_bids[symbol] = bb
                    self.best_asks[symbol] = ba
                    self.spreads[symbol] = (ba - bb) / bb if bb > 0 else 1.0
                    
                    bid_vol = sum(b[1] for b in ob['bids'][:5])
                    ask_vol = sum(a[1] for a in ob['asks'][:5])
                    total = bid_vol + ask_vol
                    self.imbalances[symbol] = bid_vol / total if total > 0 else 0.5

                    # --- Elite Edge Detection ---
                    # Track historical liquidity for spoof/pull detection
                    now = time.time()
                    self.bid_liquidity_history[symbol].append((now, bid_vol))
                    self.ask_liquidity_history[symbol].append((now, ask_vol))
                    
                    # Keep last 5 seconds
                    self.bid_liquidity_history[symbol] = [x for x in self.bid_liquidity_history[symbol] if now - x[0] <= 5]
                    self.ask_liquidity_history[symbol] = [x for x in self.ask_liquidity_history[symbol] if now - x[0] <= 5]

                    # Detect Spoofing (Large order appears then disappears without trade)
                    # Detect Liquidity Pull (Sudden drop in liquidity)
                    if len(self.bid_liquidity_history[symbol]) > 2:
                        prev_bid = self.bid_liquidity_history[symbol][-2][1]
                        if bid_vol < prev_bid * 0.5: # 50% drop
                            self.pull_flags[symbol]['bid'] = True
                        else:
                            self.pull_flags[symbol]['bid'] = False

                    if len(self.ask_liquidity_history[symbol]) > 2:
                        prev_ask = self.ask_liquidity_history[symbol][-2][1]
                        if ask_vol < prev_ask * 0.5: # 50% drop
                            self.pull_flags[symbol]['ask'] = True
                        else:
                            self.pull_flags[symbol]['ask'] = False

            except Exception as e:
                if 'closed' not in str(e).lower():
                    print(f"[WS OB] {symbol}: {e}")
                await asyncio.sleep(1)

    async def _feed_trades(self, symbol):
        while self._running:
            try:
                trades = await self.exchange.watch_trades(symbol)
                now = time.time()
                recent_buys = 0
                recent_sells = 0
                
                for t in trades:
                    side = t.get('side', 'buy')
                    amt = float(t.get('amount', 0))
                    px = float(t.get('price', 0))
                    vol = amt * px
                    
                    self.trade_buffer[symbol].append((now, side, amt, px))
                    
                    if side == 'buy':
                        recent_buys += vol
                    else:
                        recent_sells += vol

                cutoff = now - DELTA_WINDOW
                self.trade_buffer[symbol] = [
                    x for x in self.trade_buffer[symbol] if x[0] > cutoff
                ]
                buf = self.trade_buffer[symbol]
                
                if buf:
                    buy_v = sum(x[2] * x[3] for x in buf if x[1] == 'buy')
                    sell_v = sum(x[2] * x[3] for x in buf if x[1] == 'sell')
                    total = buy_v + sell_v
                    self.volume_deltas[symbol] = (buy_v - sell_v) / total if total > 0 else 0.0

                # --- Absorption Detection ---
                # Buy volume is high, but price is not going up -> Ask Absorption (Bearish)
                # Sell volume is high, but price is not going down -> Bid Absorption (Bullish)
                bb = self.best_bids.get(symbol, 0)
                ba = self.best_asks.get(symbol, 0)
                
                if len(buf) > 10 and bb > 0 and ba > 0:
                    if recent_sells > recent_buys * 2: # Heavy selling
                        # Price hasn't dropped much compared to 5 seconds ago
                        past_trades = [x for x in buf if now - x[0] > 3]
                        if past_trades:
                            past_px = past_trades[-1][3]
                            if bb >= past_px * 0.9998: # Price holding strong
                                self.absorption_flags[symbol]['bid'] = True # Bullish setup
                            else:
                                self.absorption_flags[symbol]['bid'] = False
                    
                    elif recent_buys > recent_sells * 2: # Heavy buying
                        past_trades = [x for x in buf if now - x[0] > 3]
                        if past_trades:
                            past_px = past_trades[-1][3]
                            if ba <= past_px * 1.0002: # Price not breaking out
                                self.absorption_flags[symbol]['ask'] = True # Bearish setup
                            else:
                                self.absorption_flags[symbol]['ask'] = False

            except Exception as e:
                if 'closed' not in str(e).lower():
                    print(f"[WS TRADE] {symbol}: {e}")
                await asyncio.sleep(1)

    async def _feed_ohlcv(self, symbol):
        while self._running:
            try:
                candles = await self.exchange.watch_ohlcv(symbol, '1m')
                self.candles[symbol] = list(candles[-100:])
            except Exception as e:
                if 'closed' not in str(e).lower():
                    print(f"[WS OHLCV] {symbol}: {e}")
                await asyncio.sleep(1)

    # --- DATA ACCESSORS ---
    def get_imbalance(self, s): return self.imbalances.get(s, 0.5)
    def get_volume_delta(self, s): return self.volume_deltas.get(s, 0.0)
    def get_best_bid(self, s): return self.best_bids.get(s, 0.0)
    def get_best_ask(self, s): return self.best_asks.get(s, 0.0)
    def get_spread(self, s): return self.spreads.get(s, 1.0)
    
    def get_absorption(self, s): return self.absorption_flags.get(s, {'bid': False, 'ask': False})
    def get_liquidity_pull(self, s): return self.pull_flags.get(s, {'bid': False, 'ask': False})

    def get_change_pct(self, s, window=60) -> float:
        """Belirli bir pencere içindeki % değişimi hesaplar (BTC Protector için)."""
        buf = self.trade_buffer.get(s, [])
        if not buf: return 0.0
        now = time.time()
        recent = [x for x in buf if now - x[0] <= window]
        if len(recent) < 2: return 0.0
        start_px = recent[0][3]
        end_px = recent[-1][3]
        return (end_px - start_px) / start_px if start_px > 0 else 0.0

    def get_tick_size(self, symbol) -> float:
        """Sembolün minimum fiyat adımını (tick) döner."""
        try:
            market = self.exchange.market(symbol)
            return float(market['precision']['price']) if 'precision' in market else 0.00001
        except:
            return 0.00001

    async def reconnect(self):
        """Bağlantıları tazele (Self-healing)."""
        print("[WS] Yeniden bağlanılıyor...")
        symbols = list(self.trade_buffer.keys())
        await self.close()
        self._tasks = []
        await self.start(symbols)

    def get_price(self, s):
        b, a = self.best_bids.get(s, 0), self.best_asks.get(s, 0)
        if b and a:
            return (b + a) / 2
        c = self.get_closes(s)
        return float(c[-1]) if len(c) > 0 else 0.0

    def get_closes(self, s):
        cd = self.candles.get(s, [])
        return np.array([c[4] for c in cd], dtype=float) if cd else np.array([])

    def get_atr(self, s, period=14):
        cd = self.candles.get(s, [])
        if len(cd) < period + 1:
            return 0.00001  # BURAYI 0.0 YERİNE 0.00001 YAPTIK
        recent = cd[-(period + 1):]
        h = np.array([c[2] for c in recent])
        l = np.array([c[3] for c in recent])
        c = np.array([c[4] for c in recent])
        tr = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - c[:-1]),
                                   np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr))

    async def close(self):
        """Tüm taskları güvenli bir şekilde öldür ve bağlantıyı kapat."""
        self._running = False
        
        # 1. Bekleyen tüm görevleri iptal et (Zombileri öldür)
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # 2. Görevlerin kapanmasını bekle
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            
        self._tasks = [] # Artık listeyi güvenle temizleyebiliriz
        
        # 3. Exchange bağlantısını kapat
        try:
            await self.exchange.close()
        except Exception:
            pass
