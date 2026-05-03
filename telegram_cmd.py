# PREDATOR v3 — TELEGRAM CONTROL PANEL
# /start /stop /status /pnl /mode /latency

import asyncio
import aiohttp
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MAX_SLOTS


# ─── SEND HELPER ────────────────────────────────────────────────
async def send(text: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chats = TELEGRAM_CHAT_ID if isinstance(TELEGRAM_CHAT_ID, list) else [TELEGRAM_CHAT_ID]
    async with aiohttp.ClientSession() as session:
        for chat_id in chats:
            try:
                await session.post(url, json={
                    'chat_id': chat_id,
                    'text': text,
                    'parse_mode': 'HTML',
                })
            except Exception as e:
                print(f"[TG] Send error: {e}")


# ─── BOT ────────────────────────────────────────────────────────
class TelegramBot:
    def __init__(self, engine):
        self.engine = engine
        self.offset = 0
        self.running = True

    async def _get_real_balance(self):
        """Binance'ten gerçek zamanlı USDT (veya USDC) bakiyesini çeker."""
        try:
            balance = await self.engine.exchange.fetch_balance()
            # Genelde Futures cüzdanında USDT veya USDC tutulur
            usdt_total = balance.get('USDT', {}).get('total', 0.0)
            return usdt_total
        except Exception as e:
            print(f"[TG BALANCE ERROR] {e}")
            # Hata verirse lokal bakiyeye dön (fallback)
            return self.engine.risk.balance

    async def run(self):
        print("[TG] Telegram bot dinliyor...")
        while self.running:
            try:
                await self._poll()
            except Exception as e:
                print(f"[TG POLL ERROR] {e}")
            await asyncio.sleep(1)

    async def _poll(self):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        async with aiohttp.ClientSession() as session:
            resp = await session.get(url, params={
                'offset': self.offset,
                'timeout': 10,
                'allowed_updates': ['message'],
            })
            data = await resp.json()
        for upd in data.get('result', []):
            self.offset = upd['update_id'] + 1
            msg = upd.get('message', {})
            text = msg.get('text', '').strip()
            chat_id = str(msg.get('chat', {}).get('id', ''))
            if chat_id not in (TELEGRAM_CHAT_ID if isinstance(TELEGRAM_CHAT_ID, list) else [TELEGRAM_CHAT_ID]):
                continue
            await self._handle(text)

    async def _handle(self, text: str):
        e = self.engine
        cmd = text.lower().split()
        if not cmd:
            return

        # /start
        if cmd[0] == '/start':
            if not e.running:
                e.running = True
                asyncio.create_task(e.run())
                await send("✅ <b>PREDATOR v4 ELITE başlatıldı!</b>")
            else:
                await send("ℹ️ Bot zaten çalışıyor.")

        # /stop
        elif cmd[0] == '/stop':
            await e.stop()
            await send("⛔ <b>Bot durduruldu.</b>")

        # /status
        elif cmd[0] == '/status':
            real_balance = await self._get_real_balance()
            slots = e.active_slots
            if not slots:
                await send(f"📭 <b>Açık pozisyon yok.</b>\n💰 Bakiye: ${real_balance:.2f}")
                return
            lines = [f"📊 <b>Açık Pozisyonlar ({len(slots)}/{MAX_SLOTS})</b>"]
            for sym, p in slots.items():
                roi = p.get('current_roi', 0) * 100
                emoji = '🟢' if roi >= 0 else '🔴'
                lines.append(
                    f"\n{emoji} <b>{sym}</b> {p['side'].upper()}\n"
                    f"   Giriş: {p['entry']:.5f}\n"
                    f"   ROI: %{roi:.1f}\n"
                    f"   TP: {p['tp']:.5f} | SL: {p['sl']:.5f}"
                )
            lines.append(f"\n📡 Piyasa: {'🟢' if e.running else '🔴'}")
            lines.append(f"💰 Gerçek Bakiye: ${real_balance:.2f}")
            lines.append(f"📈 Günlük PnL: {e.risk.daily_pnl:+.2f}$")
            lines.append(f"⚡ Ort. Fill: {e.avg_latency_ms():.0f}ms")
            await send('\n'.join(lines))

        # /pnl
        elif cmd[0] == '/pnl':
            real_balance = await self._get_real_balance()
            t = e.stats['total']
            w = e.stats['wins']
            wr = (w / t * 100) if t > 0 else 0
            pnl = e.stats['pnl']
            await send(
                f"📈 <b>İstatistikler</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 Net PnL: <b>{pnl:+.3f} USDT</b>\n"
                f"📊 Winrate: %{wr:.1f} ({w}/{t})\n"
                f"💵 Gerçek Bakiye: ${real_balance:.2f}\n"
                f"📉 Günlük PnL: {e.risk.daily_pnl:+.2f}$\n"
                f"⚡ Ort. Fill: {e.avg_latency_ms():.0f}ms"
            )

        # /mode aggressive | safe
        elif cmd[0] == '/mode' and len(cmd) > 1:
            mode = cmd[1]
            e.signals.set_mode(mode)
            await send(f"⚙️ Mod değiştirildi: <b>{mode.upper()}</b>")

        # /latency
        elif cmd[0] == '/latency':
            avg = e.avg_latency_ms()
            recent = e.latency_log[-5:]
            lines = [f"⚡ <b>Execution Latency</b>", f"Ortalama: <b>{avg:.0f}ms</b>", ""]
            for x in recent:
                emoji = '🟢' if x['latency_ms'] < 200 else '🔴'
                lines.append(f"{emoji} {x['symbol']} {x['side'].upper()}: {x['latency_ms']}ms")
            await send('\n'.join(lines))

        # /debug
        elif cmd[0] == '/debug':
            if e.debug:
                await send(e.debug.full_report())
            else:
                await send("⚠️ Debug Logger aktif değil.")

        # /help
        else:
            await send(
                "🤖 <b>PREDATOR v4 ELITE Komutları</b>\n"
                "━━━━━━━━━━━━━━━\n"
                "/start — botu başlat\n"
                "/stop — botu durdur\n"
                "/status — açık pozisyonlar\n"
                "/pnl — istatistikler\n"
                "/mode aggressive|safe — mod değiştir\n"
                "/latency — fill hız raporu\n"
                "/debug — detaylı sistem hata ayıklama analizi"
            )
