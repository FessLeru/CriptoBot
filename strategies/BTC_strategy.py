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
from config import TIMEFRAME_PARAMS

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
        super().__init__(symbol="BTC/USDT", timeframe="4h", exchange=exchange)
        
        # Параметры стратегии из конфигурации
        params = TIMEFRAME_PARAMS.get(self.timeframe, TIMEFRAME_PARAMS["4h"])
        
        self.frama_length = params["frama_length"]              # 12
        self.stc_length = params["stc_length"]                  # 23
        self.vfi_length = params["vfi_length"]                  # 120
        self.fixed_sl_pct = params["fixed_stop_percent"]        # 0.6%
        self.trail_trigger_pct = params["trail_trigger_percent"] # 0.5%
        self.trail_step_pct = params["trail_step_percent"]      # 0.3%
        self.trade_direction = trade_direction
        
    async def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитывает индикаторы FRAMA, STC и VFI.
        
        Args:
            df: DataFrame с OHLCV данными
            
        Returns:
            DataFrame с добавленными индикаторами
        """
        # Создаем явную копию DataFrame, чтобы избежать SettingWithCopyWarning
        df_copy = df.copy()
        
        # Расчет FRAMA
        df_copy.loc[:, 'frama'] = self._calculate_frama(df_copy, self.frama_length)
        
        # Расчет STC
        df_copy.loc[:, 'stc'] = self._calculate_stc(df_copy, self.stc_length)
        
        # Расчет VFI
        df_copy.loc[:, 'vfi'] = self._calculate_vfi(df_copy, self.vfi_length)
        
        return df_copy
    
    async def check_entry_signals(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Проверяет наличие сигналов входа в позицию на основе индикаторов.
        
        Args:
            df: DataFrame с OHLCV данными и индикаторами
            
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        if len(df) < self.frama_length + 5:
            self.logger.warning(f"Недостаточно данных для расчета индикаторов BTC: {len(df)} < {self.frama_length + 5}")
            return None
        
        # Получаем последние данные
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Логируем текущие значения индикаторов
        self.logger.info(f"BTC индикаторы: FRAMA={current['frama']:.2f}, STC={current['stc']:.2f}, VFI={current['vfi']:.4f}")
        self.logger.info(f"BTC цены: текущая={current['close']:.2f}, предыдущая={prev['close']:.2f}")
        
        # Проверяем основные условия стратегии для LONG
        trend_long = current['close'] > current['frama']
        momentum_long = current['stc'] > 48
        volume_long = current['vfi'] > -0.15
        
        # Проверяем основные условия стратегии для SHORT
        trend_short = current['close'] < current['frama']
        momentum_short = current['stc'] < 52
        volume_short = current['vfi'] < 0.15
        
        # Логируем состояние условий для LONG
        self.logger.info(f"BTC LONG условия: тренд={trend_long} (close > FRAMA), момент={momentum_long} (STC > 48), объем={volume_long} (VFI > -0.15)")
        
        # Логируем состояние условий для SHORT
        self.logger.info(f"BTC SHORT условия: тренд={trend_short} (close < FRAMA), момент={momentum_short} (STC < 52), объем={volume_short} (VFI < 0.15)")
        
        # Формируем условия для входа
        long_condition = (
            trend_long and momentum_long and volume_long and 
            self.trade_direction in ["long", "both"]
        )
        
        short_condition = (
            trend_short and momentum_short and volume_short and 
            self.trade_direction in ["short", "both"]
        )
        
        # Проверяем trade_direction
        if self.trade_direction not in ["long", "short", "both"]:
            self.logger.warning(f"BTC: неверный trade_direction: {self.trade_direction}")
        
        # Определяем сигналы
        signal = None
        
        # Расчет стоп-лосса и трейлинг-стопа в абсолютных значениях цены на основе процентов
        entry_price = current['close']
        sl_points = entry_price * self.fixed_sl_pct / 100  # Абсолютное значение для стоп-лосса
        
        # Абсолютные значения для трейлинг-стопа (не проценты)
        trail_trigger_points = entry_price * self.trail_trigger_pct / 100  # Расстояние до активации в абс. значении
        trail_step_points = entry_price * self.trail_step_pct / 100  # Шаг трейлинга в абс. значении
        
        # Long сигнал
        if long_condition:
            stop_loss = entry_price - sl_points  # Фиксированный стоп-лосс для лонга
            
            self.logger.info(f"LONG сигнал по {self.symbol}: entryPrice={entry_price}, stopLoss={stop_loss}, " +
                          f"trail_trigger={trail_trigger_points} (абс), trail_step={trail_step_points} (абс)")
            
            signal = {
                "symbol": self.symbol,
                "side": "buy",
                "tradeSide": "open",
                "type": "market",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,  # Абсолютное значение для активации
                "trail_offset": trail_step_points,     # Абсолютное значение для шага
                "trail_mode": True,
                "strategy_name": "BTCStrategy",
                "timeframe": self.timeframe
            }
        # Short сигнал
        elif short_condition:
            stop_loss = entry_price + sl_points  # Фиксированный стоп-лосс для шорта
            
            self.logger.info(f"SHORT сигнал по {self.symbol}: entryPrice={entry_price}, stopLoss={stop_loss}, " +
                          f"trail_trigger={trail_trigger_points} (абс), trail_step={trail_step_points} (абс)")
            
            signal = {
                "symbol": self.symbol,
                "side": "sell",
                "tradeSide": "open",
                "type": "market",
                "price": entry_price,
                "stop_loss": stop_loss,
                "trail_points": trail_trigger_points,  # Абсолютное значение для активации
                "trail_offset": trail_step_points,     # Абсолютное значение для шага
                "trail_mode": True,
                "strategy_name": "BTCStrategy",
                "timeframe": self.timeframe
            }
        else:
            # Логируем почему сигнал не был сгенерирован с более детальной информацией
            detailed_reasons = []
            
            # Проверяем условия для LONG
            if self.trade_direction in ["long", "both"]:
                if not trend_long:
                    detailed_reasons.append(f"LONG тренд отсутствует: close={current['close']:.2f} <= FRAMA={current['frama']:.2f}, разница: {(current['frama'] - current['close']):.2f}")
                if not momentum_long:
                    detailed_reasons.append(f"LONG момент недостаточен: STC={current['stc']:.2f} <= 48, требуется увеличение на {(48 - current['stc']):.2f}")
                if not volume_long:
                    detailed_reasons.append(f"LONG объем недостаточен: VFI={current['vfi']:.4f} <= -0.15, требуется увеличение на {(-0.15 - current['vfi']):.4f}")
            
            # Проверяем условия для SHORT
            if self.trade_direction in ["short", "both"]:
                if not trend_short:
                    detailed_reasons.append(f"SHORT тренд отсутствует: close={current['close']:.2f} >= FRAMA={current['frama']:.2f}, разница: {(current['close'] - current['frama']):.2f}")
                if not momentum_short:
                    detailed_reasons.append(f"SHORT момент недостаточен: STC={current['stc']:.2f} >= 52, требуется уменьшение на {(current['stc'] - 52):.2f}")
                if not volume_short:
                    detailed_reasons.append(f"SHORT объем недостаточен: VFI={current['vfi']:.4f} >= 0.15, требуется уменьшение на {(current['vfi'] - 0.15):.4f}")
            
            # Логируем все причины
            if detailed_reasons:
                detailed_log = "\n   - " + "\n   - ".join(detailed_reasons)
                self.logger.info(f"BTC: Сигнал не сгенерирован. Причины:{detailed_log}")
            elif self.trade_direction not in ["long", "short", "both"]:
                self.logger.warning(f"BTC: Сигнал не сгенерирован: неверное направление торговли: {self.trade_direction}")
            else:
                self.logger.info(f"BTC: Сигнал не сгенерирован: условия не выполнены (неизвестная причина)")
        
        return signal
    
    def _calculate_frama(self, df: pd.DataFrame, length: int) -> pd.Series:
        """
        Реализация FRAMA (Fractal Adaptive Moving Average) точно как в Pine Script
        
        Args:
            df: DataFrame с данными OHLCV
            length: Период для расчета
            
        Returns:
            pd.Series: Значения FRAMA
        """
        price = df['close']
        high = df['high']
        low = df['low']
        
        frama = pd.Series(index=df.index, dtype=float)
        
        # Инициализируем первое значение первой доступной ценой закрытия
        # (в Pine Script: frama_val := na(frama_val[1]) ? src : frama_val[1]...)
        frama.iloc[0] = price.iloc[0]
        
        for i in range(length, len(price)):
            # Расчет высшей и низшей цены за период (n1) - точно как в Pine Script
            high1 = high.iloc[i-length:i].max()
            low1 = low.iloc[i-length:i].min()
            n1 = (high1 - low1) / length
            
            # Расчет для половины периода (n2) - точно как в Pine Script
            half_len = length // 2
            
            # Рассчитываем mid = (high + low) / 2, как в Pine Script
            mid = (high.iloc[i-length:i] + low.iloc[i-length:i]) / 2
            
            # Используем mid для расчета high2 и low2, как в оригинальном Pine Script:
            # mid = (high + low) / 2
            # high2 = highest(mid, half_len)
            # low2 = lowest(mid, half_len)
            high2 = mid.tail(half_len).max()  # highest(mid, half_len)
            low2 = mid.tail(half_len).min()   # lowest(mid, half_len)
            
            n2 = (high2 - low2) / half_len
            
            # Расчет фрактальной размерности (d) - точно как в Pine Script
            # d = log(n1 + n2) / log(2)
            d = 0
            if (n1 + n2) > 0:
                d = math.log(n1 + n2) / math.log(2)
            
            # Расчет alpha на основе фрактальной размерности - точно как в Pine Script
            # alpha = exp(-4.6 * (d - 1))
            alpha = math.exp(-4.6 * (d - 1))
            alpha = max(0.01, min(1.0, alpha))  # Ограничиваем alpha между 0.01 и 1.0
            
            # Расчет FRAMA с экспоненциальным сглаживанием - точно как в Pine Script
            # frama = alpha * src + (1 - alpha) * frama[1]
            prev_frama = frama.iloc[i-1] if not pd.isna(frama.iloc[i-1]) else price.iloc[i]
            frama.iloc[i] = alpha * price.iloc[i] + (1 - alpha) * prev_frama
        
        return frama
    
    def _calculate_stc(self, df: pd.DataFrame, length: int) -> pd.Series:
        """Реализация Schaff Trend Cycle"""
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        
        # Вычисляем стохастик на основе MACD
        macd_min = macd.rolling(window=length).min()
        macd_max = macd.rolling(window=length).max()
        macd_range = macd_max - macd_min
        
        # Избегаем деления на ноль, используя маску
        stoch_k = pd.Series(index=df.index, dtype=float)
        mask = macd_range != 0
        stoch_k[mask] = 100 * (macd[mask] - macd_min[mask]) / macd_range[mask]
        stoch_k[~mask] = 50  # Нейтральное значение при отсутствии диапазона
        
        return stoch_k
    
    def _calculate_vfi(self, df: pd.DataFrame, length: int) -> pd.Series:
        """Реализация Volume Flow Indicator"""
        # Расчет изменения цены в логарифмическом виде
        close = df['close']
        delta = np.log(close / close.shift(1))
        
        # Расчет сырого значения VFI
        vf_raw = delta * df['volume']
        
        # Ограничение выбросов (спайков) - не более 2x от 10-периодного SMA
        vf_sma = vf_raw.rolling(window=10).mean()
        vf_capped = pd.Series(index=df.index)
        
        for i in range(10, len(vf_raw)):
            cap_value = 2 * vf_sma.iloc[i]
            if vf_raw.iloc[i] > cap_value:  # Только ограничиваем сверху
                vf_capped.iloc[i] = cap_value
            else:
                vf_capped.iloc[i] = vf_raw.iloc[i]
        
        # Применяем EMA к ограниченным значениям
        vfi = vf_capped.ewm(span=length, adjust=False).mean()
        
        return vfi 