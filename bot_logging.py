import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logger(name="trading_bot", log_dir="logs", log_file="bot.log", max_bytes=10 * 1024 * 1024, backup_count=5):
    """Настройка логгера с ротацией файлов."""

    # Создаем директорию для логов, если ее нет
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Настройка формата логов
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Настройка логгера
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Очищаем предыдущие хендлеры, если они есть (для избежания дублирования)
    if logger.handlers:
        logger.handlers = []

    # Логи в файл с ротацией
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_file),
        maxBytes=max_bytes,  # Максимальный размер файла
        backupCount=backup_count,  # Количество резервных файлов
        encoding='utf-8'  # Указываем кодировку
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Логи в консоль
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Настройка специального логгера для стратегий
def setup_strategy_logger(strategy_name, log_dir="logs"):
    """Настройка отдельного логгера для каждой стратегии."""
    
    # Создаем отдельный файл для логов стратегии
    log_file = f"strategy_{strategy_name.lower()}.log"
    
    # Настройка формата логов с указанием стратегии
    log_format = f"%(asctime)s - %(name)s - {strategy_name} - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)
    
    # Создаем директорию для логов, если ее нет
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Настройка логгера
    strategy_logger = logging.getLogger(f"strategy.{strategy_name}")
    strategy_logger.setLevel(logging.INFO)
    
    # Очищаем предыдущие хендлеры, если они есть
    if strategy_logger.handlers:
        strategy_logger.handlers = []
    
    # Логи в файл с ротацией
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, log_file),
        maxBytes=5 * 1024 * 1024,  # Максимальный размер файла (5 МБ)
        backupCount=3,  # Количество резервных файлов
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    strategy_logger.addHandler(file_handler)
    
    return strategy_logger

class BotLogger:
    """Класс для управления логированием бота и стратегий."""
    
    def __init__(self, name="trading_bot", log_dir="logs"):
        """Инициализация основного логгера бота."""
        self.main_logger = setup_logger(name=name, log_dir=log_dir)
        self.strategy_loggers = {}
        self.log_dir = log_dir
        
    def get_strategy_logger(self, strategy_name):
        """Получение или создание логгера для указанной стратегии."""
        if strategy_name not in self.strategy_loggers:
            self.strategy_loggers[strategy_name] = setup_strategy_logger(
                strategy_name=strategy_name, 
                log_dir=self.log_dir
            )
        return self.strategy_loggers[strategy_name]
    
    def log_bot_start(self, version="1.0.0", config=None):
        """Логирование запуска бота с детальной информацией."""
        self.main_logger.info("=" * 50)
        self.main_logger.info("ТОРГОВЫЙ БОТ ЗАПУСКАЕТСЯ")
        self.main_logger.info(f"Версия бота: {version}")
        self.main_logger.info(f"Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if config:
            self.main_logger.info("Конфигурация:")
            for key, value in config.items():
                self.main_logger.info(f"  {key}: {value}")
        
        self.main_logger.info("=" * 50)
    
    def log_bot_stop(self, uptime_seconds):
        """Логирование остановки бота."""
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        self.main_logger.info("=" * 50)
        self.main_logger.info("ТОРГОВЫЙ БОТ ОСТАНОВЛЕН")
        self.main_logger.info(f"Время работы: {int(hours)}ч {int(minutes)}м {int(seconds)}с")
        self.main_logger.info(f"Время остановки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.main_logger.info("=" * 50)

# Инициализация логгера
logger = setup_logger()

# testing
if __name__ == "__main__":
    # Тест основного логгера
    logger.info("Логгер успешно инициализирован.")
    logger.debug("Это отладочное сообщение.")
    logger.warning("Это предупреждение.")
    logger.error("Это сообщение об ошибке.")
    logger.critical("Это критическое сообщение.")
    
    # Тест логгера стратегий
    bot_logger = BotLogger()
    btc_logger = bot_logger.get_strategy_logger("BTC")
    eth_logger = bot_logger.get_strategy_logger("ETH")
    
    btc_logger.info("Инициализация стратегии BTC")
    eth_logger.info("Инициализация стратегии ETH")
    
    # Тест логирования запуска/остановки бота
    bot_logger.log_bot_start(config={"timeframe": "15m", "leverage": 20})
    bot_logger.log_bot_stop(3600 * 5 + 45 * 60 + 30)  # 5 часов, 45 минут и 30 секунд