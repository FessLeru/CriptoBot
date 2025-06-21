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
import aiohttp
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
            logger.warning(f"Символ {symbol} преобразован в {self.symbol} для совместимости с Bitget API")
        else:
            self.symbol = symbol
            
        self.timeframe = timeframe
        self.exchange = exchange
        self.name = self.__class__.__name__
        self.next_scan_time = None  # Время следующего сканирования для этой стратегии
        
        # Добавляем поле для хранения предзагруженных данных
        self.preloaded_data = None
        self.is_preloaded = False
        
        # Инициализация специального логгера для этой стратегии
        self.logger = setup_strategy_logger(self.name)
        self.logger.info(f"Стратегия {self.name} для {self.symbol} инициализирована (таймфрейм: {timeframe})")
        
    def set_preloaded_data(self, data: pd.DataFrame) -> None:
        """
        Устанавливает предзагруженные исторические данные и рассчитывает индикаторы.
        
        Args:
            data: DataFrame с историческими данными OHLCV
        """
        if data is not None and not data.empty:
            self.preloaded_data = data
            self.is_preloaded = True
            self.logger.info(f"Установлены предзагруженные данные для {self.symbol}: "
                           f"{len(data)} свечей (с {data.index[0]} по {data.index[-1]})")
            
            # Примечание: индикаторы будут рассчитаны автоматически при первом запросе данных
            # через fetch_data или при выполнении стратегии через execute
            # Не нужно рассчитывать их здесь, так как это асинхронная операция
        else:
            self.logger.warning(f"Попытка установить пустые предзагруженные данные для {self.symbol}")
        
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
    
    async def fetch_data(self, limit: int = 100) -> Optional[pd.DataFrame]:
        """
        Получает OHLCV данные с биржи и преобразует их в DataFrame.
        Гарантирует получение данных независимо от типа инструмента.
        Использует предзагруженные данные, если они доступны.
        
        Args:
            limit: Количество запрашиваемых свечей (по умолчанию 100)
            
        Returns:
            DataFrame с OHLCV данными или None в случае ошибки
        """
        # Если есть предзагруженные данные, используем их
        if self.is_preloaded and self.preloaded_data is not None and len(self.preloaded_data) >= limit:
            self.logger.info(f"Использование предзагруженных данных для {self.symbol}: возвращаем {limit} из {len(self.preloaded_data)} свечей")
            
            # Проверяем, рассчитаны ли индикаторы для предзагруженных данных
            if self.symbol == "ETH/USDT":
                required_indicators = ['frama', 'adx', 'rsi', 'ema200']
            else:  # BTC/USDT и другие
                required_indicators = ['frama', 'stc', 'vfi']
            missing_indicators = [ind for ind in required_indicators if ind not in self.preloaded_data.columns]
            
            # Если индикаторы не рассчитаны, рассчитываем их
            if missing_indicators:
                self.logger.info(f"Расчет отсутствующих индикаторов для предзагруженных данных {self.symbol}: {', '.join(missing_indicators)}")
                try:
                    # Рассчитываем индикаторы для предзагруженных данных
                    self.preloaded_data = await self.calculate_indicators(self.preloaded_data)
                    self.logger.info(f"Индикаторы успешно рассчитаны для {self.symbol}")
                except Exception as e:
                    self.logger.error(f"Ошибка при расчете индикаторов: {e}")
            
            return self.preloaded_data.iloc[-limit:]
        
        # Если предзагруженные данные отсутствуют или недостаточны, получаем данные с биржи
        try:
            self.logger.info(f"Получение {limit} OHLCV свечей для {self.symbol} на таймфрейме {self.timeframe}")
            
            # Ограничиваем limit до 1000 свечей (API ограничение Bitget)
            if limit > 1000:
                self.logger.warning(f"Запрошено слишком много свечей ({limit}), ограничиваем до 1000")
                limit = 1000
                
            # Получаем данные через стандартный метод биржи
            try:
                # Параметры для фьючерсного рынка
                params = {
                    "instType": "swap",  # Указываем тип инструмента - фьючерсы
                    "marginCoin": "USDT"  # Маржинальная валюта
                }
                
                # Получаем исторические данные с явными параметрами для фьючерсов
                ohlcv = await self.exchange.fetch_ohlcv(
                    symbol=self.symbol, 
                    timeframe=self.timeframe, 
                    limit=limit,
                    params=params
                )
                
                # Проверяем, получены ли данные
                if not ohlcv or len(ohlcv) == 0:
                    self.logger.warning(f"Не удалось получить OHLCV данные для {self.symbol} через стандартный метод, пробуем альтернативный")
                    raise Exception("Нет данных")
                    
                # Преобразуем данные в pandas DataFrame
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                
                # Если были предзагруженные данные, обновляем их новыми данными
                if self.is_preloaded and self.preloaded_data is not None:
                    self.logger.info(f"Объединение предзагруженных данных с новыми данными для {self.symbol}")
                    # Объединяем старые и новые данные, удаляя дубликаты
                    combined_df = pd.concat([self.preloaded_data, df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                    combined_df = combined_df.sort_index()
                    # Обновляем предзагруженные данные
                    self.preloaded_data = combined_df
                    # Используем объединенные данные
                    df = combined_df.iloc[-limit:] if len(combined_df) > limit else combined_df
                
                self.logger.info(f"Получено {len(df)} свечей для {self.symbol} (с {df.index[0]} по {df.index[-1]})")
                return df
            
            except Exception as e:
                self.logger.warning(f"Ошибка при получении данных через стандартный метод: {e}")
                
                # Если стандартный метод не сработал, используем альтернативный через Ticker API
                try:
                    self.logger.info(f"Попытка получения данных через альтернативный метод для {self.symbol}")
                    
                    # Преобразуем символ в формат, принимаемый API
                    api_symbol = self.symbol.replace("/", "")
                    
                    # Параметры для API запроса Bitget
                    params = {
                        "symbol": api_symbol,
                        "granularity": self.timeframe,
                        "limit": str(limit),
                        "productType": "USDT-FUTURES"  # Указываем тип продукта
                    }
                    
                    # URL для API запроса
                    url = "https://api.bitget.com/api/v2/mix/market/history-candles"
                    
                    # Выполняем HTTP запрос
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, params=params) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                if data.get('data'):
                                    # Получаем данные свечей
                                    ohlcv_data = data.get('data', [])
                                    
                                    # Преобразуем данные из формата Bitget API в стандартный OHLCV формат
                                    ohlcv = []
                                    for candle in ohlcv_data:
                                        timestamp = int(candle[0])
                                        open_price = float(candle[1])
                                        high = float(candle[2])
                                        low = float(candle[3])
                                        close = float(candle[4])
                                        volume = float(candle[5])
                                        ohlcv.append([timestamp, open_price, high, low, close, volume])
                                    
                                    self.logger.info(f"Успешно получено {len(ohlcv)} свечей для {self.symbol} через альтернативный метод")
                                    
                                    # Преобразуем данные в DataFrame
                                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                                    df.set_index('timestamp', inplace=True)
                                    
                                    self.logger.info(f"Получено {len(df)} свечей для {self.symbol} (с {df.index[0]} по {df.index[-1]})")
                                    return df
                                else:
                                    self.logger.warning(f"Ошибка в ответе API: {data}")
                            else:
                                self.logger.warning(f"Ошибка HTTP {response.status}: {await response.text()}")
                except Exception as alt_err:
                    self.logger.error(f"Ошибка при получении данных через альтернативный метод: {alt_err}")
                    self.logger.error(traceback.format_exc())
                
                # Если все методы не сработали, используем метод from ticker price
                try:
                    self.logger.info(f"Попытка получения текущей цены через тикер для {self.symbol}")
                    
                    # Получаем текущую цену через ticker
                    ticker_data = await self.exchange.get_ticker_price(self.symbol)
                    current_price = ticker_data['mark']  # Используем mark price
                    
                    self.logger.info(f"Получена текущая цена через тикер: {current_price} для {self.symbol}")
                    
                    # Создаем синтетический DataFrame с одной свечой для текущей цены
                    # Используем текущую цену для всех значений OHLC
                    now = pd.Timestamp.now()
                    synthetic_df = pd.DataFrame([{
                        'timestamp': now,
                        'open': current_price,
                        'high': current_price,
                        'low': current_price,
                        'close': current_price,
                        'volume': 0
                    }])
                    synthetic_df.set_index('timestamp', inplace=True)
                    
                    self.logger.warning(f"Создан синтетический DataFrame с текущей ценой {current_price} для {self.symbol}")
                    return synthetic_df
                    
                except Exception as ticker_err:
                    self.logger.error(f"Ошибка при получении цены через тикер: {ticker_err}")
                    self.logger.error(traceback.format_exc())
                    
                self.logger.error(f"Все методы получения данных для {self.symbol} не сработали")
                return None
        
        except Exception as e:
            self.logger.error(f"Критическая ошибка при получении данных для {self.symbol} на таймфрейме {self.timeframe}: {e}")
            self.logger.error(traceback.format_exc())
            return None
    
    async def execute(self) -> Optional[Dict]:
        """
        Выполняет полный цикл анализа: получение данных, расчет индикаторов и проверка сигналов.
        
        Returns:
            Dict с информацией о сигнале или None, если сигнала нет
        """
        self.logger.info(f"Выполнение анализа для {self.symbol} на таймфрейме {self.timeframe}")
        
        # Получаем данные (100 свечей по умолчанию)
        df = await self.fetch_data(limit=100)
        if df is None:
            self.logger.error(f"Не удалось получить данные для {self.symbol}")
            return None
            
        if len(df) < 10:  # Минимальное количество свечей для анализа
            self.logger.warning(f"Недостаточно данных для анализа {self.symbol}: получено {len(df)}, требуется минимум 10")
            return None
        
        try:
            # Расчет индикаторов
            self.logger.info(f"Расчет индикаторов для {self.symbol} на {len(df)} свечах")
            df = await self.calculate_indicators(df)
            
            # Определяем необходимые индикаторы в зависимости от стратегии
            if self.symbol == "ETH/USDT":
                required_indicators = ['frama', 'adx', 'rsi', 'ema200']
            else:  # BTC/USDT и другие
                required_indicators = ['frama', 'stc', 'vfi']
                
            missing_indicators = [ind for ind in required_indicators if ind not in df.columns]
            
            if missing_indicators:
                self.logger.warning(f"Отсутствуют необходимые индикаторы для {self.symbol}: {', '.join(missing_indicators)}")
                return None
                
            # Проверка сигналов
            self.logger.info(f"Проверка сигналов для {self.symbol}")
            signal = await self.check_entry_signals(df)
            
            if signal:
                signal['strategy_name'] = self.name
                signal['symbol'] = self.symbol
                signal['timeframe'] = self.timeframe
                signal['timestamp'] = datetime.now()
                
                self.logger.info(f"Сгенерирован сигнал {signal.get('side', 'unknown')} {signal.get('type', 'unknown')} для {self.symbol} по цене {signal.get('price', 0):.4f}")
            else:
                self.logger.info(f"Сигналов для {self.symbol} не найдено")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении стратегии для {self.symbol}: {str(e)}")
            self.logger.error(traceback.format_exc())
            return None
    
    async def execute_with_conditions(self) -> Tuple[Optional[Dict], Optional[List[str]]]:
        """
        Выполняет полный цикл анализа и возвращает как сигнал, так и информацию о несоответствующих условиях.
        
        Returns:
            Tuple[Optional[Dict], Optional[List[str]]]: Сигнал и список несоответствующих условий
        """
        self.logger.info(f"Выполнение анализа с детализацией условий для {self.symbol} на таймфрейме {self.timeframe}")
        
        # Получаем данные (100 свечей по умолчанию)
        df = await self.fetch_data(limit=100)
        if df is None:
            self.logger.error(f"Не удалось получить данные для {self.symbol}")
            return None, ["Не удалось получить данные для анализа"]
            
        if len(df) < 10:  # Минимальное количество свечей для анализа
            self.logger.warning(f"Недостаточно данных для анализа {self.symbol}: получено {len(df)}, требуется минимум 10")
            return None, [f"Недостаточно данных для анализа: получено {len(df)}, требуется минимум 10"]
        
        try:
            # Расчет индикаторов
            self.logger.info(f"Расчет индикаторов для {self.symbol} на {len(df)} свечах")
            df = await self.calculate_indicators(df)
            
            # Определяем необходимые индикаторы в зависимости от стратегии
            if self.symbol == "ETH/USDT":
                required_indicators = ['frama', 'adx', 'rsi', 'ema200']
            else:  # BTC/USDT и другие
                required_indicators = ['frama', 'stc', 'vfi']
                
            missing_indicators = [ind for ind in required_indicators if ind not in df.columns]
            
            if missing_indicators:
                error_msg = f"Отсутствуют необходимые индикаторы: {', '.join(missing_indicators)}"
                self.logger.warning(f"{error_msg} для {self.symbol}")
                return None, [error_msg]
            
            # Получаем последние данные для проверки условий
            current = df.iloc[-1]
            
            # Список для хранения не выполненных условий
            failed_conditions = []
            
            # Проверяем условия в зависимости от стратегии
            if self.symbol == "ETH/USDT":
                # ETH стратегия: FRAMA + ADX + RSI + EMA200
                if hasattr(self, 'trade_direction') and self.trade_direction in ["long", "both"]:
                    # Проверка тренда (double confirmation)
                    if 'ema200' in df.columns and current['close'] <= current['ema200']:
                        failed_conditions.append(f"LONG: цена ниже EMA200 (close={current['close']:.2f} <= EMA200={current['ema200']:.2f})")
                    if 'frama' in df.columns and current['close'] <= current['frama']:
                        failed_conditions.append(f"LONG: цена ниже FRAMA (close={current['close']:.2f} <= FRAMA={current['frama']:.2f})")
                    
                    # Проверка RSI
                    if 'rsi' in df.columns and current['rsi'] <= 55:
                        failed_conditions.append(f"LONG: RSI недостаточный (RSI={current['rsi']:.2f} <= 55)")
                    
                    # Проверка ADX
                    if 'adx' in df.columns and current['adx'] <= 15:
                        failed_conditions.append(f"LONG: ADX слишком низкий (ADX={current['adx']:.2f} <= 15)")
                
                if hasattr(self, 'trade_direction') and self.trade_direction in ["short", "both"]:
                    # Проверка тренда (double confirmation)
                    if 'ema200' in df.columns and current['close'] >= current['ema200']:
                        failed_conditions.append(f"SHORT: цена выше EMA200 (close={current['close']:.2f} >= EMA200={current['ema200']:.2f})")
                    if 'frama' in df.columns and current['close'] >= current['frama']:
                        failed_conditions.append(f"SHORT: цена выше FRAMA (close={current['close']:.2f} >= FRAMA={current['frama']:.2f})")
                    
                    # Проверка RSI
                    if 'rsi' in df.columns and current['rsi'] >= 45:
                        failed_conditions.append(f"SHORT: RSI недостаточный (RSI={current['rsi']:.2f} >= 45)")
                    
                    # Проверка ADX
                    if 'adx' in df.columns and current['adx'] <= 15:
                        failed_conditions.append(f"SHORT: ADX слишком низкий (ADX={current['adx']:.2f} <= 15)")
            else:
                # BTC стратегия: FRAMA + STC + VFI
                if hasattr(self, 'trade_direction') and self.trade_direction in ["long", "both"]:
                    # Проверка тренда
                    if 'frama' in df.columns and current['close'] <= current['frama']:
                        failed_conditions.append(f"LONG: Нет восходящего тренда (close={current['close']:.2f} <= FRAMA={current['frama']:.2f})")
                    
                    # Проверка моментума
                    if 'stc' in df.columns and current['stc'] <= 48:
                        failed_conditions.append(f"LONG: Недостаточный моментум (STC={current['stc']:.2f} <= 48)")
                    
                    # Проверка объема
                    if 'vfi' in df.columns and current['vfi'] <= -0.15:
                        failed_conditions.append(f"LONG: Недостаточное подтверждение объемом (VFI={current['vfi']:.4f} <= -0.15)")
                
                if hasattr(self, 'trade_direction') and self.trade_direction in ["short", "both"]:
                    # Проверка тренда
                    if 'frama' in df.columns and current['close'] >= current['frama']:
                        failed_conditions.append(f"SHORT: Нет нисходящего тренда (close={current['close']:.2f} >= FRAMA={current['frama']:.2f})")
                    
                    # Проверка моментума
                    if 'stc' in df.columns and current['stc'] >= 52:
                        failed_conditions.append(f"SHORT: Недостаточный моментум (STC={current['stc']:.2f} >= 52)")
                    
                    # Проверка объема
                    if 'vfi' in df.columns and current['vfi'] >= 0.15:
                        failed_conditions.append(f"SHORT: Недостаточное подтверждение объемом (VFI={current['vfi']:.4f} >= 0.15)")
            
            # Проверяем trade_direction, если он определен
            if hasattr(self, 'trade_direction') and self.trade_direction not in ["long", "short", "both"]:
                failed_conditions.append(f"Некорректное направление торговли: {self.trade_direction}")
            
            # Проверяем сигналы через стандартный метод
            self.logger.info(f"Проверка сигналов для {self.symbol}")
            signal = await self.check_entry_signals(df)
            
            if signal:
                signal['strategy_name'] = self.name
                signal['symbol'] = self.symbol
                signal['timeframe'] = self.timeframe
                signal['timestamp'] = datetime.now()
                
                self.logger.info(f"Сгенерирован сигнал {signal.get('side', 'unknown')} {signal.get('type', 'unknown')} для {self.symbol} по цене {signal.get('price', 0):.4f}")
                return signal, None
            
            # Если сигнала нет и не обнаружены проблемы, но мы не смогли определить причину
            if not failed_conditions:
                failed_conditions.append("Условия не выполнены (другие условия стратегии не соответствуют требованиям)")
                
            return None, failed_conditions
            
        except Exception as e:
            error_msg = f"Ошибка при выполнении стратегии: {str(e)}"
            self.logger.error(f"{error_msg} для {self.symbol}")
            self.logger.error(traceback.format_exc())
            return None, [error_msg]
        
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