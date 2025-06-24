#!/usr/bin/env python3
"""
Тестовый файл для работы с фьючерсами ETH и BTC на бирже Bitget
Функциональность:
1. Проверка открытых позиций и ордеров
2. Закрытие трейлинг-стопов
"""
import dotenv
dotenv.load_dotenv()
import winloop
winloop.install()
import asyncio
import ccxt.async_support as ccxt
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import json

class BitgetFuturesTest:
    """Класс для тестирования операций с фьючерсами на Bitget"""
    
    def __init__(self):
        """Инициализация подключения к бирже Bitget"""
        # Проверяем наличие API ключей
        self.api_key = os.getenv('API_KEY')
        self.secret_key = os.getenv('SECRET_KEY') 
        self.passphrase = os.getenv('PASSPHRASE')
        
        if not self.api_key or not self.secret_key or not self.passphrase:
            raise ValueError("API ключи отсутствуют. Проверьте файл .env или переменные окружения.")
        
        # Настройки подключения к бирже (аналогично основному проекту)
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
        
        # Тестируемые символы
        self.test_symbols = ['BTC/USDT', 'ETH/USDT']
        
        print(f"✅ Биржа Bitget инициализирована для фьючерсной торговли")
        
    def _format_symbol(self, symbol: str) -> str:
        """
        Преобразует символ в формат Bitget API для фьючерсов.
        Аналогично функции из основного проекта.
        
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
    
    async def check_positions_and_orders(self, symbol: str) -> Dict[str, Any]:
        """
        Проверка открытых позиций и ордеров по указанному символу
        
        Args:
            symbol (str): Символ для проверки (например, 'BTC/USDT')
            
        Returns:
            Dict: Информация о позициях и ордерах
        """
        try:
            print(f"\n{'='*60}")
            print(f"🔍 ПРОВЕРКА ПОЗИЦИЙ И ОРДЕРОВ ДЛЯ {symbol}")
            print(f"{'='*60}")
            
            result = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'positions': [],
                'orders': [],
                'trailing_stops': []
            }
            
            formatted_symbol = self._format_symbol(symbol)
            
            # 1. Проверяем открытые позиции
            print("📊 Проверка открытых позиций...")
            try:
                positions_params = {
                    'instType': 'swap',
                    'marginCoin': 'USDT',
                    'symbol': formatted_symbol
                }
                positions = await self.exchange.fetch_positions(params=positions_params)
                
                for position in positions:
                    if position['contracts'] and float(position['contracts']) != 0:
                        pos_info = {
                            'symbol': position['symbol'],
                            'side': position['side'],
                            'size': position['contracts'],
                            'entry_price': position['entryPrice'],
                            'mark_price': position['markPrice'],
                            'unrealized_pnl': position['unrealizedPnl'],
                            'percentage': position['percentage']
                        }
                        result['positions'].append(pos_info)
                        
                        print(f"  📈 Открытая позиция:")
                        print(f"     Символ: {pos_info['symbol']}")
                        print(f"     Направление: {pos_info['side']}")
                        print(f"     Размер: {pos_info['size']}")
                        print(f"     Цена входа: {pos_info['entry_price']}")
                        print(f"     Текущая цена: {pos_info['mark_price']}")
                        print(f"     Нереализованная PnL: {pos_info['unrealized_pnl']}")
                        print(f"     Процент: {pos_info['percentage']}%")
                
                if not result['positions']:
                    print("  ❌ Открытых позиций не найдено")
                    
            except Exception as pos_error:
                print(f"  ❌ Ошибка при проверке позиций: {pos_error}")
            
            # 2. Проверяем открытые ордера
            print("\n📋 Проверка открытых ордеров...")
            try:
                orders_params = {
                    'instType': 'swap',
                    'marginCoin': 'USDT'
                }
                orders = await self.exchange.fetch_open_orders(symbol=formatted_symbol, params=orders_params)
                
                for order in orders:
                    order_info = {
                        'id': order['id'],
                        'symbol': order['symbol'],
                        'type': order['type'],
                        'side': order['side'],
                        'amount': order['amount'],
                        'price': order['price'],
                        'status': order['status'],
                        'timestamp': order['timestamp'],
                        'info': order.get('info', {})
                    }
                    
                    # Проверяем, является ли это трейлинг-стопом
                    # Проверяем, является ли это трейлинг-стопом
                    is_trailing = self._is_trailing_stop(order)
                    
                    if is_trailing:
                        result['trailing_stops'].append(order_info)
                        print(f"  🎯 Трейлинг-стоп ордер:")
                        print(f"     ID: {order_info['id']}")
                        print(f"     Тип: {order_info['type']}")
                        print(f"     Направление: {order_info['side']}")
                        print(f"     Количество: {order_info['amount']}")
                        
                        # Детальная информация о трейлинг-стопе
                        if order_info.get('info'):
                            info = order_info['info']
                            trigger_price = info.get('triggerPrice', 'N/A')
                            callback_rate = info.get('callbackRatio', 'N/A')
                            trailing_percent = info.get('trailingPercent', 'N/A')
                            trailing_trigger = info.get('trailingTriggerPrice', 'N/A')
                            ord_type = info.get('ordType', 'N/A')
                            plan_type = info.get('planType', 'N/A')
                            
                            print(f"     Цена активации: {trigger_price}")
                            print(f"     Процент отката: {callback_rate}")
                            print(f"     Трейлинг процент: {trailing_percent}")
                            print(f"     Трейлинг триггер: {trailing_trigger}")
                            print(f"     Тип ордера (ordType): {ord_type}")
                            print(f"     Тип плана (planType): {plan_type}")
                    else:
                        result['orders'].append(order_info)
                        print(f"  📄 Обычный ордер:")
                        print(f"     ID: {order_info['id']}")
                        print(f"     Тип: {order_info['type']}")
                        print(f"     Направление: {order_info['side']}")
                        print(f"     Количество: {order_info['amount']}")
                        print(f"     Цена: {order_info['price']}")
                        
                        # Для отладки - показываем дополнительную информацию
                        if order_info.get('info'):
                            info = order_info['info']
                            ord_type = info.get('ordType', 'N/A')
                            plan_type = info.get('planType', 'N/A')
                            if ord_type != 'N/A' or plan_type != 'N/A':
                                print(f"     [DEBUG] ordType: {ord_type}, planType: {plan_type}")
                
                if not orders:
                    print("  ❌ Открытых ордеров не найдено")
                    
            except Exception as order_error:
                print(f"  ❌ Ошибка при проверке ордеров: {order_error}")
            
            # 3. Статистика
            print(f"\n📊 СТАТИСТИКА:")
            print(f"   • Открытых позиций: {len(result['positions'])}")
            print(f"   • Обычных ордеров: {len(result['orders'])}")
            print(f"   • Трейлинг-стопов: {len(result['trailing_stops'])}")
            
            return result
            
        except Exception as e:
            print(f"❌ Критическая ошибка при проверке позиций и ордеров для {symbol}: {e}")
            return {'error': str(e), 'symbol': symbol}
    
    def _is_trailing_stop(self, order: Dict) -> bool:
        """
        Определяет, является ли ордер трейлинг-стопом
        Использует ту же логику, что и в основном проекте
        
        Args:
            order (Dict): Информация об ордере
            
        Returns:
            bool: True если это трейлинг-стоп
        """
        order_info = order.get('info', {})
        order_type = order.get('type', '')
        
        # Проверяем различные признаки трейлинг-стопа в Bitget API
        # Аналогично логике из основного проекта
        trailing_indicators = [
            # Проверяем тип ордера
            'trailing' in str(order_type).lower(),
            'trailing' in str(order_info.get('ordType', '')).lower(),
            
            # Проверяем параметры трейлинг-стопа
            'trailingPercent' in order_info,
            'callbackRatio' in order_info,
            order_info.get('trailingTriggerPrice') is not None,
            
            # Проверяем различные типы ордеров Bitget
            order.get('type') == 'trailing_stop',
            order_info.get('orderType') == 'trailing_stop',
            order_info.get('planType') == 'trailing_stop', 
            order_info.get('ordType') == 'trailing_stop',
            
            # Проверяем строковые индикаторы
            'trailing' in str(order_info).lower(),
            'callback' in str(order_info).lower() and order_info.get('triggerType') == 'mark_price',
            
            # Дополнительные проверки для Bitget API
            order_info.get('force') == 'gtc' and 'trailing' in str(order_info).lower(),
            order_info.get('planCategory') == 'tpsl' and 'callback' in str(order_info).lower()
        ]
        
        return any(trailing_indicators)
    
    async def close_trailing_stop(self, symbol: str, order_id: str = None) -> Dict[str, Any]:
        """
        Закрытие трейлинг-стопа по символу или конкретному ID
        
        Args:
            symbol (str): Символ торговой пары
            order_id (str, optional): ID конкретного ордера для закрытия
            
        Returns:
            Dict: Результат операции закрытия
        """
        try:
            print(f"\n{'='*60}")
            print(f"🎯 ЗАКРЫТИЕ ТРЕЙЛИНГ-СТОПОВ ДЛЯ {symbol}")
            print(f"{'='*60}")
            
            result = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'closed_orders': [],
                'errors': []
            }
            
            formatted_symbol = self._format_symbol(symbol)
            
            # Получаем все открытые ордера
            try:
                orders_params = {
                    'instType': 'swap',
                    'marginCoin': 'USDT'
                }
                orders = await self.exchange.fetch_open_orders(symbol=formatted_symbol, params=orders_params)
                trailing_stops = [order for order in orders if self._is_trailing_stop(order)]
                
                if not trailing_stops:
                    print("❌ Трейлинг-стопы не найдены")
                    return result
                
                print(f"🔍 Найдено {len(trailing_stops)} трейлинг-стопов")
                
                # Если указан конкретный ID, фильтруем по нему
                if order_id:
                    trailing_stops = [order for order in trailing_stops if order['id'] == order_id]
                    if not trailing_stops:
                        error_msg = f"Трейлинг-стоп с ID {order_id} не найден"
                        print(f"❌ {error_msg}")
                        result['errors'].append(error_msg)
                        return result
                
                # Закрываем каждый трейлинг-стоп
                for order in trailing_stops:
                    try:
                        print(f"\n🗑️ Закрытие трейлинг-стопа:")
                        print(f"   ID: {order['id']}")
                        print(f"   Символ: {order['symbol']}")
                        print(f"   Направление: {order['side']}")
                        print(f"   Количество: {order['amount']}")
                        
                        # Отменяем ордер с правильными параметрами
                        cancel_params = {
                            'instType': 'swap',
                            'marginCoin': 'USDT'
                        }
                        cancel_result = await self.exchange.cancel_order(order['id'], formatted_symbol, params=cancel_params)
                        
                        result['closed_orders'].append({
                            'order_id': order['id'],
                            'symbol': order['symbol'],
                            'side': order['side'],
                            'amount': order['amount'],
                            'cancel_result': cancel_result,
                            'status': 'success'
                        })
                        
                        print(f"   ✅ Успешно закрыт")
                        
                    except Exception as order_error:
                        error_msg = f"Ошибка при закрытии ордера {order['id']}: {order_error}"
                        print(f"   ❌ {error_msg}")
                        result['errors'].append(error_msg)
                
                # Статистика
                success_count = len(result['closed_orders'])
                error_count = len(result['errors'])
                
                print(f"\n📊 РЕЗУЛЬТАТ ЗАКРЫТИЯ:")
                print(f"   ✅ Успешно закрыто: {success_count}")
                print(f"   ❌ Ошибок: {error_count}")
                
            except Exception as fetch_error:
                error_msg = f"Ошибка при получении ордеров: {fetch_error}"
                print(f"❌ {error_msg}")
                result['errors'].append(error_msg)
            
            return result
            
        except Exception as e:
            error_msg = f"Критическая ошибка при закрытии трейлинг-стопов: {e}"
            print(f"❌ {error_msg}")
            return {'error': error_msg, 'symbol': symbol}
    
    async def close_all_trailing_stops(self) -> Dict[str, Any]:
        """
        Закрытие всех трейлинг-стопов по всем тестируемым символам
        
        Returns:
            Dict: Общий результат операции
        """
        print(f"\n{'='*60}")
        print("🚨 МАССОВОЕ ЗАКРЫТИЕ ВСЕХ ТРЕЙЛИНГ-СТОПОВ")
        print(f"{'='*60}")
        
        total_result = {
            'timestamp': datetime.now().isoformat(),
            'symbols_processed': [],
            'total_closed': 0,
            'total_errors': 0
        }
        
        for symbol in self.test_symbols:
            print(f"\n🔄 Обработка символа: {symbol}")
            symbol_result = await self.close_trailing_stop(symbol)
            
            total_result['symbols_processed'].append(symbol_result)
            total_result['total_closed'] += len(symbol_result.get('closed_orders', []))
            total_result['total_errors'] += len(symbol_result.get('errors', []))
            
            # Пауза между символами
            await asyncio.sleep(0.5)
        
        print(f"\n{'='*60}")
        print("📊 ОБЩАЯ СТАТИСТИКА:")
        print(f"   🎯 Обработано символов: {len(self.test_symbols)}")
        print(f"   ✅ Всего закрыто: {total_result['total_closed']}")
        print(f"   ❌ Всего ошибок: {total_result['total_errors']}")
        print(f"{'='*60}")
        
        return total_result
    
    async def debug_order_structure(self, symbol: str) -> None:
        """
        Отладочная функция для анализа структуры ордеров
        
        Args:
            symbol (str): Символ для анализа
        """
        try:
            print(f"\n{'='*60}")
            print(f"🔬 ОТЛАДКА СТРУКТУРЫ ОРДЕРОВ ДЛЯ {symbol}")
            print(f"{'='*60}")
            
            formatted_symbol = self._format_symbol(symbol)
            
            orders_params = {
                'instType': 'swap',
                'marginCoin': 'USDT'
            }
            orders = await self.exchange.fetch_open_orders(symbol=formatted_symbol, params=orders_params)
            
            if not orders:
                print("❌ Открытых ордеров не найдено для отладки")
                return
            
            for i, order in enumerate(orders, 1):
                print(f"\n🔍 ОРДЕР #{i}:")
                print(f"   ID: {order.get('id')}")
                print(f"   Type: {order.get('type')}")
                print(f"   Side: {order.get('side')}")
                print(f"   Amount: {order.get('amount')}")
                print(f"   Price: {order.get('price')}")
                print(f"   Status: {order.get('status')}")
                
                # Полная структура info
                info = order.get('info', {})
                print(f"\n   📄 Полная структура 'info':")
                for key, value in info.items():
                    print(f"      {key}: {value}")
                
                # Результат проверки на трейлинг-стоп
                is_trailing = self._is_trailing_stop(order)
                print(f"\n   🎯 Является трейлинг-стопом: {'ДА' if is_trailing else 'НЕТ'}")
                
                print("-" * 50)
                
        except Exception as e:
            print(f"❌ Ошибка при отладке структуры ордеров: {e}")

    async def get_balance_info(self) -> Dict[str, Any]:
        """
        Получение информации о балансе USDT на фьючерсном счете
        
        Returns:
            Dict: Информация о балансе
        """
        try:
            print(f"\n{'='*60}")
            print("💰 ИНФОРМАЦИЯ О БАЛАНСЕ")
            print(f"{'='*60}")
            
            balance_params = {
                'instType': 'swap',
                'marginCoin': 'USDT'
            }
            balance = await self.exchange.fetch_balance(balance_params)
            
            usdt_balance = balance['total'].get('USDT', 0)
            usdt_free = balance['free'].get('USDT', 0)
            usdt_used = balance['used'].get('USDT', 0)
            
            print(f"📊 Баланс USDT:")
            print(f"   • Общий: {usdt_balance:.4f} USDT")
            print(f"   • Свободный: {usdt_free:.4f} USDT")
            print(f"   • Используемый: {usdt_used:.4f} USDT")
            
            return {
                'total': usdt_balance,
                'free': usdt_free,
                'used': usdt_used,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"❌ Ошибка при получении баланса: {e}")
            return {'error': str(e)}
    
    async def run_comprehensive_test(self):
        """Запуск полного тестирования для всех символов"""
        print("🚀 ЗАПУСК КОМПЛЕКСНОГО ТЕСТИРОВАНИЯ ФЬЮЧЕРСОВ BITGET")
        print(f"📅 Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Символы: {', '.join(self.test_symbols)}")
        
        try:
            # 1. Проверяем баланс
            await self.get_balance_info()
            
            # 2. Проверяем позиции и ордера для всех символов
            for symbol in self.test_symbols:
                await self.check_positions_and_orders(symbol)
                await asyncio.sleep(1)  # Пауза между запросами
            
            # 3. Показываем меню действий
            print(f"\n{'='*60}")
            print("🎮 ДОСТУПНЫЕ ДЕЙСТВИЯ:")
            print("1. Закрыть трейлинг-стопы для BTC")
            print("2. Закрыть трейлинг-стопы для ETH") 
            print("3. Закрыть ВСЕ трейлинг-стопы")
            print("4. Перепроверить позиции и ордера")
            print("5. Показать баланс")
            print("6. 🔬 Отладка структуры ордеров BTC")
            print("7. 🔬 Отладка структуры ордеров ETH")
            print("8. Выход")
            print(f"{'='*60}")
            
            while True:
                choice = input("\n🔢 Выберите действие (1-8): ").strip()
                
                if choice == '1':
                    await self.close_trailing_stop('BTC/USDT')
                elif choice == '2':
                    await self.close_trailing_stop('ETH/USDT')
                elif choice == '3':
                    await self.close_all_trailing_stops()
                elif choice == '4':
                    for symbol in self.test_symbols:
                        await self.check_positions_and_orders(symbol)
                        await asyncio.sleep(0.5)
                elif choice == '5':
                    await self.get_balance_info()
                elif choice == '6':
                    await self.debug_order_structure('BTC/USDT')
                elif choice == '7':
                    await self.debug_order_structure('ETH/USDT')
                elif choice == '8':
                    print("👋 Завершение тестирования")
                    break
                else:
                    print("❌ Неверный выбор. Попробуйте снова.")
                
                await asyncio.sleep(0.5)
                
        except KeyboardInterrupt:
            print("\n🛑 Тестирование прервано пользователем")
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.exchange.close()
            print("🔒 Соединение с биржей закрыто")

async def main():
    """Главная функция для запуска тестов"""
    print("🎯 ТЕСТИРОВАНИЕ ФЬЮЧЕРСНЫХ ОПЕРАЦИЙ BITGET")
    print("=" * 60)
    
    # Проверяем наличие переменных окружения
    required_vars = ['API_KEY', 'SECRET_KEY', 'PASSPHRASE']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("⚠️ ВНИМАНИЕ: Не установлены переменные окружения:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n💡 Убедитесь, что файл .env содержит:")
        print("   API_KEY=your_api_key")
        print("   SECRET_KEY=your_secret_key") 
        print("   PASSPHRASE=your_passphrase")
        return
    
    # Создаем и запускаем тестер
    try:
        tester = BitgetFuturesTest()
        await tester.run_comprehensive_test()
    except Exception as e:
        print(f"❌ Ошибка при инициализации тестера: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Запуск асинхронного тестирования
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Критическая ошибка при запуске: {e}")
        import traceback
        traceback.print_exc() 