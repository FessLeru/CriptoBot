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
            strategy_name = signal.get("strategy_name", "Unknown")
            timeframe = signal.get("timeframe", "Unknown")

            # Логируем полученный сигнал
            logger.info(f"Получен сигнал: {symbol} {side.upper()} от стратегии {strategy_name} ({timeframe})")
            logger.info(f"Параметры сигнала: SL={stop_loss}, trail_points={trail_points}, trail_offset={trail_offset}")

            try:
                # Проверяем, нет ли уже активного трейда по этому символу
                if symbol in self.active_trades:
                    logger.warning(f"Сигнал отклонен: уже есть активный трейд по {symbol}")
                    return f"⚠️ Уже есть активный трейд по {symbol}"

                # Проверка корректности параметров сигнала
                if not symbol or not side or not tradeSide:
                    error_msg = f"Некорректные параметры сигнала: symbol={symbol}, side={side}, tradeSide={tradeSide}"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    return f"⚠️ Ошибка: {error_msg}"

                # Устанавливаем плечо
                try:
                    await self.exchange.set_leverage(self.leverage, symbol)
                except Exception as e:
                    error_msg = f"Не удалось установить плечо {self.leverage} для {symbol}: {str(e)}"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    return f"⚠️ Ошибка: {error_msg}"

                # Получаем баланс фьючерсов
                usdt_balance = await self.exchange.get_usdt_balance()
                logger.info(f"📈 Баланс фьючерсов USDT: {usdt_balance:.2f}")

                # Проверка баланса
                if usdt_balance < 5:  # Минимальный порог
                    error_msg = f"Недостаточно средств на фьючерсах ({usdt_balance:.2f} USDT)"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    return f"⚠️ Ошибка: {error_msg}"

                # Если amount не указан в сигнале, рассчитываем его
                if amount == 0:
                    try:
                        # Получаем текущую цену для расчета объема
                        ticker_data = await self.exchange.get_ticker_price(symbol)
                        current_price = ticker_data['mark']  # Используем mark price
                        
                        # Расчет объема ордера (% от баланса с учетом плеча)
                        amount = ((usdt_balance * self.leverage / 100) * self.position_size_percent) / current_price
                        amount = round(amount, 6)
                        logger.info(f"Рассчитанный объем ордера: {amount} {symbol.split('/')[0]} ({(usdt_balance * self.leverage / 100) * self.position_size_percent} USDT)")
                    except Exception as e:
                        error_msg = f"Ошибка при расчете объема ордера: {str(e)}"
                        logger.error(f"Сигнал отклонен: {error_msg}")
                        return f"⚠️ Ошибка: {error_msg}"

                # Проверка минимального объема ордера
                if amount <= 0:
                    error_msg = f"Некорректный объем ордера: {amount}"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    return f"⚠️ Ошибка: {error_msg}"

                # Выводим данные перед созданием ордера
                logger.info(
                    f"🚀 Открытие сделки на ФЬЮЧЕРСАХ: {symbol}, {side.upper()}, "
                    f"объем: {amount:.6f}"
                )

                # Вычисляем параметры для трейлинг-стопа (если он включен)
                trail_activation = None
                trail_callback = None

                ticker_data = await self.exchange.get_ticker_price(symbol)
                current_price = ticker_data['mark']  # Используем mark price
                
                if trail_mode:
                    # Настраиваем трейлинг-стоп в зависимости от типа сделки (long/short)
                    is_long = side == "buy"
                    
                    # Получаем параметры трейлинг-стопа из сигнала (это абсолютные значения)
                    trail_trigger_points = trail_points  # Абсолютное значение для активации
                    trail_step_points = trail_offset     # Абсолютное значение для шага
                    
                    # Для Long: активация выше текущей, для Short: активация ниже текущей
                    if is_long:
                        trail_activation = current_price + trail_trigger_points
                    else:
                        trail_activation = current_price - trail_trigger_points
                    
                    # Шаг трейлинга используем как абсолютное значение
                    trail_callback = trail_step_points
                    
                    logger.info(f"Настроен трейлинг-стоп: активация при {trail_activation:.2f}, "
                               f"шаг отступа: {trail_callback:.6f} USDT")

                # Создаем ордер через новый метод
                try:
                    order = await self.exchange.create_market_order(
                        symbol=symbol,
                        side=side,
                        amount=amount,
                        stop_loss=stop_loss,
                        trail_activation=trail_activation,
                        trail_callback=trail_callback
                    )
                except Exception as e:
                    error_msg = f"Ошибка при создании ордера: {str(e)}"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    # Логируем дополнительные детали ошибки для отладки
                    logger.error(f"Детали ошибки для {symbol}: Сторона: {side}, Объем: {amount}, SL: {stop_loss}")
                    
                    # Проверяем и логируем специфические ошибки API Bitget
                    if "insufficient balance" in str(e).lower():
                        logger.error(f"Причина: Недостаточно средств на счете для открытия позиции указанного размера")
                    elif "minimum" in str(e).lower():
                        logger.error(f"Причина: Объем ордера меньше минимально допустимого для {symbol}")
                    elif "maximum" in str(e).lower():
                        logger.error(f"Причина: Объем ордера больше максимально допустимого для {symbol}")
                    elif "precision" in str(e).lower():
                        logger.error(f"Причина: Неверная точность для объема или цены")
                    elif "rate limit" in str(e).lower():
                        logger.error(f"Причина: Превышен лимит запросов API")
                    elif "market closed" in str(e).lower() or "trading not open" in str(e).lower():
                        logger.error(f"Причина: Рынок закрыт или торговля не доступна для {symbol}")
                        
                    return f"⚠️ Ошибка при создании ордера: {str(e)}"
                
                # Проверяем статус ордера
                if not order or 'id' not in order:
                    error_msg = f"Не удалось получить ID ордера, ответ API: {order}"
                    logger.error(f"Сигнал отклонен: {error_msg}")
                    return f"⚠️ Ошибка при создании ордера: не удалось получить ID ордера"

                # Сохраняем информацию о трейде
                self.active_trades[symbol] = {
                    'order_id': order['id'],
                    'side': side,
                    'amount': amount,
                    'stop_loss': stop_loss,
                    'trail_activation': trail_activation,
                    'trail_callback': trail_callback,
                    'trail_mode': trail_mode,
                    'start_time': datetime.now(),
                    'strategy_name': strategy_name,
                    'timeframe': timeframe
                }

                trail_msg = f" с трейлинг-стопом (активация: {trail_activation:.2f}, отступ: {trail_callback:.6f} USDT)" if trail_mode else ""
                logger.info(f"✅ Успешно открыта сделка {side.upper()} {symbol} на {amount:.4f}{trail_msg}")
                return f"✅ Открыта сделка {side.upper()} {symbol} на {amount:.4f}{trail_msg}"

            except Exception as e:
                error_msg = f"Неожиданная ошибка при открытии сделки {symbol}: {str(e)}"
                logger.error(error_msg)
                logger.exception(e)  # Логируем полный стектрейс для диагностики
                
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
