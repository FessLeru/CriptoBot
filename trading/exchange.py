"""
Модуль для работы с биржей Bitget.
"""
import os
import ccxt.async_support as ccxt
import logging
from typing import Dict, List, Optional, Any, Union
from decimal import Decimal

from bot_logging import logger

class BitgetExchange:
    """Класс для работы с биржей Bitget."""
    
    def __init__(self):
        """Инициализирует клиент Bitget с ключами из переменных окружения."""
        self.api_key = os.getenv("API_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.passphrase = os.getenv("PASSPHRASE")
        
        if not self.api_key or not self.secret_key or not self.passphrase:
            raise ValueError("API keys are missing. Please check your .env file.")
            
        self.exchange = ccxt.bitget({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'password': self.passphrase,
            'options': {'defaultType': 'swap'},  # Фьючерсы Bitget
            'enableRateLimit': True
        })
        
        logger.info("Инициализирован клиент Bitget")
        
    async def __aenter__(self):
        """Контекстный менеджер для асинхронного использования."""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрывает соединение при выходе из контекстного менеджера."""
        await self.close()
        
    async def close(self):
        """Закрывает соединение с биржей."""
        if hasattr(self, 'exchange') and self.exchange:
            await self.exchange.close()
            logger.info("Соединение с Bitget закрыто")
    
    async def fetch_balance(self, params: Optional[Dict] = None) -> Dict:
        """
        Получает баланс с учетом указанных параметров.
        
        Args:
            params: Дополнительные параметры запроса
            
        Returns:
            Dict: Информация о балансе
        """
        default_params = {'type': 'swap'}
        if params:
            default_params.update(params)
            
        return await self.exchange.fetch_balance(default_params)
    
    async def get_usdt_balance(self) -> float:
        """
        Получает баланс USDT на фьючерсном счете.
        
        Returns:
            float: Баланс USDT
        """
        try:
            balance = await self.fetch_balance({'type': 'swap'})
            return balance['total'].get('USDT', 0)
        except Exception as e:
            logger.error(f"Ошибка при получении баланса USDT: {e}")
            return 0
    
    async def set_leverage(self, leverage: int, symbol: str) -> Dict:
        """
        Устанавливает плечо для указанного символа.
        
        Args:
            leverage: Значение плеча (1-100)
            symbol: Торговый символ
            
        Returns:
            Dict: Ответ биржи
        """
        try:
            if leverage < 1 or leverage > 100:
                raise ValueError("Плечо должно быть в диапазоне от 1 до 100")
                
            # Добавляем обязательный параметр marginCoin для Bitget API
            params = {
                "marginCoin": "USDT",
                "instId": symbol  # Идентификатор инструмента
            }
            
            response = await self.exchange.set_leverage(leverage, symbol, params=params)
            logger.info(f"Плечо для {symbol} установлено на {leverage}")
            return response
        except Exception as e:
            logger.error(f"Ошибка при установке плеча для {symbol}: {e}")
            raise
    
    async def create_market_order(self, 
                                symbol: str, 
                                side: str, 
                                amount: float, 
                                price: float,  # Добавляем параметр цены
                                stop_loss: float = None,
                                trail_activation: float = None,
                                trail_callback: float = None) -> Dict:
        """
        Создает рыночный ордер с указанными параметрами и стоп-лоссом.
        
        Args:
            symbol: Торговый символ
            side: Сторона сделки ('buy' или 'sell')
            amount: Объем сделки в базовой валюте
            price: Цена для расчета quoteSize
            stop_loss: Цена стоп-лосса
            trail_activation: Активационная цена для трейлинг-стопа
            trail_callback: Процент отступа для трейлинг-стопа
            
        Returns:
            Dict: Информация о созданном ордере
        """
        try:
            position_side = "long" if side == "buy" else "short"
            
            # Рассчитываем quoteSize (сумма в USDT)
            amount = round(amount, 6)
            quote_size = amount * price
            quote_size = round(quote_size, 8)
            
            # Форматируем значения для избежания научной нотации
            amount_str = f"{amount:.6f}".rstrip('0').rstrip('.') if '.' in f"{amount:.6f}" else f"{amount:.6f}"
            quote_size_str = f"{quote_size:.8f}".rstrip('0').rstrip('.') if '.' in f"{quote_size:.8f}" else f"{quote_size:.8f}"
            
            print(f"quote_size: {quote_size_str}, amount: {amount_str}")
            
            # Базовые параметры ордера
            order_params = {
                "timeInForce": "GTC",
                "reduceOnly": False,
                "positionSide": position_side,
                "type": "swap",
                "marginMode": "isolated",
                "marginCoin": "USDT",
                "loanType": "normal",
                "baseSize": amount_str,                # Количество в базовой валюте (BTC, ETH и т.д.)
                "quoteSize": quote_size_str,           # Количество в котируемой валюте (USDT)
                "priceType": "market"                   # Указываем тип цены как рыночный
            }
            
            # Добавляем стоп-лосс если указан
            if stop_loss:
                order_params["stopLoss"] = {
                    "triggerPrice": stop_loss,
                    "price": stop_loss,
                }
                
            # Добавляем трейлинг-стоп если указаны параметры
            if trail_activation and trail_callback:
                order_params["trailingStop"] = {
                    "activationPrice": trail_activation,
                    "callbackRate": trail_callback
                }
                
            # Создаем рыночный ордер
            order = await self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=amount,
                params=order_params
            )
            
            logger.info(f"Создан рыночный ордер {side.upper()} для {symbol} на объем {amount_str}")
            return order
            
        except Exception as e:
            logger.error(f"Ошибка при создании рыночного ордера для {symbol}: {e}")
            raise
    
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> List:
        """
        Получает OHLCV данные для указанного символа и таймфрейма.
        
        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм
            limit: Максимальное количество свечей
            
        Returns:
            List: Список OHLCV свечей
        """
        try:
            params = {
                "instType": "swap",  # Указываем тип инструмента - фьючерсы
                "marginCoin": "USDT"  # Маржинальная валюта
            }
            
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                params=params
            )
            
            return ohlcv
        except Exception as e:
            logger.error(f"Ошибка при получении OHLCV данных для {symbol} ({timeframe}): {e}")
            raise
    
    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List:
        """
        Получает список открытых ордеров.
        
        Args:
            symbol: Торговый символ (опционально)
            
        Returns:
            List: Список открытых ордеров
        """
        try:
            params = {"marginCoin": "USDT"}
            if symbol:
                return await self.exchange.fetch_open_orders(symbol=symbol, params=params)
            else:
                return await self.exchange.fetch_open_orders(params=params)
        except Exception as e:
            logger.error(f"Ошибка при получении открытых ордеров: {e}")
            return []
    
    async def fetch_positions(self, symbol: Optional[str] = None) -> List:
        """
        Получает список открытых позиций.
        
        Args:
            symbol: Торговый символ (опционально)
            
        Returns:
            List: Список открытых позиций
        """
        try:
            params = {"marginCoin": "USDT"}
            if symbol:
                params["symbol"] = symbol
                
            return await self.exchange.fetch_positions(params=params)
        except Exception as e:
            logger.error(f"Ошибка при получении открытых позиций: {e}")
            return []
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """
        Отменяет ордер по его ID.
        
        Args:
            order_id: ID ордера
            symbol: Торговый символ
            
        Returns:
            Dict: Результат отмены ордера
        """
        try:
            params = {"marginCoin": "USDT"}
            result = await self.exchange.cancel_order(order_id, symbol, params=params)
            logger.info(f"Ордер {order_id} для {symbol} отменен")
            return result
        except Exception as e:
            logger.error(f"Ошибка при отмене ордера {order_id} для {symbol}: {e}")
            raise
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Отменяет все открытые ордера.
        
        Args:
            symbol: Торговый символ (опционально)
            
        Returns:
            int: Количество отмененных ордеров
        """
        try:
            orders = await self.fetch_open_orders(symbol)
            canceled_count = 0
            
            for order in orders:
                try:
                    await self.cancel_order(order['id'], order['symbol'])
                    canceled_count += 1
                except Exception as e:
                    logger.error(f"Не удалось отменить ордер {order['id']}: {e}")
                    
            return canceled_count
        except Exception as e:
            logger.error(f"Ошибка при отмене всех ордеров: {e}")
            return 0
    
    async def close_position(self, position: Dict) -> bool:
        """
        Закрывает указанную позицию.
        
        Args:
            position: Словарь с информацией о позиции
            
        Returns:
            bool: True если позиция успешно закрыта, иначе False
        """
        try:
            symbol = position['symbol']
            contracts = float(position['contracts'])
            
            if contracts <= 0:
                logger.warning(f"Позиция {symbol} уже закрыта (объем = {contracts})")
                return True
                
            side = 'sell' if position['side'] == 'long' else 'buy'
            
            # Получаем mark price из позиции для расчета quoteSize
            mark_price = float(position.get('markPrice', 0))
            contracts = round(contracts, 6)
            quote_size = contracts * mark_price if mark_price > 0 else 0
            quote_size = round(quote_size, 8)
            
            # Форматируем значения для избежания научной нотации
            contracts_str = f"{contracts:.6f}".rstrip('0').rstrip('.') if '.' in f"{contracts:.6f}" else f"{contracts:.6f}"
            quote_size_str = f"{quote_size:.8f}".rstrip('0').rstrip('.') if '.' in f"{quote_size:.8f}" else f"{quote_size:.8f}"
            
            logger.info(f"Закрытие позиции {symbol}: контракты={contracts_str}, сумма={quote_size_str} USDT")
            
            # Добавляем обязательные параметры для Bitget API
            params = {
                'reduceOnly': True,
                'marginCoin': 'USDT',
                'positionSide': position['side'],
                'loanType': 'isolated',
                'baseSize': contracts_str,             # Количество в базовой валюте
                'quoteSize': quote_size_str,           # Количество в котируемой валюте (USDT)
                'priceType': 'market'                   # Указываем тип цены как рыночный
            }
            
            await self.exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=contracts,
                params=params
            )
            
            logger.info(f"Позиция {symbol} ({position['side']}) успешно закрыта")
            return True
        except Exception as e:
            logger.error(f"Ошибка при закрытии позиции {position['symbol']}: {e}")
            return False
    
    async def close_all_positions(self) -> int:
        """
        Закрывает все открытые позиции.
        
        Returns:
            int: Количество закрытых позиций
        """
        try:
            positions = await self.fetch_positions()
            closed_count = 0
            
            for position in positions:
                if float(position['contracts']) > 0:
                    success = await self.close_position(position)
                    if success:
                        closed_count += 1
                        
            return closed_count
        except Exception as e:
            logger.error(f"Ошибка при закрытии всех позиций: {e}")
            return 0 