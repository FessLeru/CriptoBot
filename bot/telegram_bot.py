"""
Модуль для работы с Telegram ботом.
"""
import os
import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.utils.markdown import hbold, hitalic, hcode, hpre

from bot_logging import logger
from trading.trader import Trader
from strategies.scanner import StrategyScanner
from utils.time_utils import get_all_supported_timeframes


class TelegramBot:
    """Класс для управления торговым ботом через Telegram."""
    
    def __init__(self, trader: Trader, scanner: StrategyScanner):
        """
        Инициализирует Telegram бота.
        
        Args:
            trader: Объект трейдера
            scanner: Объект сканера стратегий
        """
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN отсутствует в .env файле")
            
        self.bot = Bot(token=self.token)
        self.dp = Dispatcher()
        self.trader = trader
        self.scanner = scanner
        self.target_chat_id = int(os.getenv("TARGET_CHAT_ID", 0))
        
        # Лок для предотвращения гонки условий при обработке сообщений
        self._message_lock = asyncio.Lock()
        
        # Регистрируем обработчики команд
        self._register_handlers()
        
        # Регистрируем обработчик сигналов
        self.scanner.register_signal_callback(self._handle_signal)
        
        logger.info(f"Инициализирован Telegram бот. Целевой чат: {self.target_chat_id}")
    
    def _register_handlers(self) -> None:
        """Регистрирует обработчики команд."""
        # Основные команды
        self.dp.message.register(self._cmd_start, Command("start"))
        self.dp.message.register(self._cmd_balance, Command("balance"))
        self.dp.message.register(self._cmd_stop, Command("stop"))
        self.dp.message.register(self._cmd_orders, Command("orders"))
        self.dp.message.register(self._cmd_leverage, Command("leverage"))
        self.dp.message.register(self._cmd_set_chat, Command("set_chat"))
        self.dp.message.register(self._cmd_get_id, Command("get_id"))
        self.dp.message.register(self._cmd_strategies, Command("strategies"))
        
        # Новые команды
        self.dp.message.register(self._cmd_timeframe, Command("timeframe"))
        self.dp.message.register(self._cmd_scan, Command("scan"))
        self.dp.message.register(self._cmd_report, Command("report"))
        
        logger.info("Зарегистрированы обработчики команд")
    
    async def start(self) -> None:
        """Запускает бота."""
        logger.info("Запуск Telegram бота")
        await self.dp.start_polling(self.bot)
    
    async def stop(self) -> None:
        """Останавливает бота."""
        logger.info("Остановка Telegram бота")
        await self.bot.session.close()
    
    async def _handle_signal(self, signal: Dict) -> None:
        """
        Обрабатывает сигнал от сканера стратегий.
        
        Args:
            signal: Словарь с информацией о сигнале
        """
        if not self.target_chat_id:
            logger.warning("Целевой чат не установлен. Сигнал не будет отправлен.")
            return
            
        try:
            # Формируем сообщение о сигнале
            symbol = signal["symbol"]
            signal_type = "🟢 ЛОНГ" if signal["type"] == "buy" else "🔴 ШОРТ"
            price = signal["price"]
            stop_loss = signal["stop_loss"]
            trail_points = signal.get("trail_points", 0)
            trail_offset = signal.get("trail_offset", 0)
            strategy_name = signal.get("strategy_name", "Unknown")
            timeframe = signal.get("timeframe", "Unknown")
            
            message = f"""🚨 СИГНАЛ от {strategy_name}: {signal_type} на {symbol}!
💰 Цена: {price:.4f} USDT
🛑 Стоп-лосс: {stop_loss:.4f} USDT
🔄 Трейлинг-стоп: активация при {trail_points:.4f} пунктов в прибыли, шаг {trail_offset:.4f}
⏱ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔍 Таймфрейм: {timeframe}
"""
            
            # Отправляем сообщение
            await self.bot.send_message(self.target_chat_id, message)
            
            # Открываем сделку
            trade_result = await self.trader.open_trade(signal)
            await self.bot.send_message(self.target_chat_id, trade_result)
            
        except Exception as e:
            logger.error(f"Ошибка при обработке сигнала: {str(e)}")
    
    # --- Обработчики команд ---
    
    async def _cmd_start(self, message: Message) -> None:
        """Обработчик команды /start"""
        welcome_text = """
🚀 Привет! Я — торговый бот для работы с биржей Bitget!

Команды:
- 💰 Показать текущий баланс (/balance)
- 🛑 Остановить все активные сделки и 
     отменить лимитные заявки (/stop)
- 🔥 Поменять плечо (/leverage <число>)
- ✅ Посмотреть открытые позиции и 
     лимитные заявки (/orders)
- 🆔 Узнать ID чата (/get_id)
- 🔄 Установить этот чат как целевой (/set_chat)
- 📊 Список доступных стратегий (/strategies)
- ⏱ Изменить таймфрейм (/timeframe <символ> <таймфрейм>)
- 🔍 Запустить ручное сканирование (/scan <символ>)
- 📝 Получить отчет о торговле (/report)
"""
        await message.answer(welcome_text)
    
    async def _cmd_balance(self, message: Message) -> None:
        """Обработчик команды /balance"""
        try:
            async with self._message_lock:
                balance = await self.trader.exchange.get_usdt_balance()
                await message.reply(f"💰 Баланс фьючерсов: {balance:.2f} USDT")
                logger.info(f"Пользователь {message.from_user.id} запросил баланс: {balance:.2f} USDT")
        except Exception as e:
            logger.error(f"Ошибка при получении баланса: {str(e)}")
            await message.reply(f"⚠️ Ошибка при получении баланса: {str(e)}")
    
    async def _cmd_stop(self, message: Message) -> None:
        """Обработчик команды /stop"""
        try:
            async with self._message_lock:
                result = await self.trader.close_all_trades()
                
                canceled_orders = result.get("closed_orders", 0)
                closed_positions = result.get("closed_positions", 0)
                error = result.get("error", None)
                
                if error:
                    await message.reply(f"⚠️ Ошибка при закрытии сделок: {error}", parse_mode="Markdown")
                else:
                    result_message = (
                        f"✅ *Результат выполнения команды /stop:*\n\n"
                        f"📋 *Отменено ордеров:* {canceled_orders}\n"
                        f"📊 *Закрыто позиций:* {closed_positions}\n\n"
                        f"Все активные ордера отменены, позиции закрыты.\n"
                        f"Мониторинг рынка продолжает работать."
                    )
                    await message.reply(result_message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка при выполнении команды /stop: {str(e)}")
            await message.reply(f"⚠️ Ошибка при выполнении команды /stop: {str(e)}", parse_mode="Markdown")
    
    async def _cmd_orders(self, message: Message) -> None:
        """Обработчик команды /orders"""
        try:
            async with self._message_lock:
                # Получаем активные ордера
                open_orders = await self.trader.get_open_orders()
        
                # Формируем сообщение с информацией об ордерах
                orders_info = "📋 *Активные ордера:*\n\n"
                if open_orders:
                    for order in open_orders:
                        orders_info += (
                            f"🔹 *Символ:* {order['symbol']}-{order['side']}\n"
                            f"   *Направление:* {'🟢 Лонг' if order['side'] == 'buy' else '🔴 Шорт'}\n"
                            f"   *Тип ордера:* {order['type'].capitalize()}\n"
                            f"   *Цена:* {order['price']:.4f}\n"
                            f"   *Объем:* {order['amount']:.4f}\n"
                            f"   *Исполнено:* {order['filled']:.4f}\n"
                            f"   *Осталось:* {order['remaining']:.4f}\n\n"
                        )
                else:
                    orders_info += "❌ *Активных ордеров нет.*\n\n"
        
                # Получаем открытые позиции
                positions = await self.trader.get_active_positions()
                positions_info = "📊 *Открытые позиции:*\n\n"
                if positions:
                    for position in positions:
                        if float(position['contracts']) > 0:
                            symbol = position['symbol']
                            side = '🟢 Лонг' if position['side'] == 'long' else '🔴 Шорт'
                            pnl = float(position['unrealizedPnl'])
                            pnl_emoji = "📈" if pnl >= 0 else "📉"
        
                            positions_info += (
                                f"🔹 *Символ:* {symbol}\n"
                                f"   *Направление:* {side}\n"
                                f"   *Объем:* {position['contracts']:.4f}\n"
                                f"   *Цена входа:* {position['entryPrice']:.4f}\n"
                                f"   *Текущая цена:* {position['markPrice']:.4f}\n"
                                f"   *PNL:* {pnl_emoji} {pnl:.4f} USDT\n\n"
                            )
                else:
                    positions_info += "❌ *Открытых позиций нет.*\n\n"
        
                # Объединяем информацию об ордерах и позициях
                final_message = orders_info + positions_info
        
                # Отправляем сообщение пользователю
                await message.reply(final_message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка при получении списка ордеров: {str(e)}")
            await message.reply(f"⚠️ Ошибка: {str(e)}")
    
    async def _cmd_leverage(self, message: Message) -> None:
        """Обработчик команды /leverage"""
        try:
            text = message.text
            args = text.split()
            
            if len(args) != 2:
                await message.answer("⚠️ Используйте команду в формате: /leverage <число>")
                return
                
            try:
                new_leverage = int(args[1])
                
                if 1 <= new_leverage <= 100:
                    success = await self.trader.set_leverage(new_leverage)
                    if success:
                        await message.answer(f"✅ Плечо успешно изменено на {new_leverage}")
                    else:
                        await message.answer("⚠️ Не удалось изменить плечо")
                else:
                    await message.answer("⚠️ Плечо должно быть в диапазоне от 1 до 100.")
            except ValueError:
                await message.answer("⚠️ Пожалуйста, укажите корректное число после команды /leverage.")
        except Exception as e:
            logger.error(f"Ошибка при изменении плеча: {str(e)}")
            await message.reply(f"⚠️ Ошибка: {str(e)}")
    
    async def _cmd_set_chat(self, message: Message) -> None:
        """Обработчик команды /set_chat"""
        self.target_chat_id = message.chat.id
        await message.answer(f"✅ Этот чат установлен как получатель. ID: {self.target_chat_id}")
        logger.info(f"Установлен новый целевой чат: {self.target_chat_id}")
    
    async def _cmd_get_id(self, message: Message) -> None:
        """Обработчик команды /get_id"""
        chat_id = message.chat.id
        await message.answer(f"ID этого чата: <code>{chat_id}</code>", parse_mode="HTML")
    
    async def _cmd_strategies(self, message: Message) -> None:
        """Обработчик команды /strategies"""
        strategies_info = self.scanner.get_strategies_info()
        
        if not strategies_info:
            await message.reply("📊 *Стратегии не найдены*", parse_mode="Markdown")
            return
            
        response = "📈 *Доступные стратегии:*\n\n"
        
        for info in strategies_info:
            active_status = "✅ Активна" if info["active"] else "❌ Неактивна"
            response += (
                f"🔸 *Символ:* {info['symbol']}\n"
                f"   *Стратегия:* {info['name']}\n"
                f"   *Таймфрейм:* {info['timeframe']}\n"
                f"   *Статус:* {active_status}\n\n"
            )
            
        await message.reply(response, parse_mode="Markdown")
    
    async def _cmd_timeframe(self, message: Message) -> None:
        """Обработчик команды /timeframe"""
        text = message.text
        args = text.split()
        
        if len(args) != 3:
            # Выводим список доступных таймфреймов
            timeframes = get_all_supported_timeframes()
            tf_str = "\n".join([f"  • {tf} - {desc}" for tf, desc in timeframes.items()])
            
            await message.answer(
                f"⚠️ Используйте команду в формате: /timeframe <символ> <таймфрейм>\n\n"
                f"Доступные таймфреймы:\n{tf_str}"
            )
            return
            
        symbol = args[1].upper()
        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"
            
        timeframe = args[2].lower()
        
        # Изменяем таймфрейм
        success = self.scanner.set_timeframe(symbol, timeframe)
        
        if success:
            await message.answer(f"✅ Таймфрейм для {symbol} изменен на {timeframe}")
        else:
            await message.answer(f"⚠️ Не удалось изменить таймфрейм для {symbol}. Проверьте символ и таймфрейм.")
    
    async def _cmd_scan(self, message: Message) -> None:
        """Обработчик команды /scan"""
        text = message.text
        args = text.split()
        
        if len(args) != 2:
            await message.answer("⚠️ Используйте команду в формате: /scan <символ>")
            return
            
        symbol = args[1].upper()
        if not symbol.endswith("/USDT"):
            symbol = f"{symbol}/USDT"
            
        await message.answer(f"🔍 Запуск сканирования для {symbol}...")
        
        # Запускаем сканирование
        signal = await self.scanner.scan_symbol(symbol)
        
        if signal:
            await message.answer(f"✅ Найден сигнал для {symbol}: {signal['type']} по цене {signal['price']:.4f}")
        else:
            await message.answer(f"ℹ️ Сигналов для {symbol} не найдено")
    
    async def _cmd_report(self, message: Message) -> None:
        """Обработчик команды /report"""
        await message.answer("📊 TODO: Генерация отчета о торговле...")
        # В будущей реализации здесь будет вызов метода для генерации отчета 