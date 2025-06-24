"""
Модуль для работы с биржей Bitget.
"""
import os
import ccxt.async_support as ccxt
import logging
import aiohttp
import json
import hmac
import base64
import time
import asyncio
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
            'options': {
                'defaultType': 'swap',  # Фьючерсы Bitget
                'defaultMarginMode': 'isolated',  # Изолированная маржа
                'defaultContractType': 'perpetual'  # Бессрочные контракты
            },
            'enableRateLimit': True
        })
        
        # Base URL для API Bitget
        self.api_base_url = 'https://api.bitget.com'
        
        # Словарь для хранения задач мониторинга ордеров
        self._order_monitor_tasks = {}
        
        # Запускаем задачу периодической проверки и очистки мониторинга
        self._cleanup_task = asyncio.create_task(self._periodic_monitoring_cleanup())
        
        logger.info("Инициализирован клиент Bitget для фьючерсной торговли")
        
    def _format_symbol(self, symbol: str) -> str:
        """
        Преобразует символ в формат Bitget API для фьючерсов.
        
        Args:
            symbol: Символ в формате 'BTC/USDT' или 'BTC/USDT:USDT'
            
        Returns:
            str: Символ в формате 'BTCUSDT'
        """
        if '/' in symbol:
            # Удаляем суффикс ':USDT' если он присутствует
            if ':' in symbol:
                symbol = symbol.split(':')[0]
                
            base, quote = symbol.split('/')
            return f"{base}{quote}"
        return symbol

    async def __aenter__(self):
        """Контекстный менеджер для асинхронного использования."""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрывает соединение при выходе из контекстного менеджера."""
        await self.close()
        
    async def close(self):
        """Закрывает соединение с биржей."""
        if hasattr(self, '_cleanup_task') and self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
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
        default_params = {
            'instType': 'swap',
            'marginCoin': 'USDT'
        }
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
            balance = await self.fetch_balance()
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
                
            formatted_symbol = self._format_symbol(symbol)
            params = {
                "instType": "swap",
                "marginCoin": "USDT",
                "symbol": formatted_symbol,
                "leverage": str(leverage)
            }
            
            response = await self.exchange.set_leverage(leverage, formatted_symbol, params=params)
            logger.info(f"Плечо для {formatted_symbol} установлено на {leverage}")
            return response
        except Exception as e:
            logger.error(f"Ошибка при установке плеча для {symbol}: {e}")
            raise
    
    async def get_ticker_price(self, symbol: str) -> Dict:
        """
        Получает актуальные данные о цене для указанного символа.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            Dict: Данные о цене, включая mark price и index price
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            
            ticker = await self.exchange.fetch_ticker(formatted_symbol, params=params)
            return {
                'last': ticker['last'],
                'mark': ticker.get('mark', ticker['last']),
                'index': ticker.get('index', ticker['last'])
            }
        except Exception as e:
            logger.error(f"Ошибка при получении данных о цене для {symbol}: {e}")
            raise

    async def _monitor_trailing_stop(self, symbol: str, position_side: str, trail_activation: float, trail_callback: float):
        """
        Мониторит исполнение трейлинг-стопа. Если трейлинг-стоп сработал, но позиция осталась открытой,
        создает новый трейлинг-стоп (не обновляет непрерывно).
        
        Args:
            symbol: Торговый символ
            position_side: Сторона позиции ('long' или 'short')
            trail_activation: Активационное значение для трейлинг-стопа
            trail_callback: Значение шага трейлинг-стопа
        """
        try:
            # Флаг для отслеживания наличия установленного трейлинг-стопа
            trailing_stop_set = True  # Начинаем с True, поскольку трейлинг-стоп уже должен быть установлен
            
            # Сохраняем начальный размер позиции для отслеживания изменений
            initial_positions = await self.fetch_positions(symbol)
            if not initial_positions:
                logger.warning(f"Позиция {symbol} не найдена при запуске мониторинга трейлинг-стопа")
                # Отменяем все ордера на всякий случай
                await self.cancel_all_orders(symbol)
                # Отменяем задачи мониторинга
                await self.cancel_trailing_stop_tasks(symbol)
                return
                
            initial_position = initial_positions[0]
            initial_contracts = float(initial_position['contracts'])
            
            logger.info(f"Начат мониторинг трейлинг-стопа для {symbol}, начальный размер позиции: {initial_contracts}")
            
            # Регистрируем идентификатор этой задачи в словаре
            monitoring_key = f"{symbol}_{position_side}_trailing"
            
            # Получаем ID текущего трейлинг-стопа из словаря, если есть
            trailing_info_key = f"{symbol}_trailing_info"
            current_trailing_stop_id = None
            if trailing_info_key in self._order_monitor_tasks:
                trailing_info = self._order_monitor_tasks[trailing_info_key]
                current_trailing_stop_id = trailing_info.get('order_id')
            
            while True:
                # Проверяем текущие позиции
                positions = await self.fetch_positions(symbol)
                if not positions:
                    logger.info(f"Позиция {symbol} закрыта, прекращаем мониторинг трейлинг-стопа")
                    # Отменяем текущий трейлинг-стоп по ID, если известен
                    if current_trailing_stop_id:
                        await self.cancel_trailing_stop_by_id(current_trailing_stop_id, symbol)
                    # Отменяем все связанные ордера, так как позиция закрыта
                    await self.cancel_all_orders(symbol)
                    return

                position = positions[0]
                current_contracts = float(position['contracts'])
                
                if current_contracts <= 0:
                    logger.info(f"Позиция {symbol} закрыта, прекращаем мониторинг трейлинг-стопа")
                    # Отменяем текущий трейлинг-стоп по ID, если известен
                    if current_trailing_stop_id:
                        await self.cancel_trailing_stop_by_id(current_trailing_stop_id, symbol)
                    # Отменяем все связанные ордера, так как позиция закрыта
                    await self.cancel_all_orders(symbol)
                    return
                
                # Проверяем, есть ли какое-то изменение позиции
                if current_contracts != initial_contracts:
                    logger.info(f"Изменение размера позиции {symbol}: было {initial_contracts}, стало {current_contracts}")
                    
                    # Если размер позиции уменьшился, это может означать, что трейлинг-стоп сработал частично
                    if current_contracts < initial_contracts:
                        # Отменяем текущий трейлинг-стоп по ID, если известен
                        if current_trailing_stop_id:
                            await self.cancel_trailing_stop_by_id(current_trailing_stop_id, symbol)
                            current_trailing_stop_id = None
                            
                        # Проверяем все открытые ордера и отменяем их
                        await self.cancel_all_orders(symbol)
                        
                        # Обновляем начальный размер позиции
                        initial_contracts = current_contracts
                        
                        # Сбрасываем флаг трейлинг-стопа
                        trailing_stop_set = False
                    else:
                        # Если размер позиции увеличился, просто обновляем отслеживаемый размер
                        initial_contracts = current_contracts
                    
                # Если трейлинг-стоп активен, просто продолжаем мониторинг
                if trailing_stop_set:
                    logger.debug(f"Трейлинг-стоп для {symbol} активен, продолжаем мониторинг")
                else:
                    # Если флаг trailing_stop_set сбросился, это значит что трейлинг-стоп сработал
                    logger.info(f"Трейлинг-стоп для {symbol} исполнен, но позиция осталась открытой. Создаем новый.")
                    
                    # Получаем текущую цену
                    ticker_data = await self.get_ticker_price(symbol)
                    current_price = ticker_data['mark']
                    
                    try:
                        # Пересчитываем параметры для нового трейлинг-стопа
                        if position_side == 'long':
                            # Для long активация должна быть на trail_callback пунктов выше текущей цены
                            new_activation_price = current_price + trail_callback
                        else:  # short
                            # Для short активация должна быть на trail_callback пунктов ниже текущей цены
                            new_activation_price = current_price - trail_callback
                        
                        # Вычисляем процент для API на основе абсолютного значения
                        trail_callback_percent = (trail_callback / current_price) * 100
                        
                        logger.info(f"Пересчитанные параметры: текущая цена={current_price}, "
                                    f"новая цена активации={new_activation_price}, "
                                    f"шаг трейлинга={trail_callback} USDT ({trail_callback_percent:.2f}%)")

                        params = {
                            'instType': 'swap',
                            'marginCoin': 'USDT',
                            'symbol': self._format_symbol(symbol),
                            'reduceOnly': True,
                            'positionSide': position_side,
                            'trailingTriggerPrice': new_activation_price,
                            'trailingPercent': trail_callback_percent
                        }
                        
                        # Создаем новый трейлинг-стоп
                        trailing_order = await self.exchange.create_order(
                            symbol=symbol,
                            type='market',
                            side='sell' if position_side == 'long' else 'buy',
                            amount=position['contracts'],
                            params=params
                        )
                        
                        # Проверяем успешность создания ордера
                        if 'id' in trailing_order:
                            logger.info(f"Новый трейлинг-стоп установлен для позиции {symbol} с ID: {trailing_order['id']}")
                            trailing_stop_set = True
                            current_trailing_stop_id = trailing_order['id']
                            
                            # Обновляем информацию о трейлинг-стопе в словаре мониторинга
                            trailing_info = {
                                'order_id': trailing_order['id'],
                                'symbol': symbol,
                                'position_side': position_side,
                                'current_contracts': current_contracts
                            }
                            self._order_monitor_tasks[f"{symbol}_trailing_info"] = trailing_info
                        else:
                            logger.warning(f"Новый трейлинг-стоп не был создан корректно. Ответ: {trailing_order}")
                            trailing_stop_set = False
                    except Exception as e:
                        logger.error(f"Ошибка при создании нового трейлинг-стопа: {e}")
                        trailing_stop_set = False

                # Проверяем состояние позиции каждые 5 секунд
                await asyncio.sleep(5)  # Пауза увеличена для снижения нагрузки на API

                # Периодически проверяем, не отменена ли текущая задача
                if monitoring_key not in self._order_monitor_tasks:
                    logger.info(f"Задача мониторинга {monitoring_key} была отменена извне, завершаем работу")
                    # Отменяем текущий трейлинг-стоп по ID перед выходом
                    if current_trailing_stop_id:
                        await self.cancel_trailing_stop_by_id(current_trailing_stop_id, symbol)
                    return

        except Exception as e:
            logger.error(f"Ошибка при мониторинге трейлинг-стопа для {symbol}: {e}")
        finally:
            # Удаляем задачу из словаря
            task_key = f"{symbol}_{position_side}_trailing"
            if task_key in self._order_monitor_tasks:
                del self._order_monitor_tasks[task_key]
            
            # Удаляем информацию о трейлинг-стопе
            trailing_info_key = f"{symbol}_trailing_info"
            if trailing_info_key in self._order_monitor_tasks:
                del self._order_monitor_tasks[trailing_info_key]
                
            # Удаляем флаг мониторинга символа
            symbol_key = f"{symbol}_monitoring"
            if symbol_key in self._order_monitor_tasks:
                del self._order_monitor_tasks[symbol_key]

    async def _monitor_order_execution(self, order_id: str, symbol: str, trail_activation: float = None, trail_callback: float = None):
        """
        Мониторит исполнение ордера и устанавливает трейлинг-стоп после исполнения.
        
        Args:
            order_id: ID ордера
            symbol: Торговый символ
            trail_activation: Активационная цена для трейлинг-стопа (абсолютное значение)
            trail_callback: Шаг трейлинг-стопа (абсолютное значение)
        """
        try:
            start_time = time.time()
            timeout = 600  # 10 минут в секундах
            
            # Регистрируем символ как отслеживаемый
            symbol_monitor_key = f"{symbol}_monitoring"
            self._order_monitor_tasks[symbol_monitor_key] = True
            
            # Начальная проверка для определения исходного состояния
            initial_positions = await self.fetch_positions(symbol)
            initial_position_size = 0
            if initial_positions:
                for pos in initial_positions:
                    if float(pos['contracts']) > 0:
                        initial_position_size = float(pos['contracts'])
                        break
            
            while time.time() - start_time < timeout:
                # Проверяем статус ордера
                try:
                    order = await self.exchange.fetch_order(order_id, symbol)
                except Exception as e:
                    logger.error(f"Ошибка при получении статуса ордера {order_id}: {e}")
                    # Проверяем, существует ли позиция
                    positions = await self.fetch_positions(symbol)
                    position_exists = False
                    for pos in positions:
                        if float(pos['contracts']) > 0:
                            position_exists = True
                            break
                    
                    if not position_exists:
                        logger.warning(f"Позиция {symbol} закрыта, возможно по стоп-лоссу. Прекращаем мониторинг.")
                        await self.force_clean_monitoring_tasks(symbol)
                        return False
                    
                    # Продолжаем мониторинг, если позиция все еще существует
                    await asyncio.sleep(1)
                    continue
                
                # Проверяем, не закрылась ли позиция по стоп-лоссу
                current_positions = await self.fetch_positions(symbol)
                current_position_size = 0
                if current_positions:
                    for pos in current_positions:
                        if float(pos['contracts']) > 0:
                            current_position_size = float(pos['contracts'])
                            break
                
                # Если позиция была, но теперь её нет или размер изменился - возможно закрытие по стоп-лоссу
                if initial_position_size > 0 and (current_position_size == 0 or current_position_size < initial_position_size):
                    logger.warning(f"Обнаружено изменение позиции {symbol}: было {initial_position_size}, стало {current_position_size}. Возможно закрытие по стоп-лоссу.")
                    
                    # При любом изменении размера позиции отменяем все трейлинг-стопы
                    await self.cancel_all_trailing_stops_for_symbol(symbol)
                    
                    # Если позиция полностью закрыта
                    if current_position_size == 0:
                        logger.info(f"Позиция {symbol} закрыта, прекращаем мониторинг.")
                        await self.force_clean_monitoring_tasks(symbol)
                        return True
                    
                    # Обновляем размер позиции, если она была частично закрыта
                    initial_position_size = current_position_size
                
                if order['status'] == 'closed':
                    logger.info(f"Ордер {order_id} исполнен, устанавливаем трейлинг-стоп. trail_activation={trail_activation}, trail_callback={trail_callback}")
                    
                    # Если есть параметры для трейлинг-стопа, устанавливаем его
                    if trail_activation and trail_callback:
                        try:
                            # Проверяем на наличие открытых стопов для этого символа
                            open_orders = await self.fetch_open_orders(symbol)
                            for open_order in open_orders:
                                # Если это стоп или трейлинг, отменяем его
                                if 'stop' in str(open_order['type']).lower() or 'trailing' in str(open_order['type']).lower():
                                    logger.info(f"Отменяем существующий стоп для {symbol}: {open_order['id']}")
                                    try:
                                        await self.cancel_order(open_order['id'], symbol)
                                    except Exception as cancel_error:
                                        logger.error(f"Ошибка при отмене ордера: {cancel_error}")
                            
                            # Получаем текущую позицию
                            positions = await self.fetch_positions(symbol)
                            if not positions:
                                logger.warning(f"Позиция для {symbol} не найдена после исполнения ордера")
                                return True
                                
                            position = positions[0]
                            if float(position['contracts']) <= 0:
                                logger.warning(f"Позиция для {symbol} имеет нулевой размер после исполнения ордера")
                                return True
                                
                            # Получаем текущую цену для расчета процента
                            ticker_data = await self.get_ticker_price(symbol)
                            current_price = ticker_data['mark']
                            
                            # Вычисляем процент для API на основе абсолютного значения
                            trail_callback_percent = (trail_callback / current_price) * 100
                            
                            logger.info(f"Параметры трейлинг-стопа: цена активации={trail_activation}, "
                                       f"шаг трейлинга={trail_callback} USDT ({trail_callback_percent:.2f}%)")
                            
                            # Устанавливаем трейлинг-стоп
                            params = {
                                'instType': 'swap',
                                'marginCoin': 'USDT',
                                'symbol': self._format_symbol(symbol),
                                'reduceOnly': True,
                                'positionSide': position['side'],
                                'trailingTriggerPrice': trail_activation,
                                'trailingPercent': trail_callback_percent
                            }
                            
                            # Создаем ордер трейлинг-стопа
                            trailing_order = await self.exchange.create_order(
                                symbol=symbol,
                                type='market',
                                side='sell' if position['side'] == 'long' else 'buy',
                                amount=position['contracts'],
                                params=params
                            )
                            
                            # Небольшая пауза для обновления информации на бирже
                            await asyncio.sleep(3)

                            logger.info(f"Трейлинг-стоп установлен для позиции {symbol}, ID: {trailing_order['id']}")
                            
                            # Проверяем наличие ID в ответе
                            if 'id' in trailing_order:
                                trailing_order_id = trailing_order['id']
                                logger.info(f"Запускаем мониторинг трейлинг-стопа с ID: {trailing_order_id}")
                                
                                # Запускаем мониторинг трейлинг-стопа
                                monitor_task = asyncio.create_task(
                                    self._monitor_trailing_stop(
                                        symbol,
                                        position['side'],
                                        trail_activation,
                                        trail_callback
                                    )
                                )
                                # Используем ID трейлинг-стопа для ключа задачи мониторинга
                                task_key = f"{symbol}_{position['side']}_trailing"
                                self._order_monitor_tasks[task_key] = monitor_task
                                
                                # Сохраняем информацию о трейлинг-стопе
                                trailing_info = {
                                    'order_id': trailing_order_id,
                                    'symbol': symbol,
                                    'position_side': position['side'],
                                    'current_contracts': float(position['contracts'])
                                }
                                self._order_monitor_tasks[f"{symbol}_trailing_info"] = trailing_info
                            else:
                                logger.warning(f"Трейлинг-стоп был создан, но ID не получен. Ответ: {trailing_order}")
                                
                        except Exception as e:
                            logger.error(f"Ошибка при установке трейлинг-стопа: {e}")
                    
                    return True
                
                # Проверяем, не отменен ли ордер
                if order['status'] == 'canceled':
                    logger.warning(f"Ордер {order_id} был отменен")
                    # Удаляем мониторинг для этого символа
                    if symbol_monitor_key in self._order_monitor_tasks:
                        del self._order_monitor_tasks[symbol_monitor_key]
                    return False
                
                await asyncio.sleep(1)  # Пауза между проверками
            
            # Если прошло 10 минут, отменяем ордер
            logger.warning(f"Ордер {order_id} не исполнен за 10 минут, отменяем")
            try:
                await self.cancel_order(order_id, symbol)
            except Exception as cancel_error:
                logger.error(f"Ошибка при отмене ордера {order_id}: {cancel_error}")
            
            # Удаляем мониторинг для этого символа
            if symbol_monitor_key in self._order_monitor_tasks:
                del self._order_monitor_tasks[symbol_monitor_key]
                
            return False
            
        except Exception as e:
            logger.error(f"Ошибка при мониторинге ордера {order_id}: {e}")
            # В случае ошибки очищаем задачи мониторинга для этого символа
            await self.force_clean_monitoring_tasks(symbol)
            return False
        finally:
            # Удаляем задачу из словаря
            if order_id in self._order_monitor_tasks:
                del self._order_monitor_tasks[order_id]

    async def create_market_order(self, 
                                symbol: str, 
                                side: str, 
                                amount: float, 
                                price: float = None,
                                stop_loss: float = None,
                                trail_activation: float = None,
                                trail_callback: float = None,
                                force: bool = False) -> Dict:
        """
        Создает рыночный ордер с указанными параметрами и стоп-лоссом.
        
        Args:
            symbol: Торговый символ
            side: Сторона сделки ('buy' или 'sell')
            amount: Объем сделки в базовой валюте
            price: Цена для расчета quoteSize (опционально для рыночных ордеров)
            stop_loss: Цена стоп-лосса
            trail_activation: Активационная цена для трейлинг-стопа
            trail_callback: Процент отклонения для трейлинг-стопа
            force: Принудительное создание ордера, даже если есть блокирующие факторы
            
        Returns:
            Dict: Информация о созданном ордере
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            position_side = "long" if side == "buy" else "short"
            
            # Проверяем позиции перед выполнением любых действий
            positions = await self.fetch_positions(formatted_symbol)
            has_real_position = False
            
            for pos in positions:
                if float(pos['contracts']) > 0:
                    has_real_position = True
                    break
            
            # Если система считает, что есть мониторинг, но реальных позиций нет - очищаем задачи
            is_monitored = await self.is_symbol_being_monitored(formatted_symbol)
            if is_monitored and not has_real_position:
                logger.warning(f"Обнаружено несоответствие: символ {formatted_symbol} отслеживается, но реальных позиций нет.")
                logger.warning(f"Выполняется принудительная очистка задач мониторинга для {formatted_symbol}")
                cleaned = await self.force_clean_monitoring_tasks(formatted_symbol)
                logger.info(f"Очищено {cleaned} задач мониторинга для {formatted_symbol}")
                # После очистки задач мониторинга, продолжаем выполнение
            
            # Проверяем возможность открытия ордера, если не указан флаг force
            # После очистки задач мониторинга эта проверка не должна блокировать открытие
            if not force:
                can_open = await self.can_open_orders(formatted_symbol)
                if not can_open:
                    # Пробуем еще раз принудительно очистить задачи мониторинга
                    logger.warning(f"Невозможно открыть ордер для {formatted_symbol}. Пробуем повторную очистку задач...")
                    await self.force_clean_monitoring_tasks(formatted_symbol)
                    
                    # И проверяем снова
                    can_open = await self.can_open_orders(formatted_symbol)
                    if not can_open:
                        logger.error(f"Невозможно открыть ордер для {formatted_symbol} даже после очистки задач")
                        raise ValueError(f"Невозможно открыть ордер для {formatted_symbol}. Закройте существующие позиции и ордера или используйте force=True")
            
            # Проверяем, есть ли открытые ордера для данного символа
            open_orders = await self.fetch_open_orders(formatted_symbol)
            if open_orders:
                logger.warning(f"Обнаружены открытые ордера для {formatted_symbol}. Отменяем их перед созданием нового ордера.")
                
                # Проверяем, есть ли среди открытых ордеров трейлинг-стопы, и отменяем их по ID
                for order in open_orders:
                    if 'trailing' in str(order.get('type', '')).lower() or 'trailing' in str(order.get('info', {}).get('ordType', '')).lower():
                        logger.info(f"Отменяем трейлинг-стоп {order['id']} для {formatted_symbol}")
                        await self.cancel_trailing_stop_by_id(order['id'], formatted_symbol)
                
                # Отменяем все открытые ордера для данного символа
                await self.cancel_all_orders(formatted_symbol)
                # Немного ждем, чтобы биржа успела обработать отмену
                await asyncio.sleep(1)
                
            # Проверяем и отменяем любые задачи мониторинга для этого символа
            canceled_tasks = await self.cancel_trailing_stop_tasks(formatted_symbol)
            if canceled_tasks > 0:
                logger.warning(f"Отменено {canceled_tasks} задач мониторинга для {formatted_symbol} перед открытием новой позиции")
            
            # Проверяем трейлинг-стопы по их ID из словаря мониторинга
            trailing_info_key = f"{formatted_symbol}_trailing_info"
            if trailing_info_key in self._order_monitor_tasks:
                trailing_info = self._order_monitor_tasks[trailing_info_key]
                trail_order_id = trailing_info.get('order_id')
                if trail_order_id:
                    logger.warning(f"Обнаружен активный трейлинг-стоп {trail_order_id} для {formatted_symbol}. Отменяем его.")
                    await self.cancel_trailing_stop_by_id(trail_order_id, formatted_symbol)
            
            # Получаем актуальные данные о цене
            ticker_data = await self.get_ticker_price(formatted_symbol)
            current_price = ticker_data['mark']  # Используем mark price для расчетов
            
            # Рассчитываем quoteSize (сумма в USDT)
            amount = round(amount, 6)
            quote_size = amount * current_price
            quote_size = round(quote_size, 8)
            
            # Проверяем минимальный размер ордера (1 USDT)
            if quote_size < 1:
                amount = 1 / current_price
                amount = round(amount, 6)
                quote_size = 1
            
            # Форматируем значения для избежания научной нотации
            amount_str = f"{amount:.6f}".rstrip('0').rstrip('.') if '.' in f"{amount:.6f}" else f"{amount:.6f}"
            quote_size_str = f"{quote_size:.8f}".rstrip('0').rstrip('.') if '.' in f"{quote_size:.8f}" else f"{quote_size:.8f}"
            
            logger.info(f"Создание ордера: baseSize={amount_str}, quoteSize={quote_size_str} USDT, mark price={current_price}")
            
            # Базовые параметры ордера для фьючерсов
            order_params = {
                "marginMode": "isolated",
                "marginCoin": "USDT",
                "positionSide": position_side,
                "timeInForce": "GTC",
                "baseSize": amount_str,
                "quoteSize": quote_size_str
            }
            
            # Добавляем стоп-лосс если указан
            if stop_loss:
                stop_price_str = f"{stop_loss:.2f}"
                logger.info(f"Добавлен стоп-лосс: {stop_price_str}")
                order_params["stopLoss"] = {
                    "triggerPrice": stop_loss,
                    "price": stop_loss,
                }
            
            # Создаем рыночный ордер
            order = await self.exchange.create_order(
                symbol=formatted_symbol,
                type="market",
                side=side,
                amount=amount,
                params=order_params
            )
            
            logger.info(f"Создан рыночный ордер {side.upper()} для {formatted_symbol} на объем {amount_str}")
            
            # Запускаем мониторинг исполнения ордера
            if trail_activation and trail_callback:
                logger.info(f"Установлены параметры для трейлинг-стопа: активация={trail_activation}, шаг={trail_callback}")
                
                monitor_task = asyncio.create_task(
                    self._monitor_order_execution(
                        order['id'],
                        formatted_symbol,
                        trail_activation,
                        trail_callback
                    )
                )
                self._order_monitor_tasks[order['id']] = monitor_task
                
                # Добавляем ключ мониторинга для этого символа
                symbol_key = f"{formatted_symbol}_monitoring"
                self._order_monitor_tasks[symbol_key] = True
            
            return order
            
        except Exception as e:
            logger.error(f"Ошибка при создании рыночного ордера для {symbol}: {e}")
            raise
            
    async def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200, params: Optional[Dict] = None) -> List:
        """
        Получает OHLCV данные для указанного символа и таймфрейма.
        
        Args:
            symbol: Торговый символ
            timeframe: Таймфрейм
            limit: Максимальное количество свечей (по умолчанию 200, максимум 1000)
            params: Дополнительные параметры запроса
            
        Returns:
            List: Список OHLCV свечей
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            default_params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            
            # Применяем пользовательские параметры
            if params:
                default_params.update(params)
            
            # Ограничиваем limit до 1000 свечей (API ограничение Bitget)
            if limit > 1000:
                logger.warning(f"Запрошено слишком много свечей ({limit}), ограничиваем до 1000")
                limit = 1000
                
            logger.info(f"Запрос {limit} OHLCV свечей для {formatted_symbol} на таймфрейме {timeframe}")
            
            ohlcv = await self.exchange.fetch_ohlcv(
                symbol=formatted_symbol,
                timeframe=timeframe,
                limit=limit,
                params=default_params
            )
            
            logger.info(f"Получено {len(ohlcv)} OHLCV свечей для {formatted_symbol}")
            
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
            params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            if symbol:
                formatted_symbol = self._format_symbol(symbol)
                return await self.exchange.fetch_open_orders(symbol=formatted_symbol, params=params)
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
            params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            if symbol:
                formatted_symbol = self._format_symbol(symbol)
                params["symbol"] = formatted_symbol
                
            positions = await self.exchange.fetch_positions(params=params)
            
            # Проверяем и очищаем неактивные трейлинг-стопы из словаря
            await self._cleanup_inactive_trailing_stops(positions, symbol)
            
            return positions
        except Exception as e:
            logger.error(f"Ошибка при получении открытых позиций: {e}")
            return []
    
    async def _cleanup_inactive_trailing_stops(self, positions: List, target_symbol: Optional[str] = None):
        """
        Очищает словарь мониторинга от трейлинг-стопов для символов без активных позиций.
        
        Args:
            positions: Список активных позиций
            target_symbol: Целевой символ для очистки (опционально)
        """
        try:
            # Создаем множество символов с активными позициями
            active_symbols = set()
            for position in positions:
                if float(position.get('contracts', 0)) > 0:
                    symbol = position['symbol']
                    # Удаляем суффикс ':USDT' если он присутствует
                    if ':' in symbol:
                        symbol = symbol.split(':')[0]
                    formatted_symbol = self._format_symbol(symbol)
                    active_symbols.add(formatted_symbol)
            
            # Проверяем трейлинг-стопы в словаре мониторинга
            trailing_keys_to_remove = []
            
            for key in list(self._order_monitor_tasks.keys()):
                if key.endswith('_trailing_info'):
                    # Извлекаем символ из ключа
                    symbol_from_key = key.replace('_trailing_info', '')
                    
                    # Если указан целевой символ, проверяем только его
                    if target_symbol:
                        target_formatted = self._format_symbol(target_symbol)
                        if symbol_from_key != target_formatted:
                            continue
                    
                    # Если для этого символа нет активной позиции, помечаем ключ для удаления
                    if symbol_from_key not in active_symbols:
                        trailing_keys_to_remove.append(key)
                        logger.info(f"Обнаружен неактивный трейлинг-стоп для {symbol_from_key} - позиция закрыта")
            
            # Удаляем неактивные ключи
            for key in trailing_keys_to_remove:
                if key in self._order_monitor_tasks:
                    trailing_info = self._order_monitor_tasks[key]
                    trail_order_id = trailing_info.get('order_id')
                    symbol_name = key.replace('_trailing_info', '')
                    
                    logger.info(f"Удаляем неактивный трейлинг-стоп {trail_order_id} для {symbol_name} из словаря мониторинга")
                    del self._order_monitor_tasks[key]
                    
                    # Также отменяем связанные задачи мониторинга
                    await self.cancel_trailing_stop_tasks(symbol_name)
                    
        except Exception as e:
            logger.error(f"Ошибка при очистке неактивных трейлинг-стопов: {e}")
    
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
            formatted_symbol = self._format_symbol(symbol)
            params = {
                "instType": "swap",
                "marginCoin": "USDT"
            }
            result = await self.exchange.cancel_order(order_id, formatted_symbol, params=params)
            logger.info(f"Ордер {order_id} для {formatted_symbol} отменен")
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
            
            # Также отменяем все задачи мониторинга по данному символу
            if symbol:
                canceled_tasks = await self.cancel_trailing_stop_tasks(symbol)
                if canceled_tasks > 0:
                    logger.info(f"Отменено {canceled_tasks} задач мониторинга для {symbol} при отмене всех ордеров")
            
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
            
            # Удаляем суффикс ':USDT' если он присутствует
            if ':' in symbol:
                symbol = symbol.split(':')[0]
                
            formatted_symbol = self._format_symbol(symbol)
            contracts = float(position['contracts'])
            
            if contracts <= 0:
                logger.warning(f"Позиция {formatted_symbol} уже закрыта (объем = {contracts})")
                # Отменяем задачи мониторинга даже если позиция уже закрыта
                await self.cancel_trailing_stop_tasks(formatted_symbol)
                return True
            
            # Перед закрытием позиции отменяем все трейлинг-стопы по ID
            try:
                trailing_info_key = f"{formatted_symbol}_trailing_info"
                if trailing_info_key in self._order_monitor_tasks:
                    trailing_info = self._order_monitor_tasks[trailing_info_key]
                    trail_order_id = trailing_info.get('order_id')
                    if trail_order_id:
                        await self.cancel_trailing_stop_by_id(trail_order_id, formatted_symbol)
            except Exception as e:
                logger.error(f"Ошибка при отмене трейлинг-стопа по ID перед закрытием позиции: {e}")
                
            side = 'sell' if position['side'] == 'long' else 'buy'
            
            # Получаем mark price из позиции для расчета quoteSize
            mark_price = float(position.get('markPrice', 0))
            contracts = round(contracts, 6)
            quote_size = contracts * mark_price if mark_price > 0 else 0
            quote_size = round(quote_size, 8)
            
            # Форматируем значения для избежания научной нотации
            contracts_str = f"{contracts:.6f}".rstrip('0').rstrip('.') if '.' in f"{contracts:.6f}" else f"{contracts:.6f}"
            quote_size_str = f"{quote_size:.8f}".rstrip('0').rstrip('.') if '.' in f"{quote_size:.8f}" else f"{quote_size:.8f}"
            
            logger.info(f"Закрытие позиции {formatted_symbol}: контракты={contracts_str}, сумма={quote_size_str} USDT")
            
            # Параметры для закрытия позиции
            params = {
                'instType': 'swap',
                'marginCoin': 'USDT',
                'positionSide': position['side'],
                'marginMode': 'isolated',
                'loanType': 'normal',
                'baseSize': contracts_str,
                'quoteSize': quote_size_str,
                'priceType': 'market'
            }
            
            await self.exchange.create_order(
                symbol=formatted_symbol,
                type='market',
                side=side,
                amount=contracts,
                params=params
            )
            
            logger.info(f"Позиция {formatted_symbol} ({position['side']}) успешно закрыта")
            
            # Отменяем все задачи мониторинга для этого символа после закрытия позиции
            canceled_tasks = await self.cancel_trailing_stop_tasks(formatted_symbol)
            if canceled_tasks > 0:
                logger.info(f"Отменено {canceled_tasks} задач мониторинга для {formatted_symbol} после закрытия позиции")
            
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
            
            # Отменяем все оставшиеся задачи мониторинга после закрытия всех позиций
            remaining_tasks = await self.cancel_trailing_stop_tasks()
            if remaining_tasks > 0:
                logger.warning(f"Отменено {remaining_tasks} оставшихся задач мониторинга после закрытия всех позиций")
                        
            return closed_count
        except Exception as e:
            logger.error(f"Ошибка при закрытии всех позиций: {e}")
            return 0
    
    async def fetch_trailing_stop_status(self, trailing_order_id: str, symbol: str) -> Dict:
        """
        Проверяет статус трейлинг-стоп ордера по ID.
        
        Args:
            trailing_order_id: ID трейлинг-стоп ордера
            symbol: Торговый символ
            
        Returns:
            Dict: Информация о статусе трейлинг-стоп ордера или None, если ордер не найден
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            order_status = await self.exchange.fetch_order(trailing_order_id, formatted_symbol)
            logger.debug(f"Статус трейлинг-стопа {trailing_order_id}: {order_status}")
            return order_status
        except Exception as e:
            logger.error(f"Ошибка при получении статуса трейлинг-стопа {trailing_order_id}: {e}")
            return None

    async def cancel_trailing_stop_tasks(self, symbol: str = None) -> int:
        """
        Отменяет задачи мониторинга трейлинг-стопа для указанного символа или все задачи.
        
        Args:
            symbol: Торговый символ (опционально)
            
        Returns:
            int: Количество отмененных задач
        """
        canceled_count = 0
        tasks_to_cancel = []
        
        try:
            # Если символ указан, ищем только задачи для этого символа
            if symbol:
                formatted_symbol = self._format_symbol(symbol)
                for task_key in list(self._order_monitor_tasks.keys()):
                    # Проверяем, относится ли задача к указанному символу
                    if formatted_symbol in task_key:
                        tasks_to_cancel.append(task_key)
            else:
                # Отменяем все задачи мониторинга
                tasks_to_cancel = list(self._order_monitor_tasks.keys())
            
            # Отменяем найденные задачи
            for task_key in tasks_to_cancel:
                task = self._order_monitor_tasks.get(task_key)
                # Проверяем, что это действительно задача asyncio, а не другой тип данных
                if task and hasattr(task, 'done') and hasattr(task, 'cancelled'):
                    if not task.done() and not task.cancelled():
                        task.cancel()
                        logger.info(f"Задача мониторинга {task_key} отменена")
                        canceled_count += 1
                
                # Удаляем задачу из словаря
                if task_key in self._order_monitor_tasks:
                    del self._order_monitor_tasks[task_key]
            
            return canceled_count
        except Exception as e:
            logger.error(f"Ошибка при отмене задач мониторинга: {e}")
            return canceled_count

    # Добавим новый метод для отслеживания ордеров по символу
    def _get_symbol_monitoring_keys(self, symbol: str) -> list:
        """
        Получает ключи задач мониторинга для указанного символа.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            list: Список ключей задач мониторинга для символа
        """
        formatted_symbol = self._format_symbol(symbol) if symbol else ""
        symbol_keys = []
        
        for task_key in self._order_monitor_tasks.keys():
            if formatted_symbol and formatted_symbol in task_key:
                symbol_keys.append(task_key)
        
        return symbol_keys
        
    async def is_symbol_being_monitored(self, symbol: str) -> bool:
        """
        Проверяет, отслеживается ли указанный символ какой-либо задачей.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            bool: True если символ отслеживается, иначе False
        """
        symbol_keys = self._get_symbol_monitoring_keys(symbol)
        return len(symbol_keys) > 0 

    async def can_open_orders(self, symbol: str) -> bool:
        """
        Проверяет, можно ли открывать новые ордера по указанному символу.
        Ордера нельзя открывать, если:
        1. Есть активные задачи мониторинга для символа
        2. Есть незакрытые позиции для символа
        3. Есть открытые ордера для символа
        
        Args:
            symbol: Торговый символ
            
        Returns:
            bool: True если можно открывать новые ордера, False иначе
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            
            # Проверяем наличие задач мониторинга
            monitoring = await self.is_symbol_being_monitored(formatted_symbol)
            if monitoring:
                logger.warning(f"Символ {formatted_symbol} отслеживается задачей мониторинга, открытие ордеров запрещено")
                return False
            
            # Проверяем наличие открытых позиций
            positions = await self.fetch_positions(formatted_symbol)
            if positions and any(float(pos['contracts']) > 0 for pos in positions):
                logger.warning(f"Для символа {formatted_symbol} есть открытые позиции, открытие ордеров запрещено без закрытия существующих")
                return False
            
            # Проверяем наличие открытых ордеров
            orders = await self.fetch_open_orders(formatted_symbol)
            if orders:
                logger.warning(f"Для символа {formatted_symbol} есть открытые ордера, открытие новых ордеров запрещено")
                return False
            
            return True
        except Exception as e:
            logger.error(f"Ошибка при проверке возможности открытия ордеров для {symbol}: {e}")
            # В случае ошибки, блокируем открытие ордеров для безопасности
            return False 

    async def force_clean_monitoring_tasks(self, symbol: str = None) -> int:
        """
        Принудительно очищает все задачи мониторинга и ключи для указанного символа.
        Используется для восстановления после неожиданного закрытия позиции (например, по стоп-лоссу).
        
        Args:
            symbol: Торговый символ (если None, очищаются все задачи)
            
        Returns:
            int: Количество очищенных элементов
        """
        cleaned_count = 0
        try:
            # Получаем все ключи для удаления
            keys_to_remove = []
            trailing_ids_to_cancel = []
            
            if symbol:
                formatted_symbol = self._format_symbol(symbol)
                # Ищем все ключи, содержащие символ
                for key in list(self._order_monitor_tasks.keys()):
                    if formatted_symbol in key:
                        keys_to_remove.append(key)
                        # Если это trailing_info, сохраняем ID трейлинга для отмены через API
                        if key == f"{formatted_symbol}_trailing_info":
                            trailing_info = self._order_monitor_tasks[key]
                            trail_order_id = trailing_info.get('order_id')
                            if trail_order_id:
                                trailing_ids_to_cancel.append((trail_order_id, formatted_symbol))
            else:
                # Очищаем все ключи
                keys_to_remove = list(self._order_monitor_tasks.keys())
                # Проверяем все ключи на наличие trailing_info
                for key in keys_to_remove:
                    if key.endswith("_trailing_info"):
                        trailing_info = self._order_monitor_tasks[key]
                        trail_order_id = trailing_info.get('order_id')
                        symbol_from_key = key.replace("_trailing_info", "")
                        if trail_order_id and symbol_from_key:
                            trailing_ids_to_cancel.append((trail_order_id, symbol_from_key))
            
            # Сначала отменяем трейлинг-стопы через API
            for trail_id, symb in trailing_ids_to_cancel:
                try:
                    await self.cancel_trailing_stop_by_id(trail_id, symb)
                    logger.info(f"Принудительно отменен трейлинг-стоп {trail_id} для {symb}")
                except Exception as e:
                    logger.error(f"Ошибка при отмене трейлинг-стопа {trail_id}: {e}")
            
            # Отменяем задачи и удаляем ключи
            for key in keys_to_remove:
                task = self._order_monitor_tasks.get(key)
                # Если это задача asyncio, отменяем её
                if hasattr(task, 'cancel') and callable(task.cancel):
                    if not hasattr(task, 'done') or not task.done():
                        if not hasattr(task, 'cancelled') or not task.cancelled():
                            task.cancel()
                # Удаляем из словаря в любом случае
                del self._order_monitor_tasks[key]
                cleaned_count += 1
                logger.info(f"Принудительно удален ключ мониторинга: {key}")
            
            return cleaned_count
        except Exception as e:
            logger.error(f"Ошибка при принудительной очистке задач мониторинга: {e}")
            return cleaned_count

    async def cancel_trailing_stop_by_id(self, trailing_order_id: str, symbol: str) -> bool:
        """
        Отменяет трейлинг-стоп по его ID.
        
        Args:
            trailing_order_id: ID трейлинг-стоп ордера
            symbol: Торговый символ
            
        Returns:
            bool: True если трейлинг-стоп успешно отменен, иначе False
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            params = {
                'instType': 'swap',
                'marginCoin': 'USDT'
            }
            
            # Проверяем существование ордера перед отменой
            try:
                order_status = await self.exchange.fetch_order(trailing_order_id, formatted_symbol, params=params)
                if order_status['status'] == 'closed' or order_status['status'] == 'canceled':
                    logger.info(f"Трейлинг-стоп {trailing_order_id} для {formatted_symbol} уже {order_status['status']}")
                    return True
            except Exception as fetch_error:
                # Если ордер не найден, считаем его уже отмененным
                if "Order does not exist" in str(fetch_error):
                    logger.info(f"Трейлинг-стоп {trailing_order_id} для {formatted_symbol} не найден")
                    return True
                logger.warning(f"Ошибка при проверке статуса трейлинг-стопа {trailing_order_id}: {fetch_error}")
            
            # Отменяем ордер
            result = await self.exchange.cancel_order(trailing_order_id, formatted_symbol, params=params)
            logger.info(f"Трейлинг-стоп {trailing_order_id} для {formatted_symbol} успешно отменен")
            return True
        except Exception as e:
            logger.error(f"Ошибка при отмене трейлинг-стопа {trailing_order_id} для {symbol}: {e}")
            return False

    async def cancel_all_trailing_stops_for_symbol(self, symbol: str) -> int:
        """
        Отменяет все трейлинг-стопы для указанного символа.
        
        Args:
            symbol: Торговый символ
            
        Returns:
            int: Количество отмененных трейлинг-стопов
        """
        try:
            formatted_symbol = self._format_symbol(symbol)
            canceled_count = 0
            
            # Получаем все открытые ордера для символа
            open_orders = await self.fetch_open_orders(formatted_symbol)
            
            for order in open_orders:
                # Проверяем, является ли ордер трейлинг-стопом
                if 'trailing' in str(order.get('type', '')).lower() or 'trailing' in str(order.get('info', {}).get('ordType', '')).lower():
                    try:
                        success = await self.cancel_trailing_stop_by_id(order['id'], formatted_symbol)
                        if success:
                            canceled_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка при отмене трейлинг-стопа {order['id']}: {e}")
            
            # Также отменяем трейлинг-стопы по ID из словаря мониторинга
            trailing_info_key = f"{formatted_symbol}_trailing_info"
            if trailing_info_key in self._order_monitor_tasks:
                trailing_info = self._order_monitor_tasks[trailing_info_key]
                trail_order_id = trailing_info.get('order_id')
                if trail_order_id:
                    try:
                        success = await self.cancel_trailing_stop_by_id(trail_order_id, formatted_symbol)
                        if success:
                            canceled_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка при отмене трейлинг-стопа из мониторинга {trail_order_id}: {e}")
            
            if canceled_count > 0:
                logger.info(f"Отменено {canceled_count} трейлинг-стопов для {formatted_symbol}")
            
            return canceled_count
        except Exception as e:
            logger.error(f"Ошибка при отмене всех трейлинг-стопов для {symbol}: {e}")
            return 0

    async def _periodic_monitoring_cleanup(self):
        """
        Периодически проверяет и очищает зависшие задачи мониторинга,
        сравнивая их с реальными открытыми позициями.
        """
        try:
            while True:
                # Проверяем все задачи мониторинга
                symbols_with_monitoring = set()
                
                # Собираем все символы, для которых есть задачи мониторинга
                for key in list(self._order_monitor_tasks.keys()):
                    # Ищем ключи вида "BTCUSDT_monitoring" или "BTCUSDT_long_trailing"
                    parts = key.split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        if symbol and not symbol.isdigit():  # Исключаем ID ордеров
                            symbols_with_monitoring.add(symbol)
                
                # Проверяем реальные позиции
                for symbol in symbols_with_monitoring:
                    try:
                        positions = await self.fetch_positions(symbol)
                        has_real_position = False
                        
                        for pos in positions:
                            if float(pos['contracts']) > 0:
                                has_real_position = True
                                break
                        
                        # Если нет реальной позиции, но есть мониторинг - очищаем
                        if not has_real_position:
                            logger.warning(f"Обнаружен зависший мониторинг для {symbol} без реальной позиции. Очищаем.")
                            await self.force_clean_monitoring_tasks(symbol)
                    except Exception as e:
                        logger.error(f"Ошибка при проверке позиций для {symbol}: {e}")
                
                # Проверка выполняется каждые 5 минут
                await asyncio.sleep(300)
        except asyncio.CancelledError:
            logger.info("Задача периодической очистки мониторинга отменена")
        except Exception as e:
            logger.error(f"Ошибка в задаче периодической очистки мониторинга: {e}") 