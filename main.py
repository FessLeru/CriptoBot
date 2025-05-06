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