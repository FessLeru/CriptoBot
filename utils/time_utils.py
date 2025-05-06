"""
Утилиты для работы с временем и синхронизация свечей.
"""
import asyncio
from datetime import datetime, timedelta
import logging
from typing import Dict, Union, Optional

logger = logging.getLogger(__name__)

# Словарь с временными интервалами для каждого таймфрейма в секундах
TIMEFRAME_SECONDS = {
    '1m': 60,
    '3m': 180, 
    '5m': 300,
    '15m': 900,
    '30m': 1800,
    '45m': 2700,
    '1h': 3600,
    '2h': 7200,
    '4h': 14400,
    '6h': 21600,
    '12h': 43200,
    '1d': 86400,
    '3d': 259200,
    '1w': 604800,
}

# Словарь с форматами для таймфреймов Bitget
BITGET_TIMEFRAMES = {
    '1m': '1m',
    '3m': '3m',
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '45m': '45m',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '6h': '6h',
    '12h': '12h',
    '1d': '1d',
    '3d': '3d',
    '1w': '1w',
}

def validate_timeframe(timeframe: str) -> bool:
    """
    Проверяет, что указанный таймфрейм поддерживается.
    
    Args:
        timeframe: Строка с таймфреймом, например '1m', '1h', '1d'
        
    Returns:
        bool: True если таймфрейм поддерживается, иначе False
    """
    return timeframe in TIMEFRAME_SECONDS


def get_timeframe_seconds(timeframe: str) -> int:
    """
    Возвращает количество секунд в таймфрейме.
    
    Args:
        timeframe: Строка с таймфреймом, например '1m', '1h', '1d'
        
    Returns:
        int: Количество секунд в таймфрейме
        
    Raises:
        ValueError: Если таймфрейм не поддерживается
    """
    if not validate_timeframe(timeframe):
        raise ValueError(f"Таймфрейм {timeframe} не поддерживается")
    
    return TIMEFRAME_SECONDS[timeframe]


def get_next_candle_time(timeframe: str) -> datetime:
    """
    Вычисляет время следующего закрытия свечи для указанного таймфрейма.
    
    Args:
        timeframe: Строка с таймфреймом, например '1m', '1h', '1d'
        
    Returns:
        datetime: Время следующего закрытия свечи
    """
    if not validate_timeframe(timeframe):
        raise ValueError(f"Таймфрейм {timeframe} не поддерживается")
    
    seconds = get_timeframe_seconds(timeframe)
    now = datetime.now()
    
    # Вычисляем время следующего закрытия свечи
    timestamp = now.timestamp()
    next_close = (timestamp // seconds + 1) * seconds
    
    return datetime.fromtimestamp(next_close)


async def wait_for_candle_close(timeframe: str) -> None:
    """
    Ожидает закрытия текущей свечи для указанного таймфрейма + 1 секунда.
    
    Args:
        timeframe: Строка с таймфреймом, например '1m', '1h', '1d'
    """
    next_candle = get_next_candle_time(timeframe)
    now = datetime.now()
    
    # Вычисляем время до следующего закрытия свечи + 1 секунда (для гарантии)
    wait_seconds = (next_candle - now).total_seconds() + 1
    
    logger.info(f"Ожидание {wait_seconds:.2f} секунд до закрытия свечи {timeframe} и начала сканирования")
    await asyncio.sleep(wait_seconds)


def get_all_supported_timeframes() -> Dict[str, str]:
    """
    Возвращает словарь всех поддерживаемых таймфреймов.
    
    Returns:
        Dict[str, str]: Словарь таймфреймов в формате {timeframe: description}
    """
    return {
        '1m': '1 минута',
        '3m': '3 минуты',
        '5m': '5 минут',
        '15m': '15 минут',
        '30m': '30 минут',
        '45m': '45 минут',
        '1h': '1 час',
        '2h': '2 часа',
        '4h': '4 часа',
        '6h': '6 часов',
        '12h': '12 часов',
        '1d': '1 день',
        '3d': '3 дня',
        '1w': '1 неделя',
    }


def get_bitget_timeframe(timeframe: str) -> str:
    """
    Преобразует общий формат таймфрейма в формат Bitget.
    
    Args:
        timeframe: Строка с таймфреймом, например '1m', '1h', '1d'
        
    Returns:
        str: Таймфрейм в формате Bitget
    """
    if timeframe not in BITGET_TIMEFRAMES:
        raise ValueError(f"Таймфрейм {timeframe} не поддерживается Bitget")
    
    return BITGET_TIMEFRAMES[timeframe] 