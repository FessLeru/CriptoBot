"""
Модуль для управления торговыми операциями.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

from bot_logging import logger
from trading.exchange import BitgetExchange
from config import POSITION_SIZE_PERCENT


class Trader:
    """Класс для управления торговыми операциями."""

    def __init__(self, exchange: BitgetExchange):
        """
        Инициализирует объект трейдера.
        
        Args:
            exchange: Объект биржи Bitget
        """
        self.exchange = exchange
        self.leverage = 20
        self.position_size_percent = POSITION_SIZE_PERCENT
        self.active_trades = {}
        self._lock = asyncio.Lock()

        logger.info(
            f"Инициализирован трейдер с плечом {self.leverage} и размером позиции {self.position_size_percent}%")

    async def set_leverage(self, leverage: int) -> bool:
        """
        Устанавливает значение плеча для всех дальнейших сделок.
        
        Args:
            leverage: Значение плеча (1-100)
            
        Returns:
            bool: True если успешно, иначе False
        """
        if leverage < 1 or leverage > 100:
            logger.error(f"Некорректное значение плеча: {leverage}. Должно быть от 1 до 100.")
            return False

        self.leverage = leverage
        logger.info(f"Плечо установлено на {leverage}")
        return True

    async def open_trade(self, signal: Dict) -> str:
        """
        Открывает сделку на основе сигнала.
        
        Args:
            signal: Словарь с информацией о сигнале
                {
                    "symbol": "BTC/USDT",
                    "side": "buy" | "sell",
                    "tradeSide": "open",
                    "type": "market",
                    "amount": float,
                    "stop_loss": float,
                    "trail_points": float,
                    "trail_offset": float,
                    "trail_mode": bool,
                    "strategy_name": str,
                    "timeframe": str
                }
                
        Returns:
            str: Сообщение о результате
        """
        async with self._lock:
            symbol = signal["symbol"]
            side = signal["side"]  # "buy" или "sell"
            tradeSide = signal["tradeSide"]
            type = signal["type"]
            amount = signal.get("amount", 0)  # Получаем amount из сигнала
            stop_loss = signal["stop_loss"]
            trail_points = signal.get("trail_points", 0)
            trail_offset = signal.get("trail_offset", 0)
            trail_mode = signal.get("trail_mode", True)

            try:
                # Проверяем, нет ли уже активного трейда по этому символу
                if symbol in self.active_trades:
                    return f"⚠️ Уже есть активный трейд по {symbol}"

                # Устанавливаем плечо
                await self.exchange.set_leverage(self.leverage, symbol)

                # Получаем баланс фьючерсов
                usdt_balance = await self.exchange.get_usdt_balance()

                logger.info(f"📈 Баланс фьючерсов USDT: {usdt_balance:.2f}")

                # Проверка баланса
                if usdt_balance < 5:  # Минимальный порог
                    return f"⚠️ Ошибка: недостаточно средств на фьючерсах ({usdt_balance:.2f} USDT)"

                # Если amount не указан в сигнале, рассчитываем его
                if amount == 0:
                    # Получаем текущую цену для расчета объема
                    ticker_data = await self.exchange.get_ticker_price(symbol)
                    current_price = ticker_data['mark']  # Используем mark price
                    
                    # Расчет объема ордера (% от баланса с учетом плеча)
                    amount = ((usdt_balance * self.leverage / 100) * self.position_size_percent) / current_price
                    amount = round(amount, 6)
                    logger.info(f"Рассчитанный объем ордера: {amount} {symbol.split('/')[0]} ({(usdt_balance * self.leverage / 100) * self.position_size_percent} USDT)")

                # Выводим данные перед созданием ордера
                logger.info(
                    f"🚀 Открытие сделки на ФЬЮЧЕРСАХ: {symbol}, {side.upper()}, "
                    f"объем: {amount:.6f}"
                )

                # Вычисляем параметры для трейлинг-стопа (если он включен)
                trail_activation = None
                trail_callback = None

                if trail_mode:
                    # Получаем текущую цену для трейлинг-стопа
                    ticker_data = await self.exchange.get_ticker_price(symbol)
                    current_price = ticker_data['mark']  # Используем mark price
                    
                    # Для лонг-позиции активационная цена должна быть выше entry price
                    # Для шорт-позиции активационная цена должна быть ниже entry price
                    if side == "buy":  # LONG
                        # Активационная цена = текущая цена + trail_points
                        trail_activation = current_price + trail_points
                        # Callback = процент от цены, на который может отступить цена до срабатывания
                        trail_callback = (trail_offset / trail_activation) * 100  # Преобразуем в проценты для API
                    else:  # SHORT
                        # Активационная цена = текущая цена - trail_points
                        trail_activation = current_price - trail_points
                        # Callback = процент от цены, на который может отступить цена до срабатывания
                        trail_callback = (trail_offset / trail_activation) * 100  # Преобразуем в проценты для API
                    
                    # Округляем значения для API
                    trail_activation = round(trail_activation, 2)
                    trail_callback = round(trail_callback, 2)
                    
                    logger.info(f"Трейлинг-стоп: активация при {trail_activation}, callback {trail_callback}%")

                # Создаем ордер через новый метод
                order = await self.exchange.create_market_order(
                    symbol=symbol,
                    side=side,
                    amount=amount,
                    stop_loss=stop_loss,
                    trail_activation=trail_activation,
                    trail_callback=trail_callback
                )

                # Сохраняем информацию о трейде
                self.active_trades[symbol] = {
                    'order_id': order['id'],
                    'side': side,
                    'amount': amount,
                    'stop_loss': stop_loss,
                    'start_time': datetime.now(),
                    'strategy_name': signal.get('strategy_name', 'Unknown'),
                    'timeframe': signal.get('timeframe', 'Unknown')
                }

                trail_msg = " с трейлинг-стопом" if trail_mode else ""

                return f"✅ Открыта сделка {side.upper()} {symbol} на {amount:.4f}{trail_msg}"

            except Exception as e:
                logger.error(f"Ошибка при открытии сделки {symbol}: {str(e)}")
                # В случае ошибки удаляем трейд из активных
                if symbol in self.active_trades:
                    del self.active_trades[symbol]
                return f"⚠️ Ошибка при открытии сделки {symbol}: {str(e)}"

    async def close_trade(self, symbol: str) -> str:
        """
        Закрывает активную сделку по указанному символу.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            str: Сообщение о результате
        """
        async with self._lock:
            if symbol not in self.active_trades:
                return f"⚠️ Нет активной сделки по {symbol}"

            try:
                # Получаем открытые позиции
                positions = await self.exchange.fetch_positions(symbol)

                closed = False
                for position in positions:
                    if position['symbol'] == symbol and float(position['contracts']) > 0:
                        await self.exchange.close_position(position)
                        closed = True

                if closed:
                    # Удаляем из активных сделок
                    trade_info = self.active_trades.pop(symbol)
                    return f"✅ Сделка по {symbol} закрыта"
                else:
                    return f"⚠️ Не найдено открытых позиций по {symbol}"

            except Exception as e:
                logger.error(f"Ошибка при закрытии сделки {symbol}: {str(e)}")
                return f"⚠️ Ошибка при закрытии сделки {symbol}: {str(e)}"

    async def close_all_trades(self) -> Dict:
        """
        Закрывает все активные сделки.
        
        Returns:
            Dict: Результат операции {closed_orders: int, closed_positions: int}
        """
        async with self._lock:
            try:
                # Отменяем все открытые ордера
                canceled_orders = await self.exchange.cancel_all_orders()

                # Закрываем все открытые позиции
                closed_positions = await self.exchange.close_all_positions()

                # Очищаем словарь активных сделок
                self.active_trades.clear()

                return {
                    "closed_orders": canceled_orders,
                    "closed_positions": closed_positions
                }

            except Exception as e:
                logger.error(f"Ошибка при закрытии всех сделок: {str(e)}")
                return {
                    "closed_orders": 0,
                    "closed_positions": 0,
                    "error": str(e)
                }

    def get_active_trades(self) -> Dict:
        """
        Возвращает информацию о всех активных сделках.
        
        Returns:
            Dict: Словарь с информацией о активных сделках
        """
        return self.active_trades

    async def get_active_positions(self) -> List:
        """
        Получает список всех открытых позиций.
        
        Returns:
            List: Список открытых позиций
        """
        try:
            return await self.exchange.fetch_positions()
        except Exception as e:
            logger.error(f"Ошибка при получении открытых позиций: {str(e)}")
            return []

    async def get_open_orders(self) -> List:
        """
        Получает список всех открытых ордеров.
        
        Returns:
            List: Список открытых ордеров
        """
        try:
            return await self.exchange.fetch_open_orders()
        except Exception as e:
            logger.error(f"Ошибка при получении открытых ордеров: {str(e)}")
            return []
