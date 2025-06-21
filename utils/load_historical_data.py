"""
Скрипт для ручной загрузки и проверки исторических данных для BTC и ETH.
"""
import asyncio
import os
import sys
import pandas as pd
from datetime import datetime

# Добавляем корневую директорию в путь для импорта
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
from trading.exchange import BitgetExchange
from utils.data_loader import HistoricalDataLoader

# Загружаем переменные окружения
load_dotenv()

async def load_and_verify_data(symbol: str, base_timeframe: str = "15m", 
                               target_minutes: int = 45, limit: int = 1000) -> pd.DataFrame:
    """
    Загружает исторические данные для указанного символа, агрегирует их
    и выводит информацию о полученных свечах.
    
    Args:
        symbol: Торговый символ (например, 'BTC/USDT')
        base_timeframe: Базовый таймфрейм для загрузки данных
        target_minutes: Целевой таймфрейм в минутах для агрегации
        limit: Количество свечей для загрузки
        
    Returns:
        DataFrame с агрегированными данными
    """
    print(f"\n===== Загрузка данных для {symbol} =====")
    print(f"Базовый таймфрейм: {base_timeframe}")
    print(f"Целевой таймфрейм: {target_minutes}m")
    print(f"Лимит свечей: {limit}")
    print("-" * 50)
    
    # Инициализируем биржу
    exchange = BitgetExchange()
    data_loader = HistoricalDataLoader(exchange.exchange)
    
    # Загружаем и агрегируем данные
    start_time = datetime.now()
    print(f"Начало загрузки: {start_time.strftime('%H:%M:%S')}")
    
    df = await data_loader.preload_historical_data(
        symbol=symbol,
        base_timeframe=base_timeframe,
        target_minutes=target_minutes,
        limit=limit
    )
    
    end_time = datetime.now()
    elapsed = end_time - start_time
    print(f"Загрузка завершена за {elapsed.total_seconds():.2f} секунд")
    
    if df is None or df.empty:
        print(f"❌ Не удалось загрузить данные для {symbol}")
        return None
    
    # Выводим информацию о загруженных данных
    print(f"\n✅ Успешно загружено {len(df)} свечей для {symbol}")
    print(f"Период: с {df.index[0]} по {df.index[-1]}")
    print(f"Количество свечей: {len(df)}")
    
    # Выводим первые и последние свечи
    print("\n=== Первые 3 свечи ===")
    for idx, row in df.head(3).iterrows():
        print(f"{idx:%Y-%m-%d %H:%M}: O={row['open']:.1f}, H={row['high']:.1f}, "
              f"L={row['low']:.1f}, C={row['close']:.1f}, V={row['volume']:.1f}")
    
    print("\n=== Последние 3 свечи ===")
    for idx, row in df.tail(3).iterrows():
        print(f"{idx:%Y-%m-%d %H:%M}: O={row['open']:.1f}, H={row['high']:.1f}, "
              f"L={row['low']:.1f}, C={row['close']:.1f}, V={row['volume']:.1f}")
    
    # Вычисляем основные статистики
    price_range = df['high'].max() - df['low'].min()
    avg_volume = df['volume'].mean()
    
    print("\n=== Статистика ===")
    print(f"Минимальная цена: {df['low'].min():.2f}")
    print(f"Максимальная цена: {df['high'].max():.2f}")
    print(f"Диапазон цен: {price_range:.2f}")
    print(f"Средний объем: {avg_volume:.2f}")
    
    # Закрываем соединение с биржей
    await exchange.close()
    
    return df

async def main():
    """Основная функция для загрузки данных BTC и ETH."""
    try:
        print("Начинаем загрузку исторических данных...")
        
        # Загружаем данные для BTC
        btc_df = await load_and_verify_data("BTC/USDT")
        
        # Загружаем данные для ETH
        eth_df = await load_and_verify_data("ETH/USDT")
        
        # Подтверждаем успешное выполнение
        if btc_df is not None and eth_df is not None:
            print("\n✅ Данные успешно загружены для обоих символов!")
        else:
            print("\n⚠️ Не удалось загрузить данные для некоторых символов")
            
    except Exception as e:
        print(f"\n❌ Ошибка при загрузке данных: {e}")
    
if __name__ == "__main__":
    # Запускаем асинхронную функцию загрузки данных
    asyncio.run(main()) 