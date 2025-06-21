"""
Модуль для предварительной загрузки и подготовки исторических данных.
"""
import asyncio
import pandas as pd
from typing import Dict, Optional, Any
import traceback
from bot_logging import logger

class HistoricalDataLoader:
    """
    Класс для предзагрузки исторических данных для стратегий.
    Загружает данные более мелкого таймфрейма и агрегирует их в 45-минутные свечи.
    """
    
    def __init__(self, exchange):
        """
        Инициализация загрузчика данных.
        
        Args:
            exchange: Объект биржи для получения исторических данных
        """
        self.exchange = exchange
        self.cached_data = {}  # {symbol: DataFrame}
        logger.info("Инициализирован загрузчик исторических данных")
        
    async def preload_historical_data(self, symbol: str, base_timeframe: str = '15m', 
                                    target_minutes: int = 45, limit: int = 1000) -> Optional[pd.DataFrame]:
        """
        Предзагрузка и агрегация исторических данных.
        
        Args:
            symbol: Торговый символ (например, 'BTC/USDT')
            base_timeframe: Базовый таймфрейм для загрузки данных
            target_minutes: Целевой таймфрейм в минутах для агрегации (45 минут)
            limit: Количество свечей для загрузки
            
        Returns:
            DataFrame с агрегированными данными или None в случае ошибки
        """
        try:
            logger.info(f"Предзагрузка данных для {symbol} (базовый TF: {base_timeframe}, целевой: {target_minutes}m, лимит: {limit})")
            
            # Параметры для получения фьючерсных данных
            params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            
            # Загружаем данные мелкого таймфрейма
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=base_timeframe,
                limit=limit,
                params=params
            )
            
            if not ohlcv or len(ohlcv) < 10:
                logger.warning(f"Не удалось получить достаточно данных для {symbol}")
                return None
                
            # Преобразуем в DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Агрегируем в целевой таймфрейм (45 минут)
            df_resampled = df.resample(f'{target_minutes}min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            # Сохраняем в кеш
            self.cached_data[symbol] = df_resampled
            
            # Логируем информацию о загруженных данных
            logger.info(f"Успешно загружено и агрегировано {len(df_resampled)} свечей для {symbol} "
                       f"(с {df_resampled.index[0]} по {df_resampled.index[-1]})")
            
            # Выводим информацию о последних 3 свечах для проверки
            for idx, row in df_resampled.tail(3).iterrows():
                logger.info(f"Свеча {symbol} {idx:%Y-%m-%d %H:%M}: "
                          f"O={row['open']:.1f}, H={row['high']:.1f}, "
                          f"L={row['low']:.1f}, C={row['close']:.1f}, V={row['volume']:.1f}")
            
            return df_resampled
            
        except Exception as e:
            logger.error(f"Ошибка при предзагрузке данных для {symbol}: {e}")
            logger.error(traceback.format_exc())
            return None
    
    async def get_historical_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Получение предзагруженных исторических данных.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            DataFrame с данными или None если данные не загружены
        """
        if symbol in self.cached_data:
            return self.cached_data[symbol]
        else:
            logger.warning(f"Исторические данные для {symbol} не найдены в кеше")
            return None
    
    async def load_all_data(self, symbols: list, base_timeframe: str = '15m', 
                          target_minutes: int = 45, limit: int = 1000) -> Dict[str, pd.DataFrame]:
        """
        Загрузка исторических данных для списка символов.
        
        Args:
            symbols: Список торговых символов
            base_timeframe: Базовый таймфрейм для загрузки данных
            target_minutes: Целевой таймфрейм в минутах для агрегации
            limit: Количество свечей для загрузки
            
        Returns:
            Словарь {symbol: DataFrame} с загруженными данными
        """
        results = {}
        for symbol in symbols:
            df = await self.preload_historical_data(symbol, base_timeframe, target_minutes, limit)
            if df is not None:
                results[symbol] = df
                
        return results

    async def verify_indicators(self, symbol: str) -> Dict:
        """
        Проверяет, содержит ли предзагруженный DataFrame для символа необходимые индикаторы.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            Dict с результатами проверки
        """
        result = {
            "verified": False,
            "indicators_present": [],
            "indicators_missing": [],
            "message": ""
        }
        
        # Определяем необходимые индикаторы в зависимости от символа
        if symbol == "ETH/USDT":
            required_indicators = ['frama', 'adx', 'rsi', 'ema200']
        else:  # BTC/USDT и другие
            required_indicators = ['frama', 'stc', 'vfi']
        
        # Проверяем, есть ли данные для этого символа
        if symbol not in self.cached_data or self.cached_data[symbol] is None:
            result["message"] = f"Данные для {symbol} не найдены в кеше"
            return result
        
        df = self.cached_data[symbol]
        
        # Проверяем каждый индикатор
        for indicator in required_indicators:
            if indicator in df.columns:
                result["indicators_present"].append(indicator)
            else:
                result["indicators_missing"].append(indicator)
        
        # Проверяем результаты
        if not result["indicators_missing"]:
            result["verified"] = True
            result["message"] = f"Все необходимые индикаторы найдены в данных для {symbol}"
        else:
            result["message"] = f"Отсутствуют индикаторы для {symbol}: {', '.join(result['indicators_missing'])}"
        
        return result

# Пример использования
async def preload_data_for_trading(exchange, symbols=["BTC/USDT", "ETH/USDT"], base_timeframe="4h"):
    """
    Функция для предзагрузки данных для указанных символов.
    
    Args:
        exchange: Объект биржи
        symbols: Список символов для загрузки
        base_timeframe: Базовый таймфрейм для загрузки (например "4h", "1h", "30m")
        
    Returns:
        Dict[str, pd.DataFrame]: Словарь с загруженными данными
    """
    data_loader = HistoricalDataLoader(exchange)
    
    # Определяем целевой таймфрейм для агрегации на основе символов
    target_timeframes = {
        "BTC/USDT": 240,  # 4 часа в минутах
        "ETH/USDT": 240   # 4 часа в минутах
    }
    
    loaded_data = {}
    for symbol in symbols:
        target_minutes = target_timeframes.get(symbol, 240)  # По умолчанию 4 часа
        df = await data_loader.preload_historical_data(
            symbol=symbol, 
            base_timeframe=base_timeframe, 
            target_minutes=target_minutes
        )
        if df is not None:
            loaded_data[symbol] = df
    
    logger.info(f"Предзагрузка данных завершена для {len(loaded_data)} символов")
    return loaded_data, data_loader 