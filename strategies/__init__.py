"""
Модуль стратегий для торгового бота.
Содержит базовый класс Strategy и все доступные торговые стратегии.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any, Union
import pandas as pd
from datetime import datetime
import asyncio
import traceback
from bot_logging import logger, setup_strategy_logger

class Strategy(ABC):
    """
    Абстрактный базовый класс для всех торговых стратегий.
    Определяет общий интерфейс и базовую функциональность.
    """
    def __init__(self, symbol: str, timeframe: str, exchange: Any):
        """
        Инициализация стратегии.
        
        Args:
            symbol: Торговый символ (например, 'BTC/USDT')
            timeframe: Таймфрейм для стратегии (например, '15m', '1H')
            exchange: Объект биржи для работы с API
        """
        # Проверка и исправление формата символа (удаление суффикса :USDT если он есть)
        if ':USDT' in symbol:
            self.symbol = symbol.split(':')[0]  # Преобразуем BTC/USDT:USDT в BTC/USDT
            self.logger.warning(f"Символ {symbol} преобразован в {self.symbol} для совместимости с Bitget API")
        else:
            self.symbol = symbol
            
        self.timeframe = timeframe
        self.exchange = exchange
        self.name = self.__class__.__name__
        self.next_scan_time = None  # Время следующего сканирования для этой стратегии
        
        # Инициализация специального логгера для этой стратегии
        self.logger = setup_strategy_logger(self.name)
        self.logger.info(f"Стратегия {self.name} для {self.symbol} инициализирована (таймфрейм: {timeframe})")
        
    @abstractmethod
    async def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Рассчитывает все необходимые индикаторы для стратегии.
        
        Args:
            df: DataFrame с OHLCV данными
            
        Returns:
            DataFrame с добавленными индикаторами
        """
        pass
    
    @abstractmethod
    async def check_entry_signals(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Проверяет наличие сигналов для входа в позицию.
        
        Args:
            df: DataFrame с OHLCV данными и индикаторами
            
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        pass
    
    async def fetch_data(self) -> Optional[pd.DataFrame]:
        """
        Получает OHLCV данные с биржи и преобразует их в DataFrame.
        
        Returns:
            DataFrame с OHLCV данными или None в случае ошибки
        """
        try:
            self.logger.info(f"Получение OHLCV данных для {self.symbol} на таймфрейме {self.timeframe}")
            
            # Подготовка параметров для фьючерсного рынка
            params = {
                "instType": "swap",  # Указываем тип инструмента - фьючерсы
                "marginCoin": "USDT"  # Маржинальная валюта
            }
            
            # Получаем исторические данные с явными параметрами для фьючерсов
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol=self.symbol, 
                timeframe=self.timeframe, 
                limit=200,
                params=params
            )
            
            # Преобразуем данные в pandas DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            self.logger.info(f"Получено {len(df)} свечей для {self.symbol}")
            return df
        
        except Exception as e:
            self.logger.error(f"Ошибка при получении данных для {self.symbol} на таймфрейме {self.timeframe}: {e}")
            self.logger.error(traceback.format_exc())
            return None
    
    async def execute(self) -> Optional[Dict]:
        """
        Выполняет полный цикл анализа: получение данных, расчет индикаторов и проверка сигналов.
        
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        self.logger.info(f"Выполнение анализа для {self.symbol} на таймфрейме {self.timeframe}")
        
        df = await self.fetch_data()
        if df is None or len(df) < 10:  # Минимальное количество свечей для анализа
            self.logger.warning(f"Недостаточно данных для анализа {self.symbol}")
            return None
        
        df = await self.calculate_indicators(df)
        signal = await self.check_entry_signals(df)
        
        if signal:
            # Стандартизируем формат сигнала
            signal['strategy_name'] = self.name
            signal['symbol'] = self.symbol
            signal['timeframe'] = self.timeframe
            signal['timestamp'] = datetime.now()
            
            # Добавляем поля для совместимости с trader.open_trade
            if 'type' in signal and 'side' not in signal:
                # Преобразуем 'type' в 'side' для соответствия требованиям trader.open_trade
                signal['side'] = signal['type']
                
            # Добавляем поле tradeSide со значением 'open' по умолчанию
            if 'tradeSide' not in signal:
                signal['tradeSide'] = 'open'
            
            self.logger.info(f"Сгенерирован сигнал {signal.get('type', signal.get('side', 'Unknown'))} для {self.symbol} по цене {signal['price']:.4f}")
        else:
            self.logger.info(f"Сигналов для {self.symbol} не найдено")
        
        return signal
        
    def set_timeframe(self, new_timeframe: str) -> None:
        """
        Устанавливает новый таймфрейм для стратегии.
        
        Args:
            new_timeframe: Новое значение таймфрейма
        """
        old_timeframe = self.timeframe
        self.timeframe = new_timeframe
        self.next_scan_time = None  # Сбрасываем время следующего сканирования
        self.logger.info(f"Таймфрейм изменен: {old_timeframe} -> {new_timeframe}") 