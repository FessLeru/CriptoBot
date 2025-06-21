"""
Главный модуль торгового бота для биржи Bitget.
Поддерживает множественные стратегии и асинхронную работу.
"""
import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

from bot_logging import logger
from trading.exchange import BitgetExchange
from trading.trader import Trader
from strategies.scanner import StrategyScanner
from strategies.BTC_strategy import BTCStrategy
from strategies.ETH_strategy import ETHStrategy
from bot.telegram_bot import TelegramBot
from utils.data_loader import HistoricalDataLoader, preload_data_for_trading


# Глобальные переменные для доступа к объектам из любой части программы
DATA_LOADER = None
BTC_STRATEGY = None
ETH_STRATEGY = None

async def generate_test_btc_signal(exchange, trader):
    """
    Создает и выполняет тестовый сигнал для BTC/USDT.
    
    Args:
        exchange: Объект биржи Bitget
        trader: Объект трейдера
        
    Returns:
        bool: True если тестовый сигнал был успешно исполнен
    """
    try:
        logger.info("Создание тестового сигнала для BTC/USDT...")
        
        # Получаем текущую цену через ticker
        ticker_data = await exchange.get_ticker_price("BTC/USDT")
        current_price = ticker_data['mark']  # Используем mark price

        # Вычисляем стоп-лосс (1% ниже текущей цены для LONG)
        stop_loss = current_price * 0.9999
        
        # Создаем тестовый сигнал
        test_signal = {
            "symbol": "BTC/USDT",
            "side": "buy",
            "tradeSide": "open",
            "type": "market",
            "stop_loss": stop_loss,
            "trail_points": current_price * 0.0001,
            "trail_offset": current_price * 0.0003,
            "trail_mode": True,
            "strategy_name": "TestSignal",
            "timeframe": "5m"
        }

        logger.info(f"Создан тестовый сигнал BTC/USDT BUY по цене {current_price:.2f} USDT")
        logger.info(f"Стоп-лосс: {stop_loss:.2f} USDT")
        
        # Исполняем тестовый сигнал
        result = await trader.open_trade(test_signal)
        logger.info(f"Результат тестового сигнала: {result}")
        
        return "Ошибка" not in result
    except Exception as e:
        logger.error(f"Ошибка при создании тестового сигнала: {e}")
        return False

async def reload_historical_data(exchange, base_timeframe: str = "4h", limit: int = 1000) -> dict:
    """
    Перезагружает исторические данные для BTC и ETH и обновляет их в стратегиях.
    
    Args:
        exchange: Объект биржи
        base_timeframe: Базовый таймфрейм для загрузки данных
        limit: Количество свечей для загрузки
        
    Returns:
        dict: Информация о загруженных данных
    """
    global DATA_LOADER, BTC_STRATEGY, ETH_STRATEGY
    
    try:
        logger.info(f"Перезагрузка исторических данных для BTC/USDT и ETH/USDT (база: {base_timeframe}, лимит: {limit})...")
        
        # Создаем новый загрузчик данных, если он еще не существует
        if DATA_LOADER is None:
            DATA_LOADER = HistoricalDataLoader(exchange)
        
        # Загружаем данные с учетом специфических таймфреймов для каждого символа
        symbols = ["BTC/USDT", "ETH/USDT"]
        target_timeframes = {
            "BTC/USDT": 240,  # 4 часа в минутах
            "ETH/USDT": 240   # 4 часа в минутах
        }
        
        historical_data = {}
        for symbol in symbols:
            target_minutes = target_timeframes.get(symbol, 240)
            df = await DATA_LOADER.preload_historical_data(
                symbol=symbol, 
                base_timeframe=base_timeframe, 
                target_minutes=target_minutes,
                limit=limit
            )
            if df is not None:
                historical_data[symbol] = df
        
        # Счетчики для результата
        result = {"loaded": 0, "failed": 0, "details": {}}
        
        # Обновляем данные в стратегиях
        for symbol in symbols:
            if symbol in historical_data and historical_data[symbol] is not None:
                # Добавляем информацию в результат
                candle_count = len(historical_data[symbol])
                result["loaded"] += 1
                result["details"][symbol] = {
                    "candles": candle_count,
                    "from": historical_data[symbol].index[0].strftime("%Y-%m-%d %H:%M"),
                    "to": historical_data[symbol].index[-1].strftime("%Y-%m-%d %H:%M")
                }
                
                # Обновляем данные в соответствующей стратегии
                if symbol == "BTC/USDT" and BTC_STRATEGY is not None:
                    BTC_STRATEGY.set_preloaded_data(historical_data[symbol])
                    logger.info(f"Обновлены исторические данные для BTC стратегии: {candle_count} свечей")
                    
                elif symbol == "ETH/USDT" and ETH_STRATEGY is not None:
                    ETH_STRATEGY.set_preloaded_data(historical_data[symbol])
                    logger.info(f"Обновлены исторические данные для ETH стратегии: {candle_count} свечей")
            else:
                result["failed"] += 1
                result["details"][symbol] = {"error": "Не удалось загрузить данные"}
                logger.warning(f"Не удалось загрузить исторические данные для {symbol}")
                
        return result
        
    except Exception as e:
        logger.error(f"Ошибка при перезагрузке исторических данных: {e}")
        return {"loaded": 0, "failed": len(symbols), "error": str(e)}

async def main():
    """Основная функция запуска бота."""
    try:
        global BTC_STRATEGY, ETH_STRATEGY, DATA_LOADER
        
        # Загружаем переменные окружения
        load_dotenv()
        logger.info("Загружены переменные окружения")
        
        # Инициализируем биржу
        exchange = BitgetExchange()
        logger.info("Инициализирована биржа")
        
        # Создаем трейдера
        trader = Trader(exchange)
        logger.info("Инициализирован трейдер")
        
        # Предзагрузка исторических данных для BTC и ETH (4-часовой таймфрейм)
        logger.info("Начинаем предзагрузку исторических данных для BTC/USDT и ETH/USDT...")
        historical_data, data_loader = await preload_data_for_trading(
            exchange.exchange, 
            symbols=["BTC/USDT", "ETH/USDT"],
            base_timeframe="4h"
        )
        
        # Сохраняем загрузчик данных в глобальную переменную
        DATA_LOADER = data_loader
        
        if "BTC/USDT" in historical_data and "ETH/USDT" in historical_data:
            logger.info(f"Успешно предзагружены исторические данные: "
                       f"BTC - {len(historical_data['BTC/USDT'])} свечей, "
                       f"ETH - {len(historical_data['ETH/USDT'])} свечей")
        else:
            logger.warning("Не удалось предзагрузить все необходимые исторические данные")
        
        # Создаем сканер стратегий
        scanner = StrategyScanner()
        logger.info("Инициализирован сканер стратегий")
        
        # Инициализируем стратегии с предзагруженными историческими данными
        btc_strategy = BTCStrategy(exchange=exchange.exchange)
        eth_strategy = ETHStrategy(exchange=exchange.exchange)
        
        # Сохраняем стратегии в глобальные переменные для доступа из других функций
        BTC_STRATEGY = btc_strategy
        ETH_STRATEGY = eth_strategy
        
        # Устанавливаем предзагруженные данные в стратегии, если они доступны
        if "BTC/USDT" in historical_data:
            btc_strategy.set_preloaded_data(historical_data["BTC/USDT"])
            logger.info("Установлены предзагруженные данные для BTC стратегии")
            
        if "ETH/USDT" in historical_data:
            eth_strategy.set_preloaded_data(historical_data["ETH/USDT"])
            logger.info("Установлены предзагруженные данные для ETH стратегии")
        
        # Добавляем стратегии в сканер
        scanner.add_strategy(btc_strategy)
        scanner.add_strategy(eth_strategy)
        
        # Инициализируем Telegram бота и регистрируем функцию перезагрузки данных
        telegram_bot = TelegramBot(trader, scanner)
        # Регистрируем функцию для команды /reload_data в Telegram боте
        telegram_bot.register_reload_data_handler(
            lambda base_timeframe="4h", limit=1000: reload_historical_data(
                exchange.exchange, base_timeframe=base_timeframe, limit=limit
            )
        )
        # Передаем загрузчик данных в бота для команды check_indicators
        telegram_bot.data_loader = data_loader
        logger.info("Инициализирован Telegram бот с обработчиком перезагрузки данных")
        
        # Выполняем тестовый сигнал для BTC/USDT
        test_mode = False
        if test_mode:
            logger.info("TEST_MODE включен. Выполняется тестовый сигнал...")
            await generate_test_btc_signal(exchange, trader)
        
        # Задачи для запуска
        tasks = [
            # Запускаем сканер стратегий
            asyncio.create_task(scanner.start()),
            
            # Запускаем Telegram бота
            asyncio.create_task(telegram_bot.start())
        ]
        
        logger.info("Бот успешно запущен")
        
        # Ожидаем завершения всех задач
        await asyncio.gather(*tasks)
        
    except asyncio.CancelledError:
        logger.info("Получен сигнал на завершение работы")
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}")
        logger.exception(e)
    finally:
        # Корректное завершение работы
        try:
            if 'scanner' in locals():
                await scanner.stop()
                
            if 'telegram_bot' in locals():
                await telegram_bot.stop()
                
            if 'exchange' in locals():
                await exchange.close()
                
            logger.info("Бот успешно остановлен")
        except Exception as e:
            logger.error(f"Ошибка при остановке: {e}")
            
if __name__ == "__main__":
    logger.info("Запуск бота...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.critical(f"Неперехваченное исключение: {e}")
        logger.exception(e)
        sys.exit(1) 