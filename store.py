# PREDATOR v3 — SUPABASE STORE
# Trade logs: open/close | PnL | Winrate | Signal quality

import asyncio
from config import SUPABASE_URL, SUPABASE_KEY


class Store:
    def __init__(self):
        self.client = None
        self.active = False
        try:
            from supabase import create_client
            self.client = create_client(SUPABASE_URL, SUPABASE_KEY)
            self.active = True
            print("[STORE] Supabase bağlı.")
        except Exception as e:
            print(f"[STORE] Supabase bağlantı hatası (bot devam eder): {e}")

    async def _run(self, fn):
        if not self.active:
            return
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, fn)
        except Exception as e:
            print(f"[STORE ERROR] {e}")

    async def log_trade_open(self, data: dict):
        def _do():
            self.client.table('predator_trades').insert(data).execute()
        await self._run(_do)

    async def log_trade_close(self, symbol: str, exit_reason: str, pnl: float, roi: float):
        def _do():
            try:
                res = self.client.table('predator_trades') \
                    .select('id') \
                    .eq('symbol', symbol) \
                    .eq('status', 'open') \
                    .order('created_at', desc=True) \
                    .limit(1).execute()
                if res.data:
                    self.client.table('predator_trades').update({
                        'status': 'closed',
                        'exit_reason': exit_reason,
                        'pnl_usdt': round(pnl, 4),
                        'roi_pct': round(roi * 100, 2),
                    }).eq('id', res.data[0]['id']).execute()
            except Exception as e:
                print(f"[STORE CLOSE] {e}")
        await self._run(_do)


store = Store()
