"""
API Client для интеграции с основным ботом McQueen Connection
Обертка для safe_integration с дополнительными методами
"""

import logging
from typing import Optional, List, Dict, Any

from safe_integration import safe_main_bot

logger = logging.getLogger(__name__)

class MainBotAPIClient:
    """API клиент для работы с основным ботом через safe integration"""
    
    def __init__(self):
        self.integration = safe_main_bot
        
    async def get_user_info(self, tg_id: int) -> Optional[Dict]:
        """Получение информации о пользователе"""
        try:
            user_info = await self.integration.get_user_info(tg_id)
            
            # Проверяем различные случаи отсутствия пользователя
            if user_info is None:
                logger.warning(f"Пользователь {tg_id} не найден (None)")
                return None
            
            # Проверяем на словарь с ошибкой
            if isinstance(user_info, dict) and "error" in user_info:
                logger.warning(f"Пользователь {tg_id} не найден (error: {user_info['error']})")
                return None
            
            # Проверяем на пустой словарь или отсутствие ключевых данных
            if not isinstance(user_info, dict) or not user_info.get('tg_id'):
                logger.warning(f"Пользователь {tg_id} не найден или данные неполные")
                return None
            
            return user_info
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {tg_id}: {e}")
            return None
    
    async def get_user_keys(self, tg_id: int) -> Optional[List[Dict]]:
        """Получение ключей пользователя"""
        try:
            keys = await self.integration.get_user_keys(tg_id)
            if not keys:
                return []
            else:
                return keys
        except Exception as e:
            logger.error(f"Ошибка получения ключей пользователя {tg_id}: {e}")
            return []
    
    async def check_user_exists(self, tg_id: int) -> bool:
        """Проверка существования пользователя"""
        return await self.integration.check_user_exists(tg_id)
    
    async def get_user_subscription_status(self, tg_id: int) -> Optional[Dict]:
        """Получение статуса подписки пользователя"""
        try:
            status = await self.integration.get_user_subscription_status(tg_id)
            if "error" not in status:
                return status
            else:
                logger.warning(f"Ошибка получения статуса подписки для {tg_id}: {status['error']}")
                return None
        except Exception as e:
            logger.error(f"Ошибка получения статуса подписки {tg_id}: {e}")
            return None
    
    def get_telegram_user_info(self, telegram_user) -> Dict:
        """Извлекает базовую информацию из объекта Telegram User"""
        if not telegram_user:
            return {}
        
        return {
            'tg_id': telegram_user.id,
            'username': telegram_user.username,
            'first_name': telegram_user.first_name,
            'last_name': telegram_user.last_name,
            'language_code': getattr(telegram_user, 'language_code', None),
            'is_premium': getattr(telegram_user, 'is_premium', False)
        }

    async def format_user_info(self, tg_id: int, telegram_user=None) -> str:
        """Форматирование информации о пользователе для отображения"""
        # Сначала проверяем, существует ли пользователь в системе
        is_registered = await self.check_user_exists(tg_id)
        
        user_info = None
        user_keys = []
        
        if is_registered:
            user_info = await self.get_user_info(tg_id)
            user_keys = await self.get_user_keys(tg_id)
            
            # Дополнительная проверка - если user_info пустой, значит пользователь не зарегистрирован
            if not user_info or not user_info.get('tg_id'):
                is_registered = False
        
        # Функция для экранирования HTML символов
        def escape_html(text):
            if text is None:
                return 'N/A'
            return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Начинаем с базовой информации
        info_text = "👤 <b>Информация о пользователе:</b>\n"
        info_text += f"🆔 <b>Telegram ID:</b> <code>{tg_id}</code>\n"
        
        # Статус регистрации
        if is_registered:
            info_text += f"✅ <b>Статус:</b> Зарегистрирован в боте\n"
        else:
            info_text += f"❌ <b>Статус:</b> НЕ зарегистрирован в боте\n"
        
        # Получаем данные: сначала из БД, потом из Telegram
        if is_registered and user_info:
            # Используем данные из БД
            username = user_info.get('username')
            first_name = user_info.get('first_name', 'N/A')
            last_name = user_info.get('last_name', '')
        else:
            # Используем данные из Telegram, если доступны
            if telegram_user:
                username = telegram_user.username
                first_name = telegram_user.first_name or 'N/A'
                last_name = telegram_user.last_name or ''
            else:
                username = None
                first_name = 'N/A'
                last_name = ''
        
        # Отображаем контактную информацию
        if username:
            info_text += f"👨‍💼 <b>Username:</b> @{escape_html(username)}\n"
        else:
            info_text += f"👨‍💼 <b>Username:</b> не указан\n"
            
        full_name = f"{escape_html(first_name)} {escape_html(last_name)}".strip()
        info_text += f"📝 <b>Имя:</b> {full_name}\n"
        
        # Дополнительная информация из БД (только для зарегистрированных)
        if is_registered and user_info:
            info_text += f"💰 <b>Баланс:</b> {user_info.get('balance', 0)} руб.\n"
            
            # Добавляем информацию о триале если есть
            trial = user_info.get('trial')
            if trial and trial > 0:
                info_text += f"🎯 <b>Триал:</b> {trial}\n"
            
            # Добавляем информацию о регистрации
            created_at = user_info.get('created_at')
            if created_at:
                # Преобразуем дату в читаемый формат
                try:
                    from datetime import datetime
                    if isinstance(created_at, str):
                        dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        formatted_date = dt.strftime("%d.%m.%Y")
                    else:
                        formatted_date = str(created_at)
                    info_text += f"📅 <b>Дата регистрации:</b> {formatted_date}\n"
                except:
                    info_text += f"📅 <b>Дата регистрации:</b> {created_at}\n"
            
            # Форматируем информацию о ключах
            if user_keys and len(user_keys) > 0:
                info_text += f"\n🔑 <b>Ключи пользователя ({len(user_keys)}):</b>\n"
                
                for i, key in enumerate(user_keys, 1):
                    # Используем email как название ключа (подписки)
                    key_name = key.get('email', f'key_{i}')
                    info_text += f"   {i}. <code>{key_name}</code>\n"
                    
                    # Дата истечения
                    expiry_date = key.get('expiry_date')
                    if expiry_date:
                        # Преобразуем дату в читаемый формат
                        if isinstance(expiry_date, str):
                            try:
                                from datetime import datetime
                                dt = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                                formatted_date = dt.strftime("%d.%m.%Y %H:%M")
                            except:
                                formatted_date = expiry_date[:16] if len(expiry_date) > 16 else expiry_date
                        else:
                            formatted_date = str(expiry_date)
                        info_text += f"      ⏰ <b>Истекает:</b> {formatted_date}\n"
                    
                    # Информация о сервере
                    server_name = key.get('server_name')
                    if server_name:
                        info_text += f"      🖥 <b>Сервер:</b> {server_name}\n"
                    elif key.get('server_id'):
                        info_text += f"      🖥 <b>Сервер ID:</b> {key.get('server_id')}\n"
            else:
                info_text += f"\n🔑 <b>Ключи:</b> Отсутствуют"
        else:
            # Для незарегистрированных пользователей
            info_text += f"\n💡 <b>Информация:</b> Пользователь не зарегистрирован в основном боте. Данные взяты из Telegram."
            
            # Дополнительная информация из Telegram, если доступна
            if telegram_user:
                if telegram_user.language_code:
                    info_text += f"\n🌐 <b>Язык:</b> {telegram_user.language_code}"
                if hasattr(telegram_user, 'is_premium') and telegram_user.is_premium:
                    info_text += f"\n⭐ <b>Premium:</b> Да"
        
        return info_text

# Создаем глобальный экземпляр для использования в других модулях
main_bot_api = MainBotAPIClient()

# Алиас для обратной совместимости
McQueenAPI = MainBotAPIClient
