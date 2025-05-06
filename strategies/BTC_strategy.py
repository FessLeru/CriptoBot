"""
Стратегия для торговли BTC, основанная на индикаторах FRAMA, STC и VFI.
Включает фиксированный стоп-лосс и трейлинг-стоп.
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
import math
from datetime import datetime
from strategies import Strategy

class BTCStrategy(Strategy):
    """
    Стратегия для торговли BTC/USDT на основе FRAMA + STC + VFI.
    """
    def __init__(self, exchange, trade_direction="both"):
        """
        Инициализация стратегии для BTC.
        
        Args:
            exchange: Объект биржи для работы с API
            trade_direction: Направление торговли ("long", "short", "both")
        """
        super().__init__(symbol="BTC/USDT", timeframe="1m", exchange=exchange)
        
        # Параметры стратегии на основе Pine Script
        self.frama_length = 12
        self.stc_length = 23
        self.vfi_length = 120
        self.fixed_sl_pct = 0.6  # 0.6% фиксированный стоп-лосс
        self.trail_trigger_pct = 0.9  # 0.9% для активации трейлинг-стопа
        self.trail_step_pct = 0.3  # 0.3% шаг трейлинг-стопа
        self.trade_direction = trade_direction
        
    async def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитывает индикаторы FRAMA, STC и VFI.
        
        Args:
            df: DataFrame с OHLCV данными
            
        Returns:
            DataFrame с добавленными индикаторами
        """
        # Расчет FRAMA
        df['frama'] = self._calculate_frama(df, self.frama_length)
        
        # Расчет STC
        df['stc'] = self._calculate_stc(df, self.stc_length)
        
        # Расчет VFI
        df['vfi'] = self._calculate_vfi(df, self.vfi_length)
        
        return df
    
    async def check_entry_signals(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Проверяет наличие сигналов входа в позицию на основе индикаторов.
        
        Args:
            df: DataFrame с OHLCV данными и индикаторами
            
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        if len(df) < self.frama_length + 5:
            return None
        
        # Получаем последние данные
        current = df.iloc[-1]
        
        # Проверяем основные условия стратегии для LONG
        trend_long = current['close'] > current['frama']
        momentum_long = current['stc'] > 48
        volume_long = current['vfi'] > -0.15
        
        # Проверяем основные условия стратегии для SHORT
        trend_short = current['close'] < current['frama']
        momentum_short = current['stc'] < 52
        volume_short = current['vfi'] < 0.15
        
        # Формируем условия для входа
        long_condition = (
            trend_long and momentum_long and volume_long and 
            self.trade_direction in ["long", "both"]
        )
        
        short_condition = (
            trend_short and momentum_short and volume_short and 
            self.trade_direction in ["short", "both"]
        )
        
        # Определяем сигналы
        signal = None
        
        # Расчет стоп-лосса и трейлинг-стопа в пунктах на основе процентов
        entry_price = current['close']
        sl_long_points = entry_price * self.fixed_sl_pct / 100
        sl_short_points = entry_price * self.fixed_sl_pct / 100
        
        trail_trigger_points = entry_price * self.trail_trigger_pct / 100
        trail_step_points = entry_price * self.trail_step_pct / 100
        
        # Long сигнал
        if long_condition:
            stop_loss = entry_price - sl_long_points  # Фиксированный стоп-лосс для лонга
            
            signal = {
                "type": "buy",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,
                "trail_offset": trail_step_points,
                "trail_mode": True
            }
        
        # Short сигнал
        elif short_condition:
            stop_loss = entry_price + sl_short_points  # Фиксированный стоп-лосс для шорта
            
            signal = {
                "type": "sell",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,
                "trail_offset": trail_step_points,
                "trail_mode": True
            }
        
        return signal
    
    def _calculate_frama(self, df: pd.DataFrame, length: int) -> pd.Series:
        """Реализация FRAMA (Fractal Adaptive Moving Average)"""
        price = df['close']
        high = df['high']
        low = df['low']
        
        frama = pd.Series(index=df.index)
        
        # Инициализируем первое значение
        frama.iloc[length-1] = price.iloc[length-1]
        
        for i in range(length, len(price)):
            # Расчет высшей и низшей цены за период
            high1 = high.iloc[i-length:i].max()
            low1 = low.iloc[i-length:i].min()
            n1 = (high1 - low1) / length
            
            # Расчет для половины периода с использованием средней цены
            mid = (high.iloc[i-length:i] + low.iloc[i-length:i]) / 2
            half_len = length // 2
            high2 = mid.iloc[-half_len:].max()
            low2 = mid.iloc[-half_len:].min()
            n2 = (high2 - low2) / half_len
            
            # Расчет фрактальной размерности
            d = 0
            if (n1 + n2) > 0:
                d = math.log(n1 + n2) / math.log(2)
            
            # Расчет alpha на основе фрактальной размерности
            alpha_raw = math.exp(-4.6 * (d - 1))
            alpha = max(0.01, min(1.0, alpha_raw))  # Ограничиваем alpha между 0.01 и 1
            
            # Расчет FRAMA с экспоненциальным сглаживанием
            frama.iloc[i] = alpha * price.iloc[i] + (1 - alpha) * frama.iloc[i-1]
        
        return frama
    
    def _calculate_stc(self, df: pd.DataFrame, length: int) -> pd.Series:
        """Реализация Schaff Trend Cycle"""
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        
        # Вычисляем стохастик на основе MACD
        stoch_k = 100 * (macd - macd.rolling(window=length).min()) / \
                (macd.rolling(window=length).max() - macd.rolling(window=length).min()).replace(0, 1)
        
        return stoch_k
    
    def _calculate_vfi(self, df: pd.DataFrame, length: int) -> pd.Series:
        """Реализация Volume Flow Indicator"""
        # Расчет изменения цены в логарифмическом виде
        close = df['close']
        delta = np.log(close / close.shift(1))
        
        # Расчет сырого значения VFI и ограничение выбросов
        vf_raw = delta * df['volume']
        
        # Ограничение выбросов (спайков) - не более 2x от 10-периодного SMA
        vf_sma = vf_raw.rolling(window=10).mean()
        vf_capped = pd.Series(index=df.index)
        
        for i in range(10, len(vf_raw)):
            cap_value = 2 * vf_sma.iloc[i]
            if abs(vf_raw.iloc[i]) > abs(cap_value):
                vf_capped.iloc[i] = cap_value if vf_raw.iloc[i] > 0 else -cap_value
            else:
                vf_capped.iloc[i] = vf_raw.iloc[i]
        
        # Применяем EMA к ограниченным значениям
        vfi = vf_capped.ewm(span=length, adjust=False).mean()
        
        return vfi 