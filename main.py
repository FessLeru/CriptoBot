"""
Главный модуль торгового бота для биржи Bitget.
Поддерживает множественные стратегии и асинхронную работу.
"""
import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
import winloop

from bot_logging import logger
from trading.exchange import BitgetExchange
from trading.trader import Trader
from strategies.scanner import StrategyScanner
from strategies.BTC_strategy import BTCStrategy
from strategies.ETH_strategy import ETHStrategy
from bot.telegram_bot import TelegramBot

# Настройка event loop для Windows
winloop.install()

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

        # Вычисляем стоп-лосс (0.5% ниже текущей цены для LONG)
        stop_loss_percent = 0.5  # 0.5%
        stop_loss = current_price * (1 - stop_loss_percent / 100)
        
        # Параметры трейлинг-стопа (абсолютные значения в USDT)
        trail_trigger_percent = 0.7  # 0.7%
        trail_step_percent = 0.25    # 0.25%
        trail_points = current_price * trail_trigger_percent / 100
        trail_offset = current_price * trail_step_percent / 100
        
        # Создаем тестовый сигнал
        test_signal = {
            "symbol": "BTC/USDT",
            "side": "buy",
            "tradeSide": "open",
            "type": "market",
            "stop_loss": stop_loss,
            "trail_points": trail_points,
            "trail_offset": trail_offset,
            "trail_mode": True,
            "strategy_name": "TestSignal",
            "timeframe": "5m"
        }

        logger.info(f"Создан тестовый сигнал BTC/USDT BUY по цене {current_price:.2f} USDT")
        logger.info(f"Стоп-лосс: {stop_loss:.2f} USDT")
        logger.info(f"Трейлинг-стоп: активация при {trail_points:.2f} пунктов, шаг {trail_offset:.2f}")
        
        # Исполняем тестовый сигнал
        result = await trader.open_trade(test_signal)
        logger.info(f"Результат тестового сигнала: {result}")
        return "Ошибка" not in result
    except Exception as e:
        logger.error(f"Ошибка при создании тестового сигнала: {e}")
        return False

async def main():
    """Основная функция запуска бота."""
    try:
        # Загружаем переменные окружения
        load_dotenv()
        logger.info("Загружены переменные окружения")
        
        # Инициализируем биржу
        exchange = BitgetExchange()
        logger.info("Инициализирована биржа")
        
        # Создаем трейдера
        trader = Trader(exchange)
        logger.info("Инициализирован трейдер")
        
        # Создаем сканер стратегий
        scanner = StrategyScanner()
        logger.info("Инициализирован сканер стратегий")
        
        # Инициализируем стратегии
        btc_strategy = BTCStrategy(exchange=exchange.exchange)
        eth_strategy = ETHStrategy(exchange=exchange.exchange)
        
        # Добавляем стратегии в сканер
        scanner.add_strategy(btc_strategy)
        scanner.add_strategy(eth_strategy)
        
        # Инициализируем Telegram бота
        telegram_bot = TelegramBot(trader, scanner)
        logger.info("Инициализирован Telegram бот")
        
        # Выполняем тестовый сигнал для BTC/USDT
        test_mode = os.getenv("TEST_MODE", "false").lower() == "true"
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