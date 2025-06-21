"""
Сканер для выполнения стратегий и поиска сигналов.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import traceback

from bot_logging import logger
from trading.exchange import BitgetExchange
from strategies import Strategy
from utils.time_utils import wait_for_candle_close

class StrategyScanner:
    """Сканер для выполнения стратегий и поиска сигналов."""
    
    def __init__(self):
        """Инициализирует сканер стратегий."""
        self.strategies = {}  # {symbol: Strategy}
        self.active_tasks = {}  # {symbol: Task}
        self.running = False
        self.signal_callback = None
        self._lock = asyncio.Lock()
        
        logger.info("Инициализирован сканер стратегий")
    
    def add_strategy(self, strategy: Strategy) -> None:
        """
        Добавляет стратегию в список для сканирования.
        
        Args:
            strategy: Объект стратегии
        """
        symbol = strategy.symbol
        self.strategies[symbol] = strategy
        logger.info(f"Добавлена стратегия {strategy.name} для {symbol} (таймфрейм: {strategy.timeframe})")
    
    def register_signal_callback(self, callback: Callable) -> None:
        """
        Регистрирует функцию обратного вызова для обработки сигналов.
        
        Args:
            callback: Функция, которая будет вызвана при получении сигнала
        """
        self.signal_callback = callback
        logger.info("Зарегистрирован обработчик сигналов")
        
    async def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Сканирует указанный символ на наличие сигналов.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            Optional[Dict]: Словарь с информацией о сигнале или None
        """
        async with self._lock:
            if symbol not in self.strategies:
                logger.warning(f"Стратегия для {symbol} не найдена")
                return None
            
            try:
                strategy = self.strategies[symbol]
                
                # Используем execute_with_conditions вместо execute для получения информации о причинах отсутствия сигнала
                signal, failed_conditions = await strategy.execute_with_conditions()
                
                if signal:
                    logger.info(f"Найден сигнал для {symbol}: {signal.get('side', 'unknown')} {signal.get('type', 'unknown')} по цене {signal.get('price', 0):.4f}")
                    
                    # Вызываем функцию обратного вызова если она задана
                    if self.signal_callback:
                        await self.signal_callback(signal)
                    
                    return signal
                else:
                    # Логируем причины отсутствия сигнала
                    if failed_conditions:
                        # Форматируем причины для лучшей читаемости
                        reasons = "\n   - " + "\n   - ".join(failed_conditions)
                        logger.info(f"Сигналов для {symbol} не найдено. Причины:{reasons}")
                    else:
                        logger.info(f"Сигналов для {symbol} не найдено. Причина не определена.")
                    return None
                    
            except Exception as e:
                logger.error(f"Ошибка при сканировании {symbol}: {str(e)}")
                logger.error(traceback.format_exc())
                return None
    
    async def _continuous_scan(self, symbol: str) -> None:
        """
        Непрерывно сканирует указанный символ с учетом таймфрейма.
        
        Args:
            symbol: Торговый символ
        """
        if symbol not in self.strategies:
            logger.error(f"Непрерывное сканирование для {symbol} невозможно: стратегия не найдена")
            return
            
        strategy = self.strategies[symbol]
        logger.info(f"Запуск непрерывного сканирования для {symbol} (таймфрейм: {strategy.timeframe})")
        
        while self.running:
            try:
                # Ожидаем закрытия свечи + 1 секунда
                await wait_for_candle_close(strategy.timeframe)
                
                # Выполняем несколько сканирований с задержкой
                num_scans = 3  # Количество сканирований
                scan_delay = 5  # Задержка между сканированиями в секундах
                
                signal = None
                for scan_num in range(1, num_scans + 1):
                    # Сканируем символ
                    logger.info(f"Сканирование {scan_num}/{num_scans} для {symbol} на таймфрейме {strategy.timeframe} в {datetime.now().strftime('%H:%M:%S.%f')}")
                    signal = await self.scan_symbol(symbol)
                    
                    # Если сигнал найден или это последнее сканирование, завершаем цикл
                    if signal or scan_num == num_scans:
                        break
                    
                    # Если это не последнее сканирование, ждем перед следующим
                    if scan_num < num_scans:
                        logger.info(f"Ожидание {scan_delay} секунд перед следующим сканированием {symbol}")
                        await asyncio.sleep(scan_delay)
                
            except asyncio.CancelledError:
                logger.info(f"Сканирование {symbol} отменено")
                break
            except Exception as e:
                logger.error(f"Ошибка при непрерывном сканировании {symbol}: {str(e)}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(10)  # Пауза перед повторной попыткой
    
    async def start(self) -> None:
        """Запускает непрерывное сканирование для всех стратегий."""
        if self.running:
            logger.warning("Сканер уже запущен")
            return
            
        self.running = True
        logger.info("Запуск сканера стратегий")
        
        for symbol in self.strategies:
            self.active_tasks[symbol] = asyncio.create_task(
                self._continuous_scan(symbol)
            )
    
    async def stop(self) -> None:
        """Останавливает все задачи сканирования."""
        if not self.running:
            logger.warning("Сканер уже остановлен")
            return
            
        self.running = False
        logger.info("Остановка сканера стратегий")
        
        # Отменяем все активные задачи
        for symbol, task in self.active_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        self.active_tasks.clear()
        logger.info("Сканер стратегий остановлен")
        
    def set_timeframe(self, symbol: str, timeframe: str) -> bool:
        """
        Устанавливает новый таймфрейм для указанной стратегии.
        
        Args:
            symbol: Торговый символ
            timeframe: Новый таймфрейм
            
        Returns:
            bool: True если успешно, иначе False
        """
        if symbol not in self.strategies:
            logger.warning(f"Стратегия для {symbol} не найдена")
            return False
            
        try:
            # Получаем стратегию
            strategy = self.strategies[symbol]
            
            # Устанавливаем новый таймфрейм
            strategy.set_timeframe(timeframe)
            
            # Перезапускаем задачу сканирования если она активна
            if self.running and symbol in self.active_tasks:
                # Отменяем текущую задачу
                task = self.active_tasks[symbol]
                if not task.done():
                    task.cancel()
                    
                # Создаем новую задачу
                self.active_tasks[symbol] = asyncio.create_task(
                    self._continuous_scan(symbol)
                )
                
            logger.info(f"Таймфрейм для {symbol} изменен на {timeframe}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при изменении таймфрейма для {symbol}: {str(e)}")
            return False
            
    def get_strategies_info(self) -> List[Dict]:
        """
        Возвращает информацию о всех стратегиях.
        
        Returns:
            List[Dict]: Список с информацией о стратегиях
        """
        strategies_info = []
        
        for symbol, strategy in self.strategies.items():
            info = {
                "symbol": symbol,
                "name": strategy.name,
                "timeframe": strategy.timeframe,
                "active": symbol in self.active_tasks and not self.active_tasks[symbol].done() if self.running else False
            }
            strategies_info.append(info)
            
        return strategies_info 