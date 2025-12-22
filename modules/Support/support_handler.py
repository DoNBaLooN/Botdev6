import logging
import asyncio
import re
from typing import Dict, Optional
from datetime import datetime
from telegram import Update, Message, ForumTopic, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from api_client import McQueenAPI
from config import Config
from topic_storage import TopicStorage
from ai_response_handler import AIResponseHandler
from ticket_state_manager import TicketStateManager
from texts import texts
from buttons import buttons
from blocked_users import blocked_users

logger = logging.getLogger(__name__)

class SupportHandler:
    """Обработчик запросов в техническую поддержку"""
    
    def __init__(self, gigachat_client=None):
        self.api_client = McQueenAPI()
        self.support_chat_id = Config.SUPPORT_CHAT_ID
        self.storage = TopicStorage()
        # Передаем GigaChatClient в AIResponseHandler
        self.ai_handler = AIResponseHandler(gigachat_client=gigachat_client)
        self.ticket_state = TicketStateManager()
    
    def escape_html(self, text):
        """Экранирование HTML символов"""
        if not text:
            return ""
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    def validate_and_clean_html(self, text):
        """Валидация и очистка HTML для Telegram"""
        if not text:
            return ""
        
        import re
        
        # Убираем все HTML теги кроме разрешённых Telegram
        allowed_tags = ['b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'code', 'pre', 'a', 'tg-spoiler', 'blockquote']
        
        # Паттерн для поиска всех HTML тегов
        tag_pattern = r'<(/?)(\w+)([^>]*)>'
        
        def replace_tag(match):
            is_closing = bool(match.group(1))
            tag_name = match.group(2).lower()
            attributes = match.group(3)
            
            # Если тег разрешён
            if tag_name in allowed_tags:
                if tag_name == 'a' and not is_closing and attributes:
                    # Для ссылок оставляем только href
                    href_match = re.search(r'href=["\']([^"\']*)["\']', attributes)
                    if href_match:
                        return f'<{match.group(1)}{tag_name} href="{href_match.group(1)}">'
                return f'<{match.group(1)}{tag_name}>'
            else:
                # Неразрешённый тег - убираем
                return ''
        
        # Заменяем все теги
        cleaned_text = re.sub(tag_pattern, replace_tag, str(text))
        
        # Убираем лишние пробелы и переводы строк
        cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)
        cleaned_text = cleaned_text.strip()
        
        return cleaned_text
    
    async def safe_send_html_message(self, message_or_query, text: str, **kwargs):
        """Безопасная отправка HTML сообщения с fallback на простой текст"""
        try:
            # Валидируем и очищаем HTML
            clean_text = self.validate_and_clean_html(text)
            
            # Пробуем отправить с HTML разметкой
            if hasattr(message_or_query, 'edit_message_text'):
                # Это callback query
                return await message_or_query.edit_message_text(clean_text, parse_mode=ParseMode.HTML, **kwargs)
            else:
                # Это обычное сообщение
                return await message_or_query.reply_text(clean_text, parse_mode=ParseMode.HTML, **kwargs)
                
        except Exception as e:
            logger.warning(f"Failed to send HTML message, trying plain text: {e}")
            try:
                # Убираем все HTML теги для fallback
                import re
                plain_text = re.sub(r'<[^>]+>', '', text)
                
                if hasattr(message_or_query, 'edit_message_text'):
                    return await message_or_query.edit_message_text(plain_text, **kwargs)
                else:
                    return await message_or_query.reply_text(plain_text, **kwargs)
            except Exception as e2:
                logger.error(f"Failed to send even plain text message: {e2}")
                raise e2
    
    async def handle_support_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка нового запроса в поддержку с улучшенной обработкой ошибок"""
        try:
            # ВАЖНО: Если это edited сообщение - игнорируем
            if update.edited_message:
                logger.debug("Ignoring edited message in handle_support_request")
                return
                
            user = update.effective_user
            message = update.message
            ai_response_sent = False  # Флаг для предотвращения дублирования ИИ-ответов
            
            if not user or not message:
                logger.error("No user or message found in update")
                return
            
            # Проверяем, заблокирован ли пользователь
            if blocked_users.is_blocked(user.id):
                logger.info(f"Blocked user {user.id} tried to send message")
                await message.reply_text(
                    texts.blocked_user_message(),
                    parse_mode=ParseMode.HTML
                )
                return
            
            logger.debug(f"Processing support request from user {user.id}")
            
            # Проверяем, есть ли уже активный топик для пользователя
            existing_topic_id = self.storage.get_topic_for_user(user.id)
            logger.info(f"🔍 Checking existing topic for user {user.id}: {existing_topic_id}")
            
            if existing_topic_id:
                # Используем существующий топик
                topic_id = existing_topic_id
                logger.info(f"✅ Using existing topic {topic_id} for user {user.id}")
                
                # Отправляем сообщение в существующий топик
                try:
                    ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
                    
                    if message.text:
                        await context.bot.send_message(
                            chat_id=self.support_chat_id,
                            message_thread_id=topic_id,
                            text=self.escape_html(message.text),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        # Пересылаем медиа-контент
                        await message.forward(self.support_chat_id, message_thread_id=topic_id)
                    
                    logger.info(f"Message added to existing ticket #{ticket_number} for user {user.id}")
                    
                    # Проверяем, нужно ли генерировать ИИ-ответ для существующего топика
                    if self.ticket_state.is_ai_mode(user.id):
                        logger.info(f"Генерируем ИИ-ответ для существующего топика пользователя {user.id}")
                        await self._handle_ai_response(user, message, context)
                        # Устанавливаем флаг что ИИ-ответ уже отправлен
                        ai_response_sent = True
                    else:
                        ai_response_sent = False
                    
                    return
                    
                except Exception as e:
                    logger.error(f"Failed to add message to existing topic {topic_id}: {e}")
                    # Продолжаем создание нового топика
                    existing_topic_id = None
            
            if not existing_topic_id:
                # Создаем новый топик с повторными попытками
                logger.info(f"Creating new topic for user {user.id}")
                topic_id = await self._create_new_topic(user, context)
                if not topic_id:
                    logger.error(f"Failed to create topic for user {user.id}")
                    await update.message.reply_text(
                        "❌ Временные технические неполадки. Попробуйте позже или обратитесь напрямую к администратору."
                    )
                    return
                logger.info(f"Created new topic {topic_id} for user {user.id}")
            
            # Отправляем сообщение пользователя в топик
            logger.debug(f"Sending message to topic {topic_id}")
            message_sent = await self.send_user_message_to_topic(message, topic_id, context)
            
            # Если сообщение не удалось отправить (топик был удален), создаем новый
            if not message_sent:
                logger.warning(f"Failed to send message to topic {topic_id}, creating new topic")
                await self._handle_deleted_topic(user, message, context)
                return
            
            # Отвечаем пользователю только для новых тикетов
            if not existing_topic_id:
                logger.debug(f"Sending new ticket response to user {user.id}")
                await self._send_new_ticket_response(user, topic_id, update)
                
                # Устанавливаем режим ИИ для нового пользователя
                self.ticket_state.set_ai_mode(user.id)
            
            # Проверяем, нужно ли отправить ИИ-ответ (только для новых тикетов или если еще не отправлен)
            if not ai_response_sent:
                await self._handle_ai_response(user, message, context)
            
            logger.info(f"Successfully processed support request from user {user.id} to topic {topic_id}")
            
        except Exception as e:
            logger.error(f"Error handling support request from user {user.id if user else 'unknown'}: {e}")
            logger.exception("Full traceback:")
            # try:
            #     await update.message.reply_text(
            #         "❌ Произошла ошибка при обработке запроса. Попробуйте позже."
            #     )
            # except Exception as reply_error:
            #     logger.error(f"Failed to send error reply: {reply_error}")
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки пользователям
            logger.debug("Error occurred in handle_support_request but not notifying user")
    
    async def _create_new_topic(self, user, context) -> Optional[int]:
        """Создание нового топика с повторными попытками"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                next_ticket_number = self.storage.get_next_ticket_number()
                topic_name = f"Тикет #{next_ticket_number} • {user.first_name or user.username} • ID{user.id}"
                logger.info(f"Creating new support topic for user {user.id}: {topic_name} (attempt {attempt + 1})")
                
                topic = await context.bot.create_forum_topic(
                    chat_id=self.support_chat_id,
                    name=topic_name
                )
                topic_id = topic.message_thread_id
                
                # Сохраняем маппинг и получаем номер тикета
                ticket_number = self.storage.add_mapping(user.id, topic_id)
                
                # Устанавливаем иконку "новый тикет"
                await self.change_topic_icon(context, topic_id, 'new')
                
                # Отправляем информацию о пользователе первым сообщением
                user_info_text = await self.api_client.format_user_info(user.id, user)
                await context.bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    text=user_info_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                
                # Отправляем панель управления тикетом
                is_user_blocked = blocked_users.is_blocked(user.id)
                reply_markup = buttons.operator_keyboard(user.id, topic_id, is_user_blocked)
                
                await context.bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    text="🎫 <b>Управление тикетом</b>",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                
                return topic_id
                
            except Exception as e:
                logger.warning(f"Failed to create topic (attempt {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2)  # Ждем 2 секунды перед повтором
                    continue
                else:
                    logger.error(f"All attempts to create topic failed for user {user.id}")
                    return None
        
        return None
    
    async def _handle_deleted_topic(self, user, message, context):
        """Обработка ситуации когда топик был удален"""
        try:
            # Очищаем старый маппинг
            self.storage.remove_mapping(user.id)
            
            # Создаем новый топик
            topic_id = await self._create_new_topic(user, context)
            if topic_id:
                # Повторно отправляем сообщение пользователя в новый топик
                await self.send_user_message_to_topic(message, topic_id, context)
                # Отправляем ответ о новом тикете
                await self._send_new_ticket_response(user, topic_id, message)
        except Exception as e:
            logger.error(f"Error handling deleted topic: {e}")
    
    async def _send_new_ticket_response(self, user, topic_id, update_or_message):
        """Отправка ответа о создании нового тикета"""
        try:
            ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
            keyboard = [
                [InlineKeyboardButton("📋 Мои обращения", callback_data=f"my_tickets_{user.id}")],
                [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"user_close_{topic_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            response_text = (
                "✅ <b>Ваш запрос получен!</b>\n"
                "Специалист технической поддержки свяжется с вами в ближайшее время.\n\n"
                f"🎫 <b>Номер тикета:</b> <code>#{ticket_number}</code>\n"
                f"📝 <b>Статус:</b> Открыт\n\n"
                "💡 <i>Можете продолжать писать в этот чат - все сообщения будут переданы в поддержку.</i>"
            )
            
            if hasattr(update_or_message, 'message'):
                await update_or_message.message.reply_text(
                    response_text, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            else:
                await update_or_message.reply_text(
                    response_text, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Failed to send new ticket response: {e}")
    
    async def send_user_message_to_topic(self, message: Message, topic_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Отправка сообщения пользователя в топик. Возвращает True если успешно, False если топик не существует"""
        try:
            # Текстовое сообщение
            if message.text:
                await context.bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    text=self.escape_html(message.text),
                    parse_mode=ParseMode.HTML
                )
            
            # Голосовое сообщение
            elif message.voice:
                await context.bot.send_voice(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    voice=message.voice.file_id
                )
            
            # Фото
            elif message.photo:
                caption_text = None
                if message.caption:
                    caption_text = self.escape_html(message.caption)
                
                await context.bot.send_photo(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    photo=message.photo[-1].file_id,
                    caption=caption_text,
                    parse_mode=ParseMode.HTML if caption_text else None
                )
            
            # Документ
            elif message.document:
                caption_text = None
                if message.caption:
                    caption_text = self.escape_html(message.caption)
                
                await context.bot.send_document(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    document=message.document.file_id,
                    caption=caption_text,
                    parse_mode=ParseMode.HTML if caption_text else None
                )
            
            # Видео
            elif message.video:
                caption_text = None
                if message.caption:
                    caption_text = self.escape_html(message.caption)
                
                await context.bot.send_video(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    video=message.video.file_id,
                    caption=caption_text,
                    parse_mode=ParseMode.HTML if caption_text else None
                )
            
            # Видеозаметка
            elif message.video_note:
                await context.bot.send_video_note(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    video_note=message.video_note.file_id
                )
            
            # Стикер
            elif message.sticker:
                await context.bot.send_sticker(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    sticker=message.sticker.file_id
                )
            
            return True
            
        except Exception as e:
            if "Message thread not found" in str(e) or "thread not found" in str(e).lower():
                logger.warning(f"Topic {topic_id} was deleted: {e}")
                return False
            else:
                logger.error(f"Error sending user message to topic: {e}")
                return False
    
    async def handle_reply_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка ответа от поддержки пользователю"""
        try:
            # ВАЖНО: Если это edited сообщение - игнорируем
            if update.edited_message:
                logger.debug("Ignoring edited message in handle_reply_to_user")
                return
            
            # Проверяем и обрабатываем команды в чате поддержки (НЕ пересылаем их пользователям)
            if await self.handle_support_chat_command(update, context):
                logger.debug("Command processed in support chat, not forwarding to user")
                return
                
            message = update.message
            
            if (not message or 
                message.chat.id != self.support_chat_id or 
                not hasattr(message, 'message_thread_id') or 
                not message.message_thread_id):
                return
            
            topic_id = message.message_thread_id
            user_id = self.storage.get_user_for_topic(topic_id)
            
            if not user_id:
                logger.warning(f"No user found for topic {topic_id}")
                return
            
            # Отправляем ответ пользователю
            await self.send_support_reply_to_user(message, user_id, context)
            
            logger.info(f"Reply sent from topic {topic_id} to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error handling support reply: {e}")
            # # НЕ показываем ошибку админу при редактировании
            # if not update.edited_message:
            #     try:
            #         await update.message.reply_text("❌ Произошла техническая ошибка при обработке ответа.")
            #     except:
            #         pass
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки пользователям
            logger.debug("Error occurred in handle_reply_to_user but not notifying user")
    
    async def send_support_reply_to_user(self, message: Message, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Отправка ответа поддержки пользователю"""
        try:
            support_name = message.from_user.first_name or message.from_user.username or "Поддержка"
            
            # Текстовое сообщение
            if message.text:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=self.escape_html(message.text),
                    parse_mode=ParseMode.HTML
                )
            
            # Голосовое сообщение
            elif message.voice:
                await context.bot.send_voice(
                    chat_id=user_id,
                    voice=message.voice.file_id
                )
            
            # Фото
            elif message.photo:
                caption = None
                if message.caption:
                    caption = self.escape_html(message.caption)
                
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=message.photo[-1].file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML if caption else None
                )
            
            # Документ
            elif message.document:
                caption = None
                if message.caption:
                    caption = self.escape_html(message.caption)
                
                await context.bot.send_document(
                    chat_id=user_id,
                    document=message.document.file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML if caption else None
                )
            
            # Видео
            elif message.video:
                caption = None
                if message.caption:
                    caption = self.escape_html(message.caption)
                
                await context.bot.send_video(
                    chat_id=user_id,
                    video=message.video.file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML if caption else None
                )
            
            # Видеозаметка
            elif message.video_note:
                await context.bot.send_video_note(
                    chat_id=user_id,
                    video_note=message.video_note.file_id
                )
            
            # Стикер
            elif message.sticker:
                await context.bot.send_sticker(
                    chat_id=user_id,
                    sticker=message.sticker.file_id
                )
            
        except Exception as e:
            logger.error(f"Error sending support reply to user {user_id}: {e}")
    
    async def close_topic_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для закрытия топика"""
        try:
            message = update.message
            
            if (message.chat.id != self.support_chat_id or 
                not hasattr(message, 'message_thread_id') or 
                not message.message_thread_id):
                return
            
            topic_id = message.message_thread_id
            user_id = self.storage.get_user_for_topic(topic_id)
            
            if user_id:
                # НЕ уведомляем пользователя автоматически при закрытии админом
                # Администратор сам решит, писать ли пользователю
                
                # Удаляем маппинг
                self.storage.close_topic(topic_id)
                
                await message.reply_text(
                    f"✅ Обращение пользователя {user_id} закрыто.",
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"Closed topic {topic_id} for user {user_id}")
            else:
                await message.reply_text("❌ Не удалось найти пользователя для этого топика.")
                
        except Exception as e:
            logger.error(f"Error closing topic: {e}")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        try:
            data = query.data
            user_id = query.from_user.id
            
            if data.startswith('close_ticket_'):
                # Закрытие тикета через кнопку
                parts = data.split('_')
                ticket_user_id = int(parts[2])
                topic_id = int(parts[3])
                
                await self.close_ticket_by_admin(query, context, ticket_user_id, topic_id)
                
            elif data.startswith('ticket_status_'):
                # Информация о тикете для админа
                parts = data.split('_')
                ticket_user_id = int(parts[2])
                topic_id = int(parts[3])
                
                await self.show_ticket_status_admin(query, context, ticket_user_id, topic_id)
                
            elif data.startswith('ticket_info_'):
                # Информация о тикете для пользователя
                parts = data.split('_')
                ticket_user_id = int(parts[2])
                topic_id = int(parts[3])
                
                if user_id == ticket_user_id:  # Проверяем что это владелец тикета
                    await self.show_ticket_info_user(query, context, topic_id)
                
            elif data.startswith('my_tickets_'):
                # Показать все тикеты пользователя
                ticket_user_id = int(data.split('_')[2])
                
                if user_id == ticket_user_id:  # Проверяем что это владелец
                    await self.show_user_tickets(query, context, user_id)
            
            elif data == "write_support":
                # Кнопка "Написать в поддержку"
                reply_markup = buttons.write_support_keyboard()
                
                await query.edit_message_text(
                    texts.write_support_message(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
                
            elif data == "help_info":
                # Кнопка "Помощь"
                reply_markup = buttons.help_keyboard()

                await query.edit_message_text(
                    texts.help_message(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_MENU:
                # Главное меню FAQ
                reply_markup = buttons.faq_main_keyboard()

                await query.edit_message_text(
                    texts.faq_menu_message(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER:
                # Подсказки по роутеру
                reply_markup = buttons.faq_router_keyboard()

                await query.edit_message_text(
                    texts.faq_router_intro(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_SUBSCRIPTION:
                # Подсказки по подписке
                reply_markup = buttons.faq_subscription_keyboard()

                await query.edit_message_text(
                    texts.faq_subscription_intro(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER_YOUTUBE:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_ROUTER)

                await query.edit_message_text(
                    texts.faq_router_youtube(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER_NO_INTERNET:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_ROUTER)

                await query.edit_message_text(
                    texts.faq_router_no_internet(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER_ADMIN_PANEL:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_ROUTER)

                await query.edit_message_text(
                    texts.faq_router_admin_panel(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER_CHANGE_WIFI_PASSWORD:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_ROUTER)

                await query.edit_message_text(
                    texts.faq_router_change_wifi_password(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_ROUTER_CHANGE_WIFI_NAME:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_ROUTER)

                await query.edit_message_text(
                    texts.faq_router_change_wifi_name(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            elif data == buttons.CB_FAQ_SUBSCRIPTION_VPN_SLOW:
                reply_markup = buttons.faq_answer_keyboard(buttons.CB_FAQ_SUBSCRIPTION)

                await query.edit_message_text(
                    texts.faq_subscription_vpn_slow(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )

            elif data == "back_to_start":
                # Кнопка "Назад" - показываем главное меню
                user = query.from_user
                active_topic = self.storage.get_topic_for_user(user_id)
                
                # Получаем основную клавиатуру с user_id
                keyboard_buttons = []
                for row in buttons.main_menu_keyboard(user_id).inline_keyboard:
                    keyboard_buttons.append(row)
                
                if active_topic:
                    active_ticket_number = self.storage.get_ticket_number(active_topic) or active_topic
                    keyboard_buttons.insert(1, [InlineKeyboardButton(f"🎫 Активный тикет #{active_ticket_number}", callback_data=f"ticket_info_{user_id}_{active_topic}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard_buttons)
                
                welcome_text = texts.welcome_message(user.first_name)
                
                await query.edit_message_text(
                    welcome_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup
                )
            
            elif data.startswith("user_close_"):
                # Пользователь закрывает свой тикет
                parts = data.split("_")
                if len(parts) >= 3:
                    topic_id = int(parts[2])
                    await self._close_ticket_by_user(query, user_id, topic_id)
            
            elif data.startswith("block_user_"):
                # Блокировка пользователя
                parts = data.split("_")
                if len(parts) >= 3:
                    target_user_id = int(parts[2])
                    # Получаем topic_id для этого пользователя
                    topic_id = self.storage.get_topic_for_user(target_user_id)
                    await self._block_user(query, context, target_user_id, topic_id)
                    
            elif data.startswith("unblock_user_"):
                # Разблокировка пользователя
                parts = data.split("_")
                if len(parts) >= 3:
                    target_user_id = int(parts[2])
                    # Получаем topic_id для этого пользователя
                    topic_id = self.storage.get_topic_for_user(target_user_id)
                    await self._unblock_user(query, context, target_user_id, topic_id)
            
            elif data.startswith("stop_ai_"):
                # Остановка ИИ оператором
                parts = data.split("_")
                if len(parts) >= 3:
                    target_user_id = int(parts[2])
                    await self._stop_ai_for_user(query, context, target_user_id)
            
            elif data == "close_ticket_helped":
                # Закрытие тикета пользователем через кнопку "Помогло!"
                await self.handle_close_ticket_helped(update, context)
                    
        except Exception as e:
            logger.error(f"Error handling callback query: {e}")
            # await query.edit_message_text("❌ Произошла ошибка при обработке запроса.")
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки пользователям
            try:
                await query.answer("Произошла ошибка", show_alert=False)
            except:
                pass
    
    async def close_ticket_by_admin(self, query, context: ContextTypes.DEFAULT_TYPE, user_id: int, topic_id: int) -> None:
        """Закрытие тикета администратором через кнопку"""
        try:
            logger.info(f"Admin closing ticket - User: {user_id}, Topic: {topic_id}")
            ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
            
            # Уведомляем пользователя о закрытии тикета
            try:
                user_notification = texts.ticket_closed_by_admin_notification(str(ticket_number))
                await context.bot.send_message(
                    chat_id=user_id,
                    text=user_notification,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"User {user_id} notified about ticket closure")
            except Exception as e:
                logger.error(f"Failed to notify user {user_id} about ticket closure: {e}")
            
            # Удаляем маппинг
            try:
                removed = self.storage.close_topic(topic_id)
                if removed:
                    logger.info(f"Ticket mapping removed successfully - Topic: {topic_id}")
                    
                    # СБРАСЫВАЕМ СЧЕТЧИК СООБЩЕНИЙ ДЛЯ ПОЛЬЗОВАТЕЛЯ
                    if hasattr(self, 'ai_handler') and self.ai_handler and hasattr(self.ai_handler, 'gigachat_client'):
                        if self.ai_handler.gigachat_client:
                            self.ai_handler.gigachat_client.reset_user_message_count(user_id)
                            logger.info(f"Счетчик сообщений сброшен для пользователя {user_id} при закрытии тикета администратором")
                else:
                    logger.warning(f"Failed to remove ticket mapping - Topic: {topic_id} (not found)")
            except Exception as e:
                logger.error(f"Error removing ticket mapping: {e}")
            
            # Изменяем иконку топика на "закрыто"
            await self.change_topic_icon(context, topic_id, 'closed')
            
            # Уведомляем других админов о закрытии тикета
            try:
                admin_notification = (
                    f"🔒 <b>Тикет закрыт администратором</b>\n\n"
                    f"👤 <b>Пользователь:</b> <code>{user_id}</code>\n"
                    f"🎫 <b>Номер тикета:</b> <code>#{ticket_number}</code>\n"
                    f"⏰ <b>Закрыт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"👨‍💼 <i>Тикет закрыт администратором через кнопку управления</i>"
                )
                
                from config import Config
                for admin_id in Config.ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_notification,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.warning(f"Failed to notify admin {admin_id} about ticket closure: {e}")
            except Exception as e:
                logger.warning(f"Error notifying admins about ticket closure: {e}")
                
            # Обновляем сообщение с кнопкой
            try:
                await query.edit_message_text(
                    f"✅ <b>Тикет закрыт!</b>\n\n"
                    f"🎫 Номер: <code>#{ticket_number}</code>\n"
                    f"⏰ Закрыт: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"👨‍💼 Администратор: {query.from_user.first_name or 'Unknown'}",
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Admin panel updated for closed ticket #{ticket_number}")
            except Exception as e:
                logger.error(f"Failed to update admin message: {e}")
                
            logger.info(f"Ticket #{ticket_number} (topic {topic_id}) successfully closed by admin")
            
        except Exception as e:
            logger.error(f"Critical error in close_ticket_by_admin: {e}")
            # try:
            #     await query.edit_message_text("❌ Ошибка при закрытии тикета.")
            # except Exception:
            #     pass  # Не критично если не удалось обновить сообщение
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки
            
            # Обновляем сообщение с кнопками
            await query.edit_message_text(
                f"🔒 <b>Тикет закрыт</b>\n\n"
                f"👤 Пользователь: <code>{user_id}</code>\n"
                f"🎫 Номер: <code>#{ticket_number}</code>\n"
                f"⏰ Закрыт: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Ticket #{ticket_number} (topic {topic_id}) closed by admin for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")
            # await query.edit_message_text("❌ Ошибка при закрытии тикета.")
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки
            try:
                await query.answer("Ошибка при закрытии", show_alert=False)
            except:
                pass
    
    async def show_ticket_status_admin(self, query, context: ContextTypes.DEFAULT_TYPE, user_id: int, topic_id: int) -> None:
        """Показать статус тикета для администратора"""
        try:
            created_time = datetime.now().strftime('%d.%m.%Y %H:%M')  # В реальности можно хранить время создания
            ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
            
            status_text = (
                f"📋 <b>Информация о тикете</b>\n\n"
                f"🎫 <b>Номер:</b> <code>#{ticket_number}</code>\n"
                f"👤 <b>Пользователь:</b> <code>{user_id}</code>\n"
                f"📅 <b>Создан:</b> {created_time}\n"
                f"📊 <b>Статус:</b> Активный\n"
                f"🔗 <b>Топик ID:</b> <code>{topic_id}</code>"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_ticket_{user_id}_{topic_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(status_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error showing ticket status: {e}")
    
    async def show_ticket_info_user(self, query, context: ContextTypes.DEFAULT_TYPE, topic_id: int) -> None:
        """Показать информацию о тикете пользователю"""
        try:
            created_time = datetime.now().strftime('%d.%m.%Y %H:%M')
            ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
            
            info_text = (
                f"🎫 <b>Ваш тикет</b>\n\n"
                f"📋 <b>Номер:</b> <code>#{ticket_number}</code>\n"
                f"📅 <b>Создан:</b> {created_time}\n"
                f"📊 <b>Статус:</b> Активный\n\n"
                f"💬 <i>Продолжайте писать в этот чат - все сообщения передаются в поддержку.</i>"
            )
            
            # Используем безопасный метод отправки
            await self.safe_send_html_message(query, info_text)
            
        except Exception as e:
            logger.error(f"Error showing ticket info to user: {e}")
    
    async def show_user_tickets(self, query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
        """Показать все тикеты пользователя"""
        try:
            active_topic = self.storage.get_topic_for_user(user_id)
            
            if active_topic:
                ticket_number = self.storage.get_ticket_number(active_topic) or active_topic
                tickets_text = (
                    f"📋 <b>Ваши тикеты</b>\n\n"
                    f"🎫 <b>Активный тикет:</b> <code>#{ticket_number}</code>\n"
                    f"📊 <b>Статус:</b> Открыт\n\n"
                    f"💬 <i>У вас есть один активный тикет. Все новые сообщения будут добавлены к нему.</i>"
                )
            else:
                tickets_text = (
                    f"📋 <b>Ваши тикеты</b>\n\n"
                    f"📝 У вас нет активных тикетов.\n\n"
                    f"💬 <i>Напишите любое сообщение боту, чтобы создать новый тикет.</i>"
                )
            
            await query.edit_message_text(tickets_text, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error showing user tickets: {e}")

    async def _close_ticket_by_user(self, query, user_id: int, topic_id: int) -> None:
        """Закрытие тикета пользователем"""
        try:
            # Проверяем что это действительно тикет пользователя
            stored_topic = self.storage.get_topic_for_user(user_id)
            if stored_topic != topic_id:
                await query.edit_message_text("❌ Тикет не найден или уже закрыт.")
                return
            
            ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
            
            # Получаем бот из message
            bot = query.message.get_bot()
            
            # Уведомляем в топик о закрытии пользователем
            logger.info(f"Starting to notify topic about user closing ticket - Chat: {self.support_chat_id}, Topic: {topic_id}")
            
            try:
                # Сначала проверим, что мы можем отправлять в этот топик
                test_message = await bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    text="🔍 Проверка связи...",
                )
                logger.info(f"Test message sent successfully: {test_message.message_id}")
                
                # Удаляем тестовое сообщение
                try:
                    await bot.delete_message(
                        chat_id=self.support_chat_id,
                        message_id=test_message.message_id
                    )
                except:
                    pass  # Не критично если не удалось удалить
                
                # Теперь отправляем основное уведомление
                user = query.from_user
                user_display = f"{user.first_name or ''} {user.last_name or ''}".strip()
                if user.username:
                    user_display += f" (@{user.username})"
                if not user_display:
                    user_display = f"Пользователь ID{user_id}"
                
                topic_notification = (
                    f"🔒 <b>ТИКЕТ ЗАКРЫТ ПОЛЬЗОВАТЕЛЕМ</b>\n\n"
                    f"👤 <b>Пользователь:</b> {user_display}\n"
                    f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                    f"🎫 <b>Номер тикета:</b> <code>#{ticket_number}</code>\n"
                    f"⏰ <b>Закрыт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"✅ <b>Статус:</b> Тикет закрыт самостоятельно"
                )
                
                notification_msg = await bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    text=topic_notification,
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"SUCCESS: Topic notification sent! Message ID: {notification_msg.message_id}")
                
            except Exception as e:
                logger.error(f"ERROR in topic notification: {e}")
                logger.error(f"Error type: {type(e).__name__}")
                logger.error(f"Chat ID: {self.support_chat_id} (type: {type(self.support_chat_id)})")
                logger.error(f"Topic ID: {topic_id} (type: {type(topic_id)})")
                
                # Последняя попытка - отправить в основной чат без топика
                try:
                    fallback_msg = await bot.send_message(
                        chat_id=self.support_chat_id,
                        text=f"FALLBACK: Пользователь {user_id} закрыл тикет #{ticket_number}"
                    )
                    logger.info(f"Fallback message sent to main chat: {fallback_msg.message_id}")
                except Exception as e2:
                    logger.error(f"Even fallback failed: {e2}")
            
            # НЕ отправляем уведомления админам о самостоятельном закрытии
            # Админы увидят закрытие в топике чата поддержки
            
            # Удаляем маппинг
            try:
                removed = self.storage.close_topic(topic_id)
                if removed:
                    logger.info(f"Ticket mapping removed successfully by user - Topic: {topic_id}")
                    
                    # СБРАСЫВАЕМ СЧЕТЧИК СООБЩЕНИЙ ДЛЯ ПОЛЬЗОВАТЕЛЯ
                    if hasattr(self, 'ai_handler') and self.ai_handler and hasattr(self.ai_handler, 'gigachat_client'):
                        if self.ai_handler.gigachat_client:
                            self.ai_handler.gigachat_client.reset_user_message_count(user_id)
                            logger.info(f"Счетчик сообщений сброшен для пользователя {user_id} при закрытии тикета")
                else:
                    logger.warning(f"Failed to remove ticket mapping by user - Topic: {topic_id} (not found)")
            except Exception as e:
                logger.error(f"Error removing ticket mapping by user: {e}")
            
            # Изменяем иконку топика на "закрыто"
            # Создаем временный контекст для изменения иконки
            class TempContext:
                def __init__(self, bot):
                    self.bot = bot
            
            temp_context = TempContext(bot)
            await self.change_topic_icon(temp_context, topic_id, 'closed')
            
            # Обновляем сообщение пользователя
            await query.edit_message_text(
                f"🔒 <b>Тикет закрыт</b>\n\n"
                f"🎫 <b>Номер:</b> <code>#{ticket_number}</code>\n"
                f"⏰ <b>Закрыт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                "💬 <i>Если у вас есть новые вопросы, просто напишите боту!</i>",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Ticket #{ticket_number} (topic {topic_id}) closed by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error closing ticket by user: {e}")
            # await query.edit_message_text("❌ Ошибка при закрытии тикета.")
            
            # ОТКЛЮЧЕНО: больше не показываем ошибки
            try:
                await query.answer("Ошибка при закрытии", show_alert=False)
            except:
                pass

    def get_topic_user_id(self, topic_name: str) -> int:
        """Извлечение ID пользователя из названия топика (legacy)"""
        try:
            import re
            match = re.search(r'ID(\d+)', topic_name)
            if match:
                return int(match.group(1))
            return 0
        except:
            return 0
    
    async def handle_edited_support_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка отредактированных сообщений от пользователей в поддержке"""
        try:
            user = update.effective_user
            message = update.edited_message
            
            if not user or not message:
                logger.debug("No user or edited message found in update")
                return
            
            logger.debug(f"Processing edited support message from user {user.id}")
            
            # Проверяем, есть ли активный топик для пользователя
            existing_topic_id = self.storage.get_topic_for_user(user.id)
            
            if existing_topic_id:
                # Отправляем уведомление о редактировании в топик
                edit_notification = (
                    f"✏️ <b>Сообщение отредактировано</b>\n\n"
                    f"📝 <b>Новый текст:</b>\n{self.escape_html(message.text or 'Медиа-файл')}"
                )
                
                await context.bot.send_message(
                    chat_id=self.support_chat_id,
                    message_thread_id=existing_topic_id,
                    text=edit_notification,
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"Edited message notification sent to topic {existing_topic_id} for user {user.id}")
            else:
                logger.debug(f"No active topic found for user {user.id}, ignoring edited message")
            
        except Exception as e:
            logger.error(f"Error handling edited support message: {e}")
    
    async def handle_edited_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка отредактированных сообщений от админов в поддержке"""
        try:
            message = update.edited_message
            
            if (not message or 
                message.chat.id != self.support_chat_id or 
                not hasattr(message, 'message_thread_id') or 
                not message.message_thread_id):
                return
            
            topic_id = message.message_thread_id
            user_id = self.storage.get_user_for_topic(topic_id)
            
            if not user_id:
                return
            
            # Отправляем уведомление о редактировании пользователю
            edit_notification = (
                f"✏️ <b>Агент тех поддержки отредактировал сообщение</b>\n\n"
                f"📝 <b>Новый текст:</b>\n{self.escape_html(message.text or 'Медиа-файл')}"
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=edit_notification,
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Edited message notification sent from topic {topic_id} to user {user_id}")
            
        except Exception as e:
            logger.error(f"Error handling edited admin message: {e}")
            # НЕ переподнимаем исключение, чтобы не вызывать глобальный error_handler
    
    def _extract_text_for_ai(self, message: Message) -> Optional[str]:
        """Извлекает текст из сообщения для обработки ИИ"""
        try:
            # Если есть обычный текст
            if message.text:
                return message.text
            
            # Если есть медиа с подписью
            if message.caption:
                media_type = ""
                if message.photo:
                    media_type = "📷 Пользователь отправил фото"
                elif message.video:
                    media_type = "🎥 Пользователь отправил видео"
                elif message.document:
                    media_type = "📎 Пользователь отправил документ"
                elif message.audio:
                    media_type = "🎵 Пользователь отправил аудио"
                elif message.voice:
                    media_type = "🎤 Пользователь отправил голосовое сообщение"
                elif message.video_note:
                    media_type = "📹 Пользователь отправил видео-сообщение"
                elif message.sticker:
                    media_type = "🎭 Пользователь отправил стикер"
                
                return f"{media_type} с подписью: {message.caption}"
            
            # Если медиа без подписи - создаем описание
            if message.photo:
                return "📷 Пользователь отправил фото. Пожалуйста, ответьте по поводу изображения."
            elif message.video:
                return "🎥 Пользователь отправил видео. Пожалуйста, ответьте по поводу видео."
            elif message.document:
                file_name = message.document.file_name or "файл"
                return f"📎 Пользователь отправил документ: {file_name}. Пожалуйста, ответьте по поводу документа."
            elif message.audio:
                return "🎵 Пользователь отправил аудиофайл. Пожалуйста, ответьте по поводу аудио."
            elif message.voice:
                return "🎤 Пользователь отправил голосовое сообщение. Пожалуйста, ответьте пользователю."
            elif message.video_note:
                return "📹 Пользователь отправил видео-сообщение. Пожалуйста, ответьте пользователю."
            elif message.sticker:
                return "🎭 Пользователь отправил стикер. Пожалуйста, ответьте пользователю."
            elif message.location:
                return "📍 Пользователь отправил геолокацию. Пожалуйста, ответьте по поводу местоположения."
            elif message.contact:
                return "👤 Пользователь отправил контакт. Пожалуйста, ответьте по поводу контактной информации."
            
            # Если ничего не найдено
            return None
            
        except Exception as e:
            logger.error(f"Ошибка при извлечении текста для ИИ: {e}")
            return None

    async def _handle_ai_response(self, user, message: Message, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает ИИ-ответ пользователю"""
        try:
            user_id = user.id
            logger.info(f"Обрабатываем ИИ-ответ для пользователя {user_id}")
            
            # Проверяем, нужно ли отправить ИИ-ответ
            if not self.ticket_state.is_ai_mode(user_id):
                logger.info(f"Пользователь {user_id} НЕ в режиме ИИ, пропускаем")
                return
            
            # Определяем текст для обработки ИИ
            user_text = self._extract_text_for_ai(message)
            
            if not user_text:
                logger.debug(f"Не удалось извлечь текст из сообщения пользователя {user_id}, пропускаем ИИ")
                return
            
            logger.info(f"Генерируем ИИ-ответ для пользователя {user_id}")
            
            # Создаем фиктивный update объект для совместимости с image_handler
            from telegram import Update
            fake_update = Update(update_id=0, message=message)
            
            # Пытаемся отправить ответ от ИИ с изображениями
            ai_sent, sent_text = await self.ai_handler.send_ai_response_with_images(
                update=fake_update,
                context=context,
                user_message=user_text,
                user_id=user_id
            )
            
            if ai_sent:
                # Отправляем ИИ-ответ в топик для информирования операторов
                topic_id = self.storage.get_topic_for_user(user_id)
                if topic_id and sent_text:
                    # Используем тот же текст, который был отправлен пользователю
                    # Валидируем и очищаем HTML перед отправкой
                    cleaned_response = self.validate_and_clean_html(sent_text)
                    
                    ai_info_message = (
                        f"🤖 <b>ИИ-помощник ответил пользователю:</b>\n\n"
                        f"{cleaned_response}"
                    )
                    
                    # Создаем клавиатуру с кнопкой "Остановить ИИ"
                    stop_ai_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔴 Остановить ИИ", callback_data=f"stop_ai_{user_id}")]
                    ])
                    
                    try:
                        await context.bot.send_message(
                            chat_id=self.support_chat_id,
                            message_thread_id=topic_id,
                            text=ai_info_message,
                            parse_mode=ParseMode.HTML,
                            reply_markup=stop_ai_keyboard
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления операторам: {e}")
                        # Пробуем отправить без HTML форматирования
                        try:
                            plain_text = ai_info_message.replace('<b>', '').replace('</b>', '')
                            await context.bot.send_message(
                                chat_id=self.support_chat_id,
                                message_thread_id=topic_id,
                                text=plain_text
                            )
                        except Exception as e2:
                            logger.error(f"Не удалось отправить уведомление даже без HTML: {e2}")
                
                logger.info(f"ИИ-ответ отправлен пользователю {user_id}")
            else:
                logger.warning(f"Не удалось отправить ИИ-ответ пользователю {user_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке ИИ-ответа для пользователя {user.id}: {e}")
    
    async def handle_operator_call(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает вызов оператора пользователем"""
        try:
            query = update.callback_query
            user = query.from_user
            user_id = user.id
            
            logger.info(f"Пользователь {user_id} вызывает оператора")
            
            # Обрабатываем вызов оператора через ИИ-обработчик
            success = await self.ai_handler.handle_operator_call(update, context)
            
            if success:
                # Переключаем пользователя в режим оператора
                self.ticket_state.set_operator_mode(user_id)
                
                # Отправляем уведомление в топик
                topic_id = self.storage.get_topic_for_user(user_id)
                if topic_id:
                    operator_call_message = (
                        f"🚨 <b>ВЫЗОВ ОПЕРАТОРА</b> 🚨\n\n"
                        f"👤 Пользователь {user.first_name or user.username} (ID: {user_id}) запрашивает помощь оператора.\n"
                        f"⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n\n"
                        f"💬 <i>Пользователь будет ожидать ответа от живого оператора.</i>"
                    )
                    
                    await context.bot.send_message(
                        chat_id=self.support_chat_id,
                        message_thread_id=topic_id,
                        text=operator_call_message,
                        parse_mode=ParseMode.HTML
                    )
                
                logger.info(f"Вызов оператора обработан для пользователя {user_id}")
        
        except Exception as e:
            logger.error(f"Ошибка при обработке вызова оператора: {e}")
            try:
                await query.answer("❌ Произошла ошибка. Попробуйте еще раз.", show_alert=True)
            except:
                pass
    
    async def handle_close_ticket_helped(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает закрытие тикета пользователем через кнопку 'Помогло!'"""
        try:
            query = update.callback_query
            await query.answer()
            
            user = query.from_user
            user_id = user.id
            
            logger.info(f"Пользователь {user_id} закрывает тикет через кнопку 'Помогло!'")
            
            # Проверяем, есть ли активный тикет
            topic_id = self.storage.get_topic_for_user(user_id)
            
            if topic_id:
                # Проверяем что это действительно тикет пользователя (как в _close_ticket_by_user)
                stored_topic = self.storage.get_topic_for_user(user_id)
                if stored_topic != topic_id:
                    await query.edit_message_text("❌ Тикет не найден или уже закрыт.")
                    return
                
                ticket_number = self.storage.get_ticket_number(topic_id) or topic_id
                
                # Получаем бот из query
                bot = query.message.get_bot()
                
                # Уведомляем в топик о закрытии пользователем (используем ту же логику)
                logger.info(f"Starting to notify topic about user closing ticket via 'Помогло!' - Chat: {self.support_chat_id}, Topic: {topic_id}")
                
                try:
                    # Отправляем уведомление в топик
                    user_display = f"{user.first_name or ''} {user.last_name or ''}".strip()
                    if user.username:
                        user_display += f" (@{user.username})"
                    if not user_display:
                        user_display = f"Пользователь ID{user_id}"
                    
                    topic_notification = (
                        f"✅ <b>ТИКЕТ ЗАКРЫТ ПОЛЬЗОВАТЕЛЕМ</b>\n\n"
                        f"👤 <b>Пользователь:</b> {user_display}\n"
                        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                        f"🎫 <b>Номер тикета:</b> <code>#{ticket_number}</code>\n"
                        f"⏰ <b>Закрыт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                        f"💬 <b>Причина:</b> Проблема решена (нажал 'Помогло!')\n\n"
                        f"🎉 <b>Статус:</b> Пользователь остался доволен качеством поддержки!"
                    )
                    
                    notification_msg = await bot.send_message(
                        chat_id=self.support_chat_id,
                        message_thread_id=topic_id,
                        text=topic_notification,
                        parse_mode=ParseMode.HTML
                    )
                    
                    logger.info(f"SUCCESS: Topic notification sent! Message ID: {notification_msg.message_id}")
                    
                except Exception as e:
                    logger.error(f"ERROR in topic notification: {e}")
                    logger.error(f"Error type: {type(e).__name__}")
                    logger.error(f"Chat ID: {self.support_chat_id} (type: {type(self.support_chat_id)})")
                    logger.error(f"Topic ID: {topic_id} (type: {type(topic_id)})")
                    
                    # Последняя попытка - отправить в основной чат без топика
                    try:
                        fallback_msg = await bot.send_message(
                            chat_id=self.support_chat_id,
                            text=f"FALLBACK: Пользователь {user_id} закрыл тикет #{ticket_number} (Помогло!)"
                        )
                        logger.info(f"Fallback message sent to main chat: {fallback_msg.message_id}")
                    except Exception as e2:
                        logger.error(f"Even fallback failed: {e2}")
                
                # Удаляем маппинг (используем правильный метод close_topic как в _close_ticket_by_user)
                try:
                    removed = self.storage.close_topic(topic_id)
                    if removed:
                        logger.info(f"Ticket mapping removed successfully by user via 'Помогло!' - Topic: {topic_id}")
                        
                        # СБРАСЫВАЕМ СЧЕТЧИК СООБЩЕНИЙ ДЛЯ ПОЛЬЗОВАТЕЛЯ
                        if hasattr(self, 'ai_handler') and self.ai_handler and hasattr(self.ai_handler, 'gigachat_client'):
                            if self.ai_handler.gigachat_client:
                                self.ai_handler.gigachat_client.reset_user_message_count(user_id)
                                logger.info(f"Счетчик сообщений сброшен для пользователя {user_id} при закрытии тикета через 'Помогло!'")
                    else:
                        logger.warning(f"Failed to remove ticket mapping by user via 'Помогло!' - Topic: {topic_id} (not found)")
                except Exception as e:
                    logger.error(f"Error removing ticket mapping by user via 'Помогло!': {e}")
                
                # Изменяем иконку топика на "закрыто" (используем ту же логику)
                class TempContext:
                    def __init__(self, bot):
                        self.bot = bot
                
                temp_context = TempContext(bot)
                await self.change_topic_icon(temp_context, topic_id, 'closed')
                
                # Обновляем сообщение пользователя (используем ту же логику)
                await query.edit_message_text(
                    f"✅ <b>Спасибо за обратную связь!</b>\n\n"
                    f"🎫 <b>Номер тикета:</b> <code>#{ticket_number}</code>\n"
                    f"⏰ <b>Закрыт:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"🎉 Рады, что смогли помочь!\n"
                    f"💬 <i>Если у вас есть новые вопросы, просто напишите боту!</i>",
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"Ticket #{ticket_number} (topic {topic_id}) closed by user {user_id} via 'Помогло!'")
                
            else:
                # Тикет уже закрыт или не существует
                await query.edit_message_text("❌ Тикет не найден или уже закрыт.")
                logger.info(f"Пользователь {user_id} пытался закрыть уже закрытый тикет")
        
        except Exception as e:
            logger.error(f"Error closing ticket by user via 'Помогло!': {e}")
            # Не показываем ошибки (как в _close_ticket_by_user)
            try:
                await query.answer("Ошибка при закрытии", show_alert=False)
            except:
                pass

    async def handle_stop_ai_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает нажатие кнопки 'Остановить ИИ' оператором"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Извлекаем user_id из callback_data (формат: stop_ai_{user_id})
            callback_data = query.data
            if not callback_data.startswith("stop_ai_"):
                logger.error(f"Invalid callback data for stop AI: {callback_data}")
                return
            
            user_id = int(callback_data.split("_")[-1])
            operator = query.from_user
            
            logger.info(f"Operator {operator.id} ({operator.first_name}) stopping AI for user {user_id}")
            
            # Переключаем пользователя в режим оператора
            await self._stop_ai_for_user(query, context, user_id)
            
            # Удаляем кнопку из сообщения ИИ
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.warning(f"Could not remove button from AI message: {e}")
            
            # Уведомляем оператора об успешном отключении
            operator_display = f"{operator.first_name or ''} {operator.last_name or ''}".strip()
            if operator.username:
                operator_display += f" (@{operator.username})"
            
            # Лишнее сообщение удалено - используется только редактирование в stop_ai_for_user
            
            logger.info(f"AI successfully stopped for user {user_id} by operator {operator.id}")
                
        except Exception as e:
            logger.error(f"Error in handle_stop_ai_callback: {e}")
            try:
                await query.answer("❌ Произошла ошибка", show_alert=True)
            except:
                pass

    async def _block_user(self, query, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, topic_id: int = None) -> None:
        """Блокировка пользователя"""
        try:
            # Блокируем пользователя
            was_blocked = blocked_users.block_user(target_user_id)
            
            if was_blocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(target_user_id)
                    username = user_info.username
                except:
                    username = None
                
                # Обновляем клавиатуру в сообщении
                if topic_id:
                    new_keyboard = buttons.operator_keyboard(target_user_id, topic_id, is_blocked=True)
                    await query.edit_message_reply_markup(reply_markup=new_keyboard)
                    
                    # Изменяем иконку топика на "заблокирован"
                    await self.change_topic_icon(context, topic_id, 'blocked')
                    
                    # Отправляем уведомление в топик
                    notification = texts.user_blocked_notification(target_user_id, username)
                    await context.bot.send_message(
                        chat_id=self.support_chat_id,
                        message_thread_id=topic_id,
                        text=notification,
                        parse_mode=ParseMode.HTML
                    )
                
                await query.answer("✅ Пользователь заблокирован", show_alert=False)
                logger.info(f"User {target_user_id} blocked by admin {query.from_user.id}")
            else:
                await query.answer("Пользователь уже заблокирован", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error blocking user {target_user_id}: {e}")
            await query.answer("❌ Ошибка при блокировке", show_alert=True)
    
    async def _unblock_user(self, query, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, topic_id: int = None) -> None:
        """Разблокировка пользователя"""
        try:
            # Разблокируем пользователя
            was_unblocked = blocked_users.unblock_user(target_user_id)
            
            if was_unblocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(target_user_id)
                    username = user_info.username
                except:
                    username = None
                
                # Обновляем клавиатуру в сообщении
                if topic_id:
                    new_keyboard = buttons.operator_keyboard(target_user_id, topic_id, is_blocked=False)
                    await query.edit_message_reply_markup(reply_markup=new_keyboard)
                    
                    # Изменяем иконку топика на "активный" (возвращаем к нормальному состоянию)
                    await self.change_topic_icon(context, topic_id, 'active')
                    
                    # Отправляем уведомление в топик
                    notification = texts.user_unblocked_notification(target_user_id, username)
                    await context.bot.send_message(
                        chat_id=self.support_chat_id,
                        message_thread_id=topic_id,
                        text=notification,
                        parse_mode=ParseMode.HTML
                    )
                
                await query.answer("✅ Пользователь разблокирован", show_alert=False)
                logger.info(f"User {target_user_id} unblocked by admin {query.from_user.id}")
            else:
                await query.answer("Пользователь не был заблокирован", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error unblocking user {target_user_id}: {e}")
            await query.answer("❌ Ошибка при разблокировке", show_alert=True)
    
    async def _stop_ai_for_user(self, query, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> None:
        """Остановка ИИ для пользователя оператором"""
        try:
            # Переключаем пользователя в режим оператора
            self.ticket_state.set_operator_mode(target_user_id)
            
            # Очищаем историю ИИ-разговора
            self.ai_handler.clear_history(target_user_id)
            
            # Получаем информацию о пользователе
            try:
                user_info = await context.bot.get_chat(target_user_id)
                username = f"@{user_info.username}" if user_info.username else f"ID: {target_user_id}"
                user_name = user_info.first_name or "Неизвестно"
            except:
                username = f"ID: {target_user_id}"
                user_name = "Неизвестно"
            
            # Обновляем сообщение с информацией об отключении ИИ
            await query.edit_message_text(
                f"🔴 <b>ИИ отключен оператором</b>\n\n"
                f"👤 <b>Пользователь:</b> {username}\n"
                f"📝 <b>Имя:</b> {user_name}\n"
                f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                f"👨‍💼 <b>Оператор:</b> {query.from_user.first_name or 'Unknown'}\n\n"
                f"💬 <b>Теперь все сообщения пользователя будут переданы напрямую операторам.</b>",
                parse_mode=ParseMode.HTML
            )
            
            # Уведомляем пользователя об отключении ИИ
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text="👨‍💼 <b>Оператор подключился к вашему тикету</b>\n\n"
                         "Теперь ваши сообщения будут переданы напрямую оператору техподдержки. "
                         "Пожалуйста, опишите вашу проблему подробнее.",
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"User {target_user_id} notified about AI disabled by operator")
            except Exception as e:
                logger.error(f"Failed to notify user {target_user_id} about AI disabled: {e}")
            
            await query.answer("✅ ИИ отключен для пользователя", show_alert=False)
            logger.info(f"AI disabled for user {target_user_id} by operator {query.from_user.id}")
            
        except Exception as e:
            logger.error(f"Error stopping AI for user {target_user_id}: {e}")
            await query.answer("❌ Ошибка при отключении ИИ", show_alert=True)
    
    # === УПРАВЛЕНИЕ ИКОНКАМИ ТОПИКОВ ===
    
    async def change_topic_icon(self, context: ContextTypes.DEFAULT_TYPE, topic_id: int, status: str) -> bool:
        """
        Изменение иконки топика в зависимости от статуса
        
        Args:
            context: Контекст бота
            topic_id: ID топика
            status: Статус тикета ('new', 'active', 'closed', 'blocked')
            
        Returns:
            bool: True если иконка была изменена успешно
        """
        try:
            # Словарь соответствия статусов и custom emoji ID
            # Эти ID нужно получить из Telegram - они уникальны для каждого эмодзи
            status_emoji_ids = {
                'new': "5377316857231450742",      # ❓ (примерный ID)
                'active': "5312536423851630001",   # 🟡 (примерный ID)  
                'closed': "5312241539987020022",   # ✅ (примерный ID)
                'blocked': "5420331611830886484"   # 🚫 (примерный ID)
            }
            
            if status not in status_emoji_ids:
                logger.warning(f"Unknown status for topic icon: {status}")
                return False
            
            # Изменяем ТОЛЬКО иконку, не трогаем название
            await context.bot.edit_forum_topic(
                chat_id=self.support_chat_id,
                message_thread_id=topic_id,
                icon_custom_emoji_id=status_emoji_ids[status]
                # name НЕ указываем, чтобы не менять название
            )
            
            logger.info(f"Topic {topic_id} icon changed to {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to change topic icon for {topic_id}: {e}")
            # Fallback: если не получается с custom emoji, попробуем без иконки
            try:
                await context.bot.edit_forum_topic(
                    chat_id=self.support_chat_id,
                    message_thread_id=topic_id,
                    icon_custom_emoji_id=None  # Убираем иконку
                )
                logger.info(f"Topic {topic_id} icon removed as fallback")
                return True
            except Exception as e2:
                logger.error(f"Even fallback failed for topic {topic_id}: {e2}")
                return False
    
    # === КОМАНДЫ УПРАВЛЕНИЯ БЛОКИРОВКАМИ ===
    
    async def handle_support_chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка команд в чате поддержки (не пересылаются пользователям)"""
        message = update.message
        
        # Проверяем что это чат поддержки
        if message.chat.id != self.support_chat_id:
            return
        
        # Проверяем что это команда
        if not message.text or not message.text.startswith('/'):
            return
        
        command_parts = message.text.split()
        command = command_parts[0].lower()
        
        # Обрабатываем команды
        if command == '/help':
            await self._handle_help_command(update, context)
        elif command == '/block':
            await self._handle_block_command_chat(update, context, command_parts)
        elif command == '/unblock':
            await self._handle_unblock_command_chat(update, context, command_parts)
        elif command == '/blocklist':
            await self._handle_blocklist_command_chat(update, context)
        else:
            # Если команда не распознана, возвращаем False чтобы сообщение обработалось как обычно
            return False
        
        # Если команда была обработана, возвращаем True чтобы остановить дальнейшую обработку
        return True
    
    async def _handle_help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда помощи для администраторов"""
        help_text = (
            "🛠 <b>Команды администратора в чате поддержки</b>\n\n"
            
            "📋 <b>Управление блокировками:</b>\n"
            "• <code>/block user_id</code> - заблокировать пользователя\n"
            "• <code>/unblock user_id</code> - разблокировать пользователя\n"
            "• <code>/blocklist</code> - список заблокированных\n\n"
            
            "❓ <b>Справка:</b>\n"
            "• <code>/help</code> - показать эту справку\n\n"
            
            "📝 <b>Примеры использования:</b>\n"
            "• <code>/block 123456789</code>\n"
            "• <code>/unblock 123456789</code>\n\n"
            
            "ℹ️ <b>Особенности:</b>\n"
            "• Команды работают только в этом чате\n"
            "• Доступны всем участникам чата\n"
            "• Не пересылаются пользователям\n"
            "• Все действия логируются"
        )
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    
    async def _handle_block_command_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, command_parts: list) -> None:
        """Обработка команды блокировки в чате"""
        try:
            if len(command_parts) < 2:
                await update.message.reply_text(
                    "❓ <b>Использование:</b> <code>/block user_id</code>\n"
                    "<b>Пример:</b> <code>/block 123456789</code>",
                    parse_mode=ParseMode.HTML
                )
                return
            
            try:
                user_id = int(command_parts[1])
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя. Укажите числовой ID.")
                return
            
            # Блокируем пользователя
            was_blocked = blocked_users.block_user(user_id)
            
            if was_blocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else f"ID: {user_id}"
                    user_name = user_info.first_name or "Неизвестно"
                except:
                    username = f"ID: {user_id}"
                    user_name = "Неизвестно"
                
                # Уведомляем об успешной блокировке
                notification = (
                    f"🚫 <b>Пользователь заблокирован</b>\n\n"
                    f"👤 <b>Пользователь:</b> {username}\n"
                    f"📝 <b>Имя:</b> {user_name}\n"
                    f"⏰ <b>Заблокирован:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"👨‍💼 <b>Администратор:</b> @{update.effective_user.username or update.effective_user.first_name}"
                )
                
                await update.message.reply_text(notification, parse_mode=ParseMode.HTML)
                logger.info(f"User {user_id} blocked by chat command from {update.effective_user.id}")
                
            else:
                await update.message.reply_text(f"ℹ️ Пользователь <code>{user_id}</code> уже заблокирован.", parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error in chat block command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")
    
    async def _handle_unblock_command_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE, command_parts: list) -> None:
        """Обработка команды разблокировки в чате"""
        try:
            if len(command_parts) < 2:
                await update.message.reply_text(
                    "❓ <b>Использование:</b> <code>/unblock user_id</code>\n"
                    "<b>Пример:</b> <code>/unblock 123456789</code>",
                    parse_mode=ParseMode.HTML
                )
                return
            
            try:
                user_id = int(command_parts[1])
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя. Укажите числовой ID.")
                return
            
            # Разблокируем пользователя
            was_unblocked = blocked_users.unblock_user(user_id)
            
            if was_unblocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else f"ID: {user_id}"
                    user_name = user_info.first_name or "Неизвестно"
                except:
                    username = f"ID: {user_id}"
                    user_name = "Неизвестно"
                
                # Уведомляем об успешной разблокировке
                notification = (
                    f"✅ <b>Пользователь разблокирован</b>\n\n"
                    f"👤 <b>Пользователь:</b> {username}\n"
                    f"📝 <b>Имя:</b> {user_name}\n"
                    f"⏰ <b>Разблокирован:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"👨‍💼 <b>Администратор:</b> @{update.effective_user.username or update.effective_user.first_name}"
                )
                
                await update.message.reply_text(notification, parse_mode=ParseMode.HTML)
                logger.info(f"User {user_id} unblocked by chat command from {update.effective_user.id}")
                
            else:
                await update.message.reply_text(f"ℹ️ Пользователь <code>{user_id}</code> не был заблокирован.", parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error in chat unblock command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")
    
    async def _handle_blocklist_command_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать список заблокированных пользователей в чате"""
        try:
            blocked_list = blocked_users.get_blocked_users()
            
            if not blocked_list:
                await update.message.reply_text("ℹ️ Список заблокированных пользователей пуст.")
                return
            
            # Формируем список с информацией о пользователях
            users_info = []
            for user_id in blocked_list:
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else "—"
                    name = user_info.first_name or "Неизвестно"
                    users_info.append(f"• <code>{user_id}</code> | {username} | {name}")
                except:
                    users_info.append(f"• <code>{user_id}</code> | — | Неизвестно")
            
            message = (
                f"🚫 <b>Заблокированные пользователи ({len(blocked_list)})</b>\n\n"
                + "\n".join(users_info[:20])  # Показываем максимум 20
            )
            
            if len(blocked_list) > 20:
                message += f"\n\n<i>... и еще {len(blocked_list) - 20} пользователей</i>"
            
            message += (
                f"\n\n💡 <b>Команды управления:</b>\n"
                f"<code>/unblock user_id</code> - разблокировать\n"
                f"<code>/block user_id</code> - заблокировать"
            )
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error in chat blocklist command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении списка.")
    
    # === СТАРЫЕ КОМАНДЫ (для обратной совместимости) ===
    
    async def handle_unblock_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка команды разблокировки пользователя"""
        try:
            # Проверяем что команда от администратора
            from config import Config
            if update.effective_user.id not in Config.ADMIN_IDS:
                await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
                return
            
            # Получаем аргументы команды
            if not context.args:
                await update.message.reply_text(
                    "❓ <b>Использование:</b>\n"
                    "<code>/unblock user_id</code>\n\n"
                    "<b>Пример:</b>\n"
                    "<code>/unblock 123456789</code>",
                    parse_mode=ParseMode.HTML
                )
                return
            
            try:
                user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя. Укажите числовой ID.")
                return
            
            # Разблокируем пользователя
            was_unblocked = blocked_users.unblock_user(user_id)
            
            if was_unblocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else f"ID: {user_id}"
                    user_name = user_info.first_name or "Неизвестно"
                except:
                    username = f"ID: {user_id}"
                    user_name = "Неизвестно"
                
                # Уведомляем об успешной разблокировке
                notification = (
                    f"✅ <b>Пользователь разблокирован</b>\n\n"
                    f"👤 <b>Пользователь:</b> {username}\n"
                    f"📝 <b>Имя:</b> {user_name}\n"
                    f"⏰ <b>Разблокирован:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"👨‍💼 <b>Администратор:</b> @{update.effective_user.username or update.effective_user.first_name}"
                )
                
                await update.message.reply_text(notification, parse_mode=ParseMode.HTML)
                logger.info(f"User {user_id} unblocked by admin command from {update.effective_user.id}")
                
            else:
                await update.message.reply_text(f"ℹ️ Пользователь <code>{user_id}</code> не был заблокирован.", parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error in unblock command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")
    
    async def handle_block_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка команды блокировки пользователя"""
        try:
            # Проверяем что команда от администратора
            from config import Config
            if update.effective_user.id not in Config.ADMIN_IDS:
                await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
                return
            
            # Получаем аргументы команды
            if not context.args:
                await update.message.reply_text(
                    "❓ <b>Использование:</b>\n"
                    "<code>/block user_id</code>\n\n"
                    "<b>Пример:</b>\n"
                    "<code>/block 123456789</code>",
                    parse_mode=ParseMode.HTML
                )
                return
            
            try:
                user_id = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя. Укажите числовой ID.")
                return
            
            # Блокируем пользователя
            was_blocked = blocked_users.block_user(user_id)
            
            if was_blocked:
                # Получаем информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else f"ID: {user_id}"
                    user_name = user_info.first_name or "Неизвестно"
                except:
                    username = f"ID: {user_id}"
                    user_name = "Неизвестно"
                
                # Уведомляем об успешной блокировке
                notification = (
                    f"🚫 <b>Пользователь заблокирован</b>\n\n"
                    f"👤 <b>Пользователь:</b> {username}\n"
                    f"📝 <b>Имя:</b> {user_name}\n"
                    f"⏰ <b>Заблокирован:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                    f"👨‍💼 <b>Администратор:</b> @{update.effective_user.username or update.effective_user.first_name}"
                )
                
                await update.message.reply_text(notification, parse_mode=ParseMode.HTML)
                logger.info(f"User {user_id} blocked by admin command from {update.effective_user.id}")
                
            else:
                await update.message.reply_text(f"ℹ️ Пользователь <code>{user_id}</code> уже заблокирован.", parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error in block command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")
    
    async def handle_blocklist_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать список заблокированных пользователей"""
        try:
            # Проверяем что команда от администратора
            from config import Config
            if update.effective_user.id not in Config.ADMIN_IDS:
                await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
                return
            
            blocked_list = blocked_users.get_blocked_users()
            
            if not blocked_list:
                await update.message.reply_text("ℹ️ Список заблокированных пользователей пуст.")
                return
            
            # Формируем список с информацией о пользователях
            users_info = []
            for user_id in blocked_list:
                try:
                    user_info = await context.bot.get_chat(user_id)
                    username = f"@{user_info.username}" if user_info.username else "—"
                    name = user_info.first_name or "Неизвестно"
                    users_info.append(f"• <code>{user_id}</code> | {username} | {name}")
                except:
                    users_info.append(f"• <code>{user_id}</code> | — | Неизвестно")
            
            message = (
                f"🚫 <b>Заблокированные пользователи ({len(blocked_list)})</b>\n\n"
                + "\n".join(users_info[:20])  # Показываем максимум 20
            )
            
            if len(blocked_list) > 20:
                message += f"\n\n<i>... и еще {len(blocked_list) - 20} пользователей</i>"
            
            message += (
                f"\n\n💡 <b>Команды управления:</b>\n"
                f"<code>/unblock user_id</code> - разблокировать\n"
                f"<code>/block user_id</code> - заблокировать"
            )
            
            await update.message.reply_text(message, parse_mode=ParseMode.HTML)
            
        except Exception as e:
            logger.error(f"Error in blocklist command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении списка.")
