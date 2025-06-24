"""
Стратегия для торговли ETH на основе индикаторов FRAMA, ADX, RSI и EMA.
Универсальная стратегия с трейлинг-стопом и системой фильтрации.
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
import math
from strategies import Strategy
from config import ETH_CONFIG

class ETHStrategy(Strategy):
    """
    Стратегия для торговли ETH/USDT на основе FRAMA + ADX + RSI + EMA.
    Основана на Pine Script: Universal ETH Bot (FRAMA+ADX+RSI+Trailing) [Stable Engine v3]
    """
    def __init__(self, exchange, trade_direction="both"):
        """
        Инициализация стратегии для ETH.
        
        Args:
            exchange: Объект биржи для работы с API
            trade_direction: Направление торговли ("long", "short", "both")
        """
        super().__init__(symbol="ETH/USDT", timeframe="4h", exchange=exchange)
        
        # Параметры стратегии из конфигурации
        params = ETH_CONFIG.get(self.timeframe, ETH_CONFIG["4h"])
        
        self.frama_length = params["frama_length"]              # 14
        self.adx_length = params["adx_length"]                  # 14  
        self.rsi_length = params["rsi_length"]                  # 14
        self.ema_length = params["ema_length"]                  # 200
        self.stop_loss_percent = params["stop_loss_percent"]    # 1.0%
        self.trail_trigger_percent = params["trail_trigger_percent"]  # 1.5%
        self.trail_step_percent = params["trail_step_percent"]  # 0.7%
        self.adx_min = params["adx_min"]                        # 15
        self.rsi_entry_margin = params["rsi_entry_margin"]      # 5
        
        self.trade_direction = trade_direction
        
    async def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитывает индикаторы FRAMA, ADX, RSI и EMA.
        
        Args:
            df: DataFrame с OHLCV данными
            
        Returns:
            DataFrame с добавленными индикаторами
        """
        df_copy = df.copy()
        
        # Расчет FRAMA
        df_copy['frama'] = self._calculate_frama(df_copy, self.frama_length)
        
        # Расчет EMA 200
        df_copy['ema200'] = df_copy['close'].ewm(span=self.ema_length).mean()
        
        # Расчет RSI
        df_copy['rsi'] = self._calculate_rsi(df_copy, self.rsi_length)
        
        # Расчет ADX
        df_copy['adx'] = self._calculate_adx(df_copy, self.adx_length)
        
        return df_copy
    
    async def check_entry_signals(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Проверяет наличие сигналов входа в позицию на основе новых индикаторов.
        
        Args:
            df: DataFrame с OHLCV данными и индикаторами
            
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        if len(df) < max(self.frama_length, self.ema_length, self.rsi_length, self.adx_length) + 5:
            self.logger.warning(f"Недостаточно данных для расчета индикаторов ETH: {len(df)}")
            return None
        
        # Получаем последние данные
        current = df.iloc[-1]
        
        # Логируем текущие значения индикаторов
        self.logger.info(f"ETH индикаторы: FRAMA={current['frama']:.2f}, ADX={current['adx']:.2f}, "
                        f"RSI={current['rsi']:.2f}, EMA200={current['ema200']:.2f}")
        self.logger.info(f"ETH цена: {current['close']:.2f}")
        
        # Основные условия торговли
        can_trade = current['adx'] > self.adx_min
        price_above_frama = current['close'] > current['frama']
        price_below_frama = current['close'] < current['frama']
        
        # Условия для Long
        trend_long = current['close'] > current['ema200'] and price_above_frama
        rsi_long = current['rsi'] > (50 + self.rsi_entry_margin)  # RSI > 55
        
        # Условия для Short
        trend_short = current['close'] < current['ema200'] and price_below_frama
        rsi_short = current['rsi'] < (50 - self.rsi_entry_margin)  # RSI < 45
        
        # Логируем состояние условий
        self.logger.info(f"ETH условия: can_trade={can_trade} (ADX > {self.adx_min})")
        self.logger.info(f"ETH LONG: trend={trend_long} (close > EMA200 & FRAMA), RSI={rsi_long} (RSI > 55)")
        self.logger.info(f"ETH SHORT: trend={trend_short} (close < EMA200 & FRAMA), RSI={rsi_short} (RSI < 45)")
        
        # Условия входа
        long_condition = (
            can_trade and trend_long and rsi_long and
            self.trade_direction in ["long", "both"]
        )
        
        short_condition = (
            can_trade and trend_short and rsi_short and
            self.trade_direction in ["short", "both"]
        )
        
        # Расчет параметров сделки
        entry_price = current['close']
        sl_points = entry_price * self.stop_loss_percent / 100
        trail_trigger_points = entry_price * self.trail_trigger_percent / 100
        trail_step_points = entry_price * self.trail_step_percent / 100
        
        signal = None
        
        # Long сигнал
        if long_condition:
            stop_loss = entry_price - sl_points
            
            self.logger.info(f"LONG сигнал по {self.symbol}: entryPrice={entry_price}, stopLoss={stop_loss}, "
                           f"trail_trigger={trail_trigger_points}, trail_step={trail_step_points}")
            
            signal = {
                "symbol": self.symbol,
                "side": "buy",
                "tradeSide": "open",
                "type": "market",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,
                "trail_offset": trail_step_points,
                "trail_mode": True,
                "strategy_name": "ETHStrategy",
                "timeframe": self.timeframe
            }
        
        # Short сигнал
        elif short_condition:
            stop_loss = entry_price + sl_points
            
            self.logger.info(f"SHORT сигнал по {self.symbol}: entryPrice={entry_price}, stopLoss={stop_loss}, "
                           f"trail_trigger={trail_trigger_points}, trail_step={trail_step_points}")
            
            signal = {
                "symbol": self.symbol,
                "side": "sell",
                "tradeSide": "open",
                "type": "market",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,
                "trail_offset": trail_step_points,
                "trail_mode": True,
                "strategy_name": "ETHStrategy",
                "timeframe": self.timeframe
            }
        else:
            # Детальное логирование причин отсутствия сигнала
            reasons = []
            if not can_trade:
                reasons.append(f"ADX слишком низкий: {current['adx']:.2f} <= {self.adx_min}")
            
            if self.trade_direction in ["long", "both"]:
                if not trend_long:
                    if current['close'] <= current['ema200']:
                        reasons.append(f"LONG: цена ниже EMA200: {current['close']:.2f} <= {current['ema200']:.2f}")
                    if not price_above_frama:
                        reasons.append(f"LONG: цена ниже FRAMA: {current['close']:.2f} <= {current['frama']:.2f}")
                if not rsi_long:
                    reasons.append(f"LONG: RSI недостаточный: {current['rsi']:.2f} <= {50 + self.rsi_entry_margin}")
                    
            if self.trade_direction in ["short", "both"]:
                if not trend_short:
                    if current['close'] >= current['ema200']:
                        reasons.append(f"SHORT: цена выше EMA200: {current['close']:.2f} >= {current['ema200']:.2f}")
                    if not price_below_frama:
                        reasons.append(f"SHORT: цена выше FRAMA: {current['close']:.2f} >= {current['frama']:.2f}")
                if not rsi_short:
                    reasons.append(f"SHORT: RSI недостаточный: {current['rsi']:.2f} >= {50 - self.rsi_entry_margin}")
            
            if reasons:
                self.logger.info(f"ETH: Сигнал не сгенерирован. Причины: {'; '.join(reasons)}")
        
        return signal
    
    def _calculate_frama(self, df: pd.DataFrame, length: int) -> pd.Series:
        """
        Реализация FRAMA (Fractal Adaptive Moving Average) как в Pine Script.
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Инициализация результата
        frama = np.full(len(df), np.nan)
        
        for i in range(length, len(df)):
            # Расчет N1
            high1 = high.iloc[i-length+1:i+1].max()
            low1 = low.iloc[i-length+1:i+1].min()
            n1 = (high1 - low1) / length
            
            # Расчет N2
            mid_points = (high.iloc[i-length//2+1:i+1] + low.iloc[i-length//2+1:i+1]) / 2
            high2 = mid_points.max()
            low2 = mid_points.min()
            n2 = (high2 - low2) / (length // 2)
            
            # Расчет фрактальной размерности
            if n1 + n2 > 0:
                d = math.log(n1 + n2) / math.log(2)
            else:
                d = 0
                
            # Расчет alpha
            alpha_raw = math.exp(-4.6 * (d - 1))
            alpha = max(0.01, min(1.0, alpha_raw))
            
            # FRAMA
            if i == length:
                frama[i] = close.iloc[i]
            else:
                frama[i] = alpha * close.iloc[i] + (1 - alpha) * frama[i-1]
        
        return pd.Series(frama, index=df.index)
    
    def _calculate_rsi(self, df: pd.DataFrame, length: int) -> pd.Series:
        """
        Расчет RSI (Relative Strength Index).
        """
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_adx(self, df: pd.DataFrame, length: int) -> pd.Series:
        """
        Расчет ADX (Average Directional Index) как в Pine Script.
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Расчет True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Расчет Directional Movement
        up = high - high.shift(1)
        down = -(low - low.shift(1))
        
        plus_dm = np.where((up > down) & (up > 0), up, 0)
        minus_dm = np.where((down > up) & (down > 0), down, 0)
        
        # Сглаживание RMA (как ta.rma в Pine Script)
        plus_dm_series = pd.Series(plus_dm, index=df.index)
        minus_dm_series = pd.Series(minus_dm, index=df.index)
        
        trur = tr.ewm(alpha=1/length).mean()
        plus_di = 100 * plus_dm_series.ewm(alpha=1/length).mean() / trur
        minus_di = 100 * minus_dm_series.ewm(alpha=1/length).mean() / trur
        
        # Расчет DX
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        
        # Расчет ADX
        adx = dx.ewm(alpha=1/length).mean()
        
        return adx
    
 