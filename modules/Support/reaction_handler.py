#!/usr/bin/env python3
"""
Обработчик реакций для Support Bot
Позволяет передавать реакции между пользователями и админами
"""

import logging
from telegram import Update, MessageReactionUpdated
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from config import Config
from topic_storage import TopicStorage

logger = logging.getLogger(__name__)

class ReactionHandler:
    """Обработчик реакций на сообщения"""
    
    def __init__(self, storage: TopicStorage):
        self.storage = storage
    
    async def handle_message_reaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обрабатывает обновления реакций на сообщения"""
        try:
            reaction_update: MessageReactionUpdated = update.message_reaction
            if not reaction_update:
                return
            
            message = reaction_update.message
            user = reaction_update.user
            chat = reaction_update.chat
            
            # Получаем новые реакции (добавленные)
            new_reactions = reaction_update.new_reaction
            old_reactions = reaction_update.old_reaction
            
            if not new_reactions or len(new_reactions) == 0:
                # Реакция была удалена, не обрабатываем
                return
            
            logger.info(f"Reaction added by user {user.id} in chat {chat.id} on message {message.message_id}")
            
            # Если реакция в приватном чате пользователя
            if chat.type == 'private' and chat.id != Config.SUPPORT_CHAT_ID:
                await self._forward_user_reaction_to_admin(update, context, reaction_update)
            
            # Если реакция в чате поддержки (от админа)
            elif chat.id == Config.SUPPORT_CHAT_ID:
                await self._forward_admin_reaction_to_user(update, context, reaction_update)
                
        except Exception as e:
            logger.error(f"Error handling message reaction: {e}")
    
    async def _forward_user_reaction_to_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                            reaction_update: MessageReactionUpdated) -> None:
        """Пересылает реакцию пользователя админам в чат поддержки"""
        try:
            user_id = reaction_update.user.id
            message_id = reaction_update.message.message_id
            
            # Находим топик пользователя
            topic_id = self.storage.get_topic_for_user(user_id)
            if not topic_id:
                logger.debug(f"No topic found for user {user_id}, cannot forward reaction")
                return
            
            # Получаем реакции
            reactions = reaction_update.new_reaction
            if not reactions:
                return
            
            # Формируем текст с реакциями
            reaction_emojis = []
            for reaction in reactions:
                if hasattr(reaction, 'emoji'):
                    reaction_emojis.append(reaction.emoji)
                elif hasattr(reaction, 'custom_emoji_id'):
                    reaction_emojis.append(f"[custom:{reaction.custom_emoji_id}]")
            
            if not reaction_emojis:
                return
            
            # Отправляем уведомление в топик
            notification_text = (
                f"👤 Пользователь поставил реакцию: {' '.join(reaction_emojis)}\n"
                f"📝 На сообщение ID: {message_id}"
            )
            
            await context.bot.send_message(
                chat_id=Config.SUPPORT_CHAT_ID,
                message_thread_id=topic_id,
                text=notification_text
            )
            
            logger.info(f"Forwarded user reaction to admin chat: {' '.join(reaction_emojis)}")
            
        except Exception as e:
            logger.error(f"Error forwarding user reaction to admin: {e}")
    
    async def _forward_admin_reaction_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                                            reaction_update: MessageReactionUpdated) -> None:
        """Пересылает реакцию админа пользователю"""
        try:
            admin_user = reaction_update.user
            message = reaction_update.message
            
            # Проверяем, что у сообщения есть thread_id (топик)
            if not message.message_thread_id:
                return
            
            topic_id = message.message_thread_id
            
            # Находим пользователя по топику
            user_id = self.storage.get_user_for_topic(topic_id)
            if not user_id:
                logger.debug(f"No user found for topic {topic_id}")
                return
            
            # Получаем реакции
            reactions = reaction_update.new_reaction
            if not reactions:
                return
            
            # Формируем текст с реакциями
            reaction_emojis = []
            for reaction in reactions:
                if hasattr(reaction, 'emoji'):
                    reaction_emojis.append(reaction.emoji)
                elif hasattr(reaction, 'custom_emoji_id'):
                    reaction_emojis.append(f"[custom:{reaction.custom_emoji_id}]")
            
            if not reaction_emojis:
                return
            
            # Отправляем уведомление пользователю
            notification_text = (
                f"⚡ Агент тех поддержки поставил реакцию: {' '.join(reaction_emojis)}\n"
                f"📝 На ваше сообщение"
            )
            
            await context.bot.send_message(
                chat_id=user_id,
                text=notification_text
            )
            
            logger.info(f"Forwarded admin reaction to user {user_id}: {' '.join(reaction_emojis)}")
            
        except Exception as e:
            logger.error(f"Error forwarding admin reaction to user: {e}")
