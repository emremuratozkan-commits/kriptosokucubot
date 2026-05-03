# PREDATOR v4 — ELITE RISK MANAGER
# Daily loss limit, cooldown, overtrading protection, dynamic sizing

import time
from datetime import date
from collections import deque
from config import MAX_SLOTS, INITIAL_BALANCE, MAX_DAILY_LOSS_PCT, SYMBOL_COOLDOWN, LEVERAGE


class RiskManager:
    def __init__(self, balance: float = INITIAL_BALANCE):
        self.balance = balance
        self.peak_balance = balance
        self.daily_pnl = 0.0
        self.daily_reset_date = None
        self.cooldowns = {}
        
        # Overtrading & Drawdown Protection
        self.consecutive_losses = 0
        self.global_pause_until = 0.0
        self.trades_history = deque(maxlen=50) # To track trades per hour
        self.MAX_TRADES_PER_HOUR = 30
        self.RISK_PER_TRADE_PCT = 0.01  # 1% risk per trade

    def update_balance(self, new_balance: float):
        self.balance = new_balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance

    def record_pnl(self, pnl: float):
        self._check_daily_reset()
        self.daily_pnl += pnl
        self.trades_history.append(time.time())
        
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= 5:
                # 5 consecutive losses -> Pause trading for 5 minutes
                print("[RISK] 5 ardışık kayıp! Bot 5 dakika duraklatılıyor.")
                self.global_pause_until = time.time() + 300 
                self.consecutive_losses = 0
        else:
            self.consecutive_losses = 0

    def calc_position(self, price: float, sl_pct: float = None) -> dict:
        """
        Dinamik Pozisyon Boyutu:
        Risk / SL Mesafesi kuralını kullanır.
        Eğer hesaplanan boyut slot margin'den büyükse max leverage limitine takılır.
        """
        max_slot_margin = self.balance / MAX_SLOTS
        max_notional = max_slot_margin * LEVERAGE
        
        notional = max_notional
        
        if sl_pct is not None and sl_pct > 0:
            # Risk miktarı (Örn: 100$ kasa için 1$ risk)
            risk_amount = self.balance * self.RISK_PER_TRADE_PCT
            
            # Position Size = Risk Amount / SL Percentage
            # Notional = Position Size
            calc_notional = risk_amount / sl_pct
            
            # Sınırlandırma (Kasa / Slot kuralını aşma)
            notional = min(calc_notional, max_notional)
            
        if notional < 5.5:
            notional = 5.5
            
        amount = notional / price if price > 0 else 0
        margin = notional / LEVERAGE
        
        return {
            'margin': margin,
            'leverage': LEVERAGE,
            'notional': notional,
            'amount': amount,
        }

    def can_open(self, symbol: str, active_count: int) -> bool:
        if active_count >= MAX_SLOTS:
            return False
            
        if time.time() < self.global_pause_until:
            return False
            
        if self.is_daily_limit_hit():
            return False
            
        if self.is_on_cooldown(symbol):
            return False
            
        if self._trades_last_hour() >= self.MAX_TRADES_PER_HOUR:
            print("[RISK] Saatlik trade limitine ulaşıldı (Overtrading koruması).")
            # Set a 5-minute cooldown to prevent spam log
            self.global_pause_until = time.time() + 300
            return False
            
        return True

    def _trades_last_hour(self) -> int:
        now = time.time()
        one_hour_ago = now - 3600
        count = sum(1 for t in self.trades_history if t > one_hour_ago)
        return count

    def is_daily_limit_hit(self) -> bool:
        self._check_daily_reset()
        max_loss = self.balance * MAX_DAILY_LOSS_PCT
        return self.daily_pnl < -max_loss

    def is_on_cooldown(self, symbol: str) -> bool:
        return time.time() < self.cooldowns.get(symbol, 0)

    def set_cooldown(self, symbol: str):
        self.cooldowns[symbol] = time.time() + SYMBOL_COOLDOWN

    def drawdown_pct(self) -> float:
        if self.peak_balance == 0:
            return 0.0
        return (self.peak_balance - self.balance) / self.peak_balance

    def _check_daily_reset(self):
        today = date.today()
        if self.daily_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_reset_date = today
            self.consecutive_losses = 0
            self.global_pause_until = 0.0
