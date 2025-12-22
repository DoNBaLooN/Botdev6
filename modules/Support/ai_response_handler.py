import logging
from typing import Dict, List, Optional
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from gigachat_client import GigaChatClient
from image_handler import ImageHandler
from config import Config

logger = logging.getLogger(__name__)

class AIResponseHandler:
    """Обработчик ИИ-ответов для технической поддержки"""
    
    def __init__(self, gigachat_client=None):
        self.conversation_history = {}  # {user_id: [messages]}
        self.max_history = 10  # Максимальное количество сообщений в истории
        self.image_handler = ImageHandler()  # Обработчик изображений
        # Сохраняем ссылку на общий GigaChatClient
        self.gigachat_client = gigachat_client
        
    def add_to_history(self, user_id: int, role: str, content: str):
        """Добавляет сообщение в историю разговора"""
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
            
        self.conversation_history[user_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        
        # Ограничиваем размер истории
        if len(self.conversation_history[user_id]) > self.max_history:
            self.conversation_history[user_id] = self.conversation_history[user_id][-self.max_history:]
    
    def get_history(self, user_id: int) -> List[Dict]:
        """Получает историю разговора для пользователя"""
        return self.conversation_history.get(user_id, [])
    
    def clear_history(self, user_id: int):
        """Очищает историю разговора для пользователя"""
        if user_id in self.conversation_history:
            del self.conversation_history[user_id]
    
    def create_operator_keyboard(self):
        """Создает клавиатуру с кнопкой вызова оператора и закрытия тикета"""
        keyboard = [
            [
                InlineKeyboardButton("👨‍💼 Позвать оператора", callback_data="call_operator"),
                InlineKeyboardButton("✅ Помогло!", callback_data="close_ticket_helped")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def create_help_only_keyboard(self):
        """Создает клавиатуру только с кнопкой 'Помогло!' без кнопки оператора"""
        keyboard = [
            [
                InlineKeyboardButton("✅ Помогло!", callback_data="close_ticket_helped")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def should_show_operator_button(self, response_text: str, user_id: int, gigachat_client=None) -> bool:
        """Проверяет, нужно ли показывать кнопку 'Позвать оператора' на основе счетчика сообщений"""
        
        # Если есть доступ к GigaChatClient, проверяем счетчик напрямую
        if gigachat_client:
            operator_button_after = gigachat_client.operator_button_after
            current_count = gigachat_client.user_message_count.get(user_id, 0)
            
            # Возвращаем True если счетчик достиг нужного значения
            should_show = current_count >= operator_button_after
            
            logger.info(f"Проверка кнопки оператора для пользователя {user_id}: "
                       f"счетчик={current_count}, порог={operator_button_after}, "
                       f"показать={'ДА' if should_show else 'НЕТ'}")
            
            return should_show
        
        # Fallback: проверяем по тексту (старый метод)
        return ("Если проблема решена - нажмите" in response_text or 
                "Позвать оператора" in response_text)
    
    async def generate_ai_response(self, user_message: str, user_id: int) -> Optional[str]:
        """Генерирует ответ от ИИ"""
        if not Config.GIGACHAT_ENABLED:
            logger.debug("GigaChat отключен в конфигурации")
            return None
            
        try:
            # Получаем существующую историю для контекста
            history = self.get_history(user_id)
            
            # Используем общий GigaChatClient вместо создания нового
            if self.gigachat_client:
                ai_response = await self.gigachat_client.generate_response(
                    user_message=user_message, 
                    user_id=user_id,
                    conversation_history=history  # Передаем всю историю
                )
            else:
                logger.error("GigaChatClient не передан в AIResponseHandler")
                return None
                
                if ai_response:
                    # Добавляем сообщение пользователя в историю
                    self.add_to_history(user_id, "user", user_message)
                    
                    # Возвращаем ответ как есть (GigaChat сам добавит кнопки по счетчику)
                    full_response = ai_response
                    
                    # Добавляем ответ ИИ в историю (без кнопок)
                    self.add_to_history(user_id, "assistant", ai_response)
                    
                    logger.debug(f"ИИ-ответ сгенерирован для пользователя {user_id}, история: {len(self.get_history(user_id))} сообщений")
                    
                    return full_response
                    
        except Exception as e:
            logger.error(f"Ошибка при генерации ИИ-ответа для пользователя {user_id}: {e}")
            
        return None
    
    async def send_ai_response_with_images(self, 
                                         update: Update, 
                                         context: ContextTypes.DEFAULT_TYPE, 
                                         user_message: str, 
                                         user_id: int) -> tuple[bool, str]:
        """
        Генерирует и отправляет ИИ-ответ с изображениями если они запрошены
        
        Returns:
            tuple[bool, str]: (True если ответ был отправлен, текст который был отправлен пользователю)
        """
        if not Config.GIGACHAT_ENABLED:
            logger.debug("GigaChat отключен в конфигурации")
            return False, ""
            
        try:
            # Получаем существующую историю для контекста
            history = self.get_history(user_id)
            
            # Используем общий GigaChatClient вместо создания нового
            if not self.gigachat_client:
                logger.error("GigaChatClient не передан в AIResponseHandler")
                return False, ""
                
            gigachat = self.gigachat_client
            ai_response = await gigachat.generate_response(
                user_message=user_message, 
                user_id=user_id,
                conversation_history=history
            )
            
            if ai_response:
                # Извлекаем запросы изображений из ответа
                cleaned_text, requested_images = self.image_handler.extract_image_requests(ai_response)
                
                # Добавляем сообщение пользователя в историю
                self.add_to_history(user_id, "user", user_message)
                
                # Проверяем, нужно ли показывать кнопку "Позвать оператора" 
                # ИСПОЛЬЗУЕМ ПРЯМУЮ ПРОВЕРКУ СЧЕТЧИКА, а не текст
                should_show_operator = self.should_show_operator_button(
                    cleaned_text, user_id, gigachat
                )
                
                if should_show_operator:
                    # Счетчик показывает что нужна кнопка оператора - полная клавиатура
                    full_response = cleaned_text
                    reply_markup = self.create_operator_keyboard()
                    logger.info(f"Пользователь {user_id}: добавляем ПОЛНУЮ клавиатуру (Оператор + Помогло)")
                else:
                    # Счетчик показывает что кнопка оператора не нужна - только "Помогло!"
                    full_response = cleaned_text
                    reply_markup = self.create_help_only_keyboard()
                    logger.info(f"Пользователь {user_id}: добавляем ТОЛЬКО кнопку Помогло")
                
                # Отправляем ответ с изображениями
                success = await self.image_handler.send_images_with_text(
                    update=update,
                    context=context,
                    text=full_response,
                    images=requested_images,
                    reply_markup=reply_markup
                )
                
                if success:
                    # Добавляем ответ ИИ в историю (без кнопок)
                    self.add_to_history(user_id, "assistant", cleaned_text)
                    
                    logger.debug(f"ИИ-ответ с {len(requested_images)} изображениями отправлен пользователю {user_id}")
                    # Возвращаем успех и текст который был отправлен пользователю (без команд изображений)
                    return True, full_response
                    
        except Exception as e:
            logger.error(f"Ошибка при генерации и отправке ИИ-ответа с изображениями для пользователя {user_id}: {e}")
            
        return False, ""
    
    async def handle_operator_call(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает вызов оператора"""
        try:
            query = update.callback_query
            await query.answer()
            
            user = query.from_user
            user_id = user.id
            
            # Отправляем сообщение пользователю
            await query.edit_message_text(
                text="👨‍💼 Оператор скоро ответит вам! Пожалуйста, ожидайте.\n\nВы можете продолжить описывать вашу проблему, и оператор увидит все сообщения.",
                parse_mode=ParseMode.HTML
            )
            
            # Очищаем историю ИИ-разговора при вызове оператора
            self.clear_history(user_id)
            
            logger.info(f"Пользователь {user_id} вызвал оператора")
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при обработке вызова оператора: {e}")
            return False
    
    def should_use_ai_response(self, user_id: int) -> bool:
        """Определяет, следует ли использовать ИИ-ответ"""
        # ИИ отвечает только если нет активного диалога с оператором
        # Это будет определяться в основном обработчике на основе состояния тикета
        return Config.GIGACHAT_ENABLED
