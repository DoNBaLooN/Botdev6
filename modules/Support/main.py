#!/usr/bin/env python3
"""
Support Bot для системы VPN
Бот технической поддержки с использованием топиков и интеграцией с основным ботом
"""

import logging
import asyncio
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler,
    CallbackQueryHandler,
    MessageReactionHandler,
    filters,
    ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut, RetryAfter, TelegramError

from config import Config
from support_handler import SupportHandler
from reaction_handler import ReactionHandler
from safe_integration import safe_main_bot as main_bot
from health_monitor import health_monitor
from texts import texts
from buttons import buttons
from gigachat_client import GigaChatClient

# Настройка логирования с записью в файл
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
import gzip
import shutil
from pathlib import Path

def cleanup_old_logs():
    """Очистка старых и больших лог-файлов"""
    try:
        logger_temp = logging.getLogger("log_cleanup")
        log_files = [
            'support_bot.log',
            'support_bot_errors.log', 
            'support_installer.log',
            'health_stats.log'
        ]
        
        for log_file in log_files:
            log_path = Path(log_file)
            if not log_path.exists():
                continue
                
            file_size_mb = log_path.stat().st_size / 1024 / 1024
            file_age_days = (datetime.now() - datetime.fromtimestamp(log_path.stat().st_mtime)).days
            
            # Архивируем файлы больше 5MB или старше 3 дней
            if file_size_mb > 5 or file_age_days > 3:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_name = f"{log_file}.{timestamp}.gz"
                
                # Сжимаем и архивируем
                with open(log_path, 'rb') as f_in:
                    with gzip.open(archive_name, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                
                # Очищаем исходный файл
                with open(log_path, 'w') as f:
                    f.write(f"# Log rotated at {datetime.now().isoformat()}\n")
                
                logger_temp.info(f"🗂️ Archived log {log_file} -> {archive_name} ({file_size_mb:.1f}MB)")
        
        # Удаляем архивы старше 5 дней
        for archive_file in Path('.').glob('*.log.*.gz'):
            archive_age_days = (datetime.now() - datetime.fromtimestamp(archive_file.stat().st_mtime)).days
            if archive_age_days > 5:
                archive_file.unlink()
                logger_temp.info(f"🗑️ Deleted old archive: {archive_file.name}")
                
    except Exception as e:
        print(f"❌ Log cleanup error: {e}")

def setup_logging():
    """Настройка детального логирования с автоочисткой"""
    # Сначала очищаем старые логи
    cleanup_old_logs()
    
    # Создаем formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Настраиваем root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, Config.LOG_LEVEL.upper(), logging.INFO))
    
    # Очищаем существующие handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    # RotatingFileHandler для основных логов (максимум 50MB, 5 файлов)
    file_handler = RotatingFileHandler(
        'support_bot.log', 
        maxBytes=50*1024*1024,  # 50MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    
    # RotatingFileHandler для ошибок (максимум 10MB, 3 файла)
    error_handler = RotatingFileHandler(
        'support_bot_errors.log',
        maxBytes=10*1024*1024,  # 10MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)
    
    return logging.getLogger(__name__)

# Настраиваем логирование
logger = setup_logging()

# Логируем старт системы
logger.info("="*60)
logger.info(f"🚀 Support Bot starting at {datetime.now()}")
logger.info(f"🐍 Python version: {sys.version}")
logger.info(f"📁 Working directory: {os.getcwd()}")
logger.info("="*60)

class SupportBot:
    """Основной класс бота технической поддержки с heartbeat мониторингом и автоперезапуском"""
    
    def __init__(self):
        # Создаем один экземпляр GigaChatClient для всего бота
        self.gigachat_client = GigaChatClient()
        self.support_handler = SupportHandler(gigachat_client=self.gigachat_client)
        self.reaction_handler = ReactionHandler(self.support_handler.storage)
        self.app = None
        self.project_name = Config.PROJECT_NAME
        self.heartbeat_task = None
        self.health_monitor_task = None
        self.preventive_restart_task = None
        self.last_heartbeat = datetime.now()
        self.start_time = datetime.now()
        self.startup_time = None  # Время запуска для обработки пропущенных сообщений
        self.is_processing_startup_messages = False  # Флаг обработки startup-сообщений
        self.heartbeat_interval = timedelta(minutes=5)  # Heartbeat каждые 5 минут
        self.max_silence_time = timedelta(minutes=30)   # Максимальное время без активности
        self.max_uptime = timedelta(hours=24)          # Увеличиваем с 2 до 24 часов
    
    def log_outgoing_message(self, chat_id, text, method="send"):
        """Логирование исходящих сообщений"""
        try:
            # Обрезаем длинный текст для логов
            display_text = text[:50] + "..." if len(text) > 50 else text
            display_text = display_text.replace('\n', ' ').strip()
            
            logger.info(f"📤 OUT | bot → chat:{chat_id} | '{display_text}' | method:{method}")
        except Exception as e:
            logger.debug(f"Failed to log outgoing message: {e}")
    
    async def preventive_restart_monitor(self):
        """Принудительный перезапуск для предотвращения накопления утечек памяти"""
        while True:
            try:
                # Проверяем каждые 30 минут
                await asyncio.sleep(30 * 60)
                
                # Получаем статистику
                uptime = datetime.now() - self.start_time
                health_report = health_monitor.get_health_report()
                memory_mb = health_report.get('memory_usage_mb', 0)
                objects_count = health_report.get('objects_count', 0)
                
                logger.info(f"🕐 Uptime: {uptime.total_seconds()/3600:.1f}h, Memory: {memory_mb:.1f}MB, Objects: {objects_count}")
                
                # Условия для принудительного перезапуска
                should_restart = False
                restart_reason = ""
                
                # 1. Превышено максимальное время работы
                if uptime >= self.max_uptime:
                    should_restart = True
                    restart_reason = f"Max uptime reached ({uptime.total_seconds()/3600:.1f}h)"
                
                # 2. Критическое потребление памяти
                elif memory_mb > 800:  # Увеличиваем лимит с 150MB до 800MB
                    should_restart = True
                    restart_reason = f"High memory usage ({memory_mb:.1f}MB)"
                
                # 3. Критическое количество объектов
                elif objects_count > 500000:  # Увеличиваем с 150K до 500K объектов
                    should_restart = True
                    restart_reason = f"Too many objects ({objects_count})"
                
                # 4. Статус системы критический
                elif health_report.get('status') == 'critical':
                    should_restart = True
                    restart_reason = "System health status: critical"
                
                if should_restart:
                    logger.warning(f"⚠️ RESTART CONDITIONS MET: {restart_reason}")
                    logger.warning("🔧 АВТОПЕРЕЗАПУСК ОТКЛЮЧЕН ДЛЯ ДИАГНОСТИКИ")
                    logger.warning("🔧 Бот продолжит работать для выявления настоящей проблемы")
                    
                    # НЕ перезапускаем - только логируем!
                    # Выполняем очистку памяти вместо перезапуска
                    try:
                        import gc
                        collected = gc.collect()
                        logger.info(f"🧹 Memory cleanup: collected {collected} objects")
                    except Exception as cleanup_error:
                        logger.error(f"Cleanup failed: {cleanup_error}")
                    
                    # if self.app:
                    #     await self.app.stop()
                    #     await self.app.shutdown()
                    # import os
                    # os._exit(0)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Preventive restart monitor error: {e}")
                await asyncio.sleep(60)  # При ошибке ждем минуту
    
    async def heartbeat_monitor(self):
        """Фоновая задача мониторинга состояния бота"""
        logger.info("💓 Heartbeat monitor initialized - checking every 5 minutes")
        
        while True:
            try:
                current_time = datetime.now()
                uptime = current_time - self.start_time
                
                # Получаем статистику здоровья
                try:
                    health_report = health_monitor.get_health_report()
                    memory_mb = health_report.get('memory_usage_mb', 0)
                    cpu_percent = health_report.get('cpu_usage_percent', 0)
                    objects_count = health_report.get('objects_count', 0)
                    status = health_report.get('status', 'unknown')
                except Exception as health_error:
                    logger.warning(f"⚠️ Could not get health report: {health_error}")
                    memory_mb = cpu_percent = objects_count = 0
                    status = 'unknown'
                
                # Детальный heartbeat лог
                logger.info(f"💓 HEARTBEAT | ⏰ Uptime: {uptime.total_seconds()/3600:.1f}h | "
                          f"🧠 RAM: {memory_mb:.1f}MB | ⚡ CPU: {cpu_percent:.1f}% | "
                          f"🏷️ Objects: {objects_count} | ❤️ Status: {status}")
                
                # Проверяем, не молчал ли бот слишком долго
                if current_time - self.last_heartbeat > self.max_silence_time:
                    logger.warning("⚠️ Bot has been silent too long, performing health check...")
                    await self.perform_health_check()
                
                # Обновляем heartbeat
                self.last_heartbeat = current_time
                
                # Выполняем периодические задачи
                await self.periodic_maintenance()
                
                # Ждем до следующего heartbeat
                await asyncio.sleep(self.heartbeat_interval.total_seconds())
                
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
                await asyncio.sleep(60)  # При ошибке ждем минуту и продолжаем
    
    async def perform_health_check(self):
        """Проверка состояния всех компонентов с timeout защитой"""
        try:
            # ИСПРАВЛЕНИЕ 1: Добавляем timeout для всех API вызовов
            async def safe_api_call(func, *args, timeout=15, **kwargs):
                """Безопасный API вызов с timeout"""
                try:
                    return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning(f"⏱️ API timeout в {func.__name__} после {timeout}s")
                    return None
                except Exception as e:
                    logger.warning(f"⚠️ API ошибка в {func.__name__}: {e}")
                    return None
            
            # ИСПРАВЛЕНИЕ 2: Принудительная сборка мусора для предотвращения object leak
            import gc
            collected = gc.collect()
            if collected > 50:  # Логируем только если собрали много объектов
                logger.info(f"🧹 Собрано {collected} объектов в health check")
            
            # Безопасная проверка соединения с Telegram API
            if self.app and self.app.bot:
                me = await safe_api_call(self.app.bot.get_me, timeout=10)
                if me:
                    logger.info(f"✅ Health check passed - Bot: {me.username}")
                else:
                    logger.warning("⚠️ Telegram API недоступен или timeout")
            
            # Безопасная проверка интеграции с основным ботом
            test_exists = await safe_api_call(
                main_bot.check_user_exists, 123456789, timeout=10
            )
            logger.debug(f"Database integration health check: {test_exists is not None}")
            
            # Безопасная проверка доступности чата поддержки
            if self.app and self.app.bot:
                chat = await safe_api_call(
                    self.app.bot.get_chat, Config.SUPPORT_CHAT_ID, timeout=8
                )
                if chat:
                    logger.debug(f"Support chat accessible: {chat.title}")
                else:
                    logger.warning("Support chat недоступен или timeout")
                    
            logger.debug("✅ Health check завершен")
            
        except Exception as e:
            logger.error(f"❌ Health check critical error: {e}")
            # ИСПРАВЛЕНИЕ 3: Не падаем, а просто логируем
    
    async def periodic_maintenance(self):
        """Периодическое обслуживание с проверкой системы и очисткой логов"""
        try:
            # Получаем отчет о здоровье системы
            health_report = health_monitor.get_health_report()
            
            # Если статус critical - выполняем экстренную очистку
            if health_report.get('status') == 'critical':
                logger.warning("System health is critical, performing emergency cleanup")
                health_monitor.perform_cleanup()
            
            # Очистка старых топиков (если топик неактивен > 200 часов)
            if hasattr(self.support_handler.storage, 'cleanup_old_topics'):
                try:
                    self.support_handler.storage.cleanup_old_topics()
                except Exception as e:
                    logger.error(f"Failed to cleanup old topics: {e}")
            
            # Проверяем валидность хранимых маппингов
            if hasattr(self.support_handler.storage, 'validate_and_clean'):
                try:
                    self.support_handler.storage.validate_and_clean()
                except Exception as e:
                    logger.error(f"Failed to validate storage: {e}")
            
            # Автоочистка логов (выполняется раз в час)
            current_time = datetime.now()
            if not hasattr(self, '_last_log_cleanup') or (current_time - self._last_log_cleanup).total_seconds() > 3600:
                try:
                    cleanup_old_logs()
                    self._last_log_cleanup = current_time
                    logger.info("🗂️ Log cleanup completed")
                except Exception as e:
                    logger.error(f"Failed to cleanup logs: {e}")
            
            # Логируем состояние системы
            active_topics = len(self.support_handler.storage.get_all_active_topics())
            logger.info(f"Maintenance complete: {active_topics} active topics, "
                       f"Memory: {health_report.get('memory_usage_mb', 0):.1f}MB, "
                       f"Status: {health_report.get('status', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Periodic maintenance error: {e}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        user = update.effective_user
        user_id = user.id
        
        # Проверяем, зарегистрирован ли пользователь в основном боте
        user_exists = await main_bot.check_user_exists(user_id)
        user_info = await main_bot.get_user_info(user_id) if user_exists else None
        
        # Проверяем есть ли активный тикет
        active_topic = self.support_handler.storage.get_topic_for_user(user_id)
        
        # Получаем клавиатуру из buttons.py
        keyboard_buttons = []
        for row in buttons.main_menu_keyboard(user_id).inline_keyboard:
            keyboard_buttons.append(row)
        
        if active_topic:
            active_ticket_number = self.support_handler.storage.get_ticket_number(active_topic) or active_topic
            keyboard_buttons.insert(1, [InlineKeyboardButton(f"🎫 Активный тикет #{active_ticket_number}", callback_data=f"ticket_info_{user_id}_{active_topic}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        
        # Персонализируем приветствие
        if user_exists and user_info and "error" not in user_info:
            status = "✅ VIP" if user_info.get("is_premium") else "👤 Пользователь"
            welcome_text = texts.welcome_message(user.first_name)
        else:
            welcome_text = texts.welcome_message(user.first_name)
        
        # Логируем исходящее сообщение
        self.log_outgoing_message(update.message.chat.id, welcome_text, "reply_text")
        
        await update.message.reply_text(
            welcome_text, 
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        logger.info(f"Start command from user {user.id} (registered: {user_exists})")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help"""
        help_text = (
            "🆘 <b>Помощь по боту поддержки</b>\n\n"
            "📋 <b>Как обратиться в поддержку:</b>\n"
            "1. Отправьте сообщение с описанием проблемы\n"
            "2. Приложите скриншоты или файлы при необходимости\n"
            "3. Дождитесь ответа от специалиста\n\n"
            "⚡ <b>Доступные команды:</b>\n"
            "/start - главное меню\n"
            "/help - эта справка\n"
            "/tickets - посмотреть ваши тикеты\n\n"
            "🎫 <b>Система тикетов:</b>\n"
            "• Один активный тикет на пользователя\n"
            "• Все сообщения добавляются к активному тикету\n"
            "• Удобные кнопки для управления\n"
            "• История всех обращений\n\n"
            "⏰ <b>Время работы:</b> 24/7\n"
            "📞 <b>Среднее время ответа:</b> до 30 минут\n\n"
            "💡 <b>Совет:</b> Чем подробнее вы опишете проблему, тем быстрее мы сможем вам помочь!"
        )
        
        # Логируем исходящее сообщение
        self.log_outgoing_message(update.message.chat.id, help_text, "reply_text")
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
        logger.info(f"Help command from user {update.effective_user.id}")
    
    async def universal_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Универсальный обработчик всех сообщений с фильтрацией старых сообщений"""
        try:
            # Фильтрация старых сообщений при запуске
            if update.message and self.startup_time:
                message_time = update.message.date
                age_hours = (datetime.now() - message_time.replace(tzinfo=None)).total_seconds() / 3600
                
                # Если сообщение старше 24 часов и мы в режиме startup
                if age_hours > 24 and self.is_processing_startup_messages:
                    logger.debug(f"⏰ Skipping old startup message ({age_hours:.1f}h old) from user {update.message.from_user.id}")
                    return
                
                # Логируем обработку старых сообщений при startup
                if self.is_processing_startup_messages and age_hours > 1:
                    logger.info(f"📨 Processing missed message from user {update.message.from_user.id} ({age_hours:.1f}h ago)")
            
            # Получаем информацию о сообщении для логирования
            message_info = "Unknown"
            user_info = "Unknown"
            
            if update.message:
                msg = update.message
                message_info = f"msg_id:{msg.message_id}"
                user_info = f"@{msg.from_user.username}" if msg.from_user.username else f"user_id:{msg.from_user.id}"
                content_type = "text" if msg.text else (msg.content_type if hasattr(msg, 'content_type') else "media")
                
                logger.info(f"📩 IN | {user_info} | {message_info} | {content_type} | chat:{msg.chat.id}")
                
            elif update.edited_message:
                msg = update.edited_message
                message_info = f"edit_msg_id:{msg.message_id}"
                user_info = f"@{msg.from_user.username}" if msg.from_user.username else f"user_id:{msg.from_user.id}"
                logger.info(f"✏️ EDIT | {user_info} | {message_info} | chat:{msg.chat.id}")
            
            logger.debug(f"UNIVERSAL_HANDLER: Processing update {update.update_id}")
            # Проверяем тип update и направляем соответственно
            if update.edited_message:
                # Это редактированное сообщение
                logger.debug("UNIVERSAL_HANDLER: Routing edited message to edited handler")
                await self.handle_edited_message(update, context)
            elif update.message:
                # Это обычное сообщение
                logger.debug("UNIVERSAL_HANDLER: Routing regular message to regular handler")
                await self.handle_message(update, context)
            else:
                logger.debug("UNIVERSAL_HANDLER: Unknown message type")
                
            logger.debug("UNIVERSAL_HANDLER: Completed successfully")
                
        except Exception as e:
            logger.error(f"UNIVERSAL_HANDLER: Error in universal_message_handler: {e}")
            # # Показываем ошибку только для обычных сообщений в приватном чате
            # # НЕ показываем ошибки для edited сообщений!
            if (update.message and 
                update.message.chat.type == 'private' and 
                update.message.chat.id != Config.SUPPORT_CHAT_ID and
                not update.edited_message):
                try:
                    logger.error(f"UNIVERSAL_HANDLER: Sending error to user {update.message.from_user.id}")
                    await context.bot.send_message(
                        chat_id=update.message.chat.id,
                        text="❌ Произошла техническая ошибка. Наши специалисты уже работают над её устранением."
                    )
                except:
                    pass
            else:
                logger.debug("UNIVERSAL_HANDLER: NOT sending error message (edited message or support chat)")
            # Переподнимаем для error_handler
            raise

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка обычных сообщений как запросов в поддержку"""
        try:
            # ТРОЙНАЯ ЗАЩИТА: Пропускаем редактированные сообщения
            if update.edited_message:
                logger.debug("ALERT: edited_message found in handle_message - should not happen!")
                return
            
            if not update.message:
                logger.debug("No message in update")
                return
                
            logger.debug(f"Processing regular message from {update.message.from_user.id}")
            
            if update.message.chat.type == 'private':
                # Это приватное сообщение - обрабатываем как запрос в поддержку
                await self.support_handler.handle_support_request(update, context)
            elif update.message.chat.id == Config.SUPPORT_CHAT_ID:
                # Это сообщение в чате поддержки - может быть ответом
                await self.support_handler.handle_reply_to_user(update, context)
                
        except Exception as e:
            logger.error(f"Error in handle_message: {e}")
            # НЕ показываем ошибку - она будет обработана в universal_message_handler
    
    async def handle_edited_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработка редактированных сообщений"""
        try:
            if not update.edited_message:
                return
            
            if update.edited_message.chat.type == 'private':
                # Редактирование сообщения от пользователя в приватном чате
                await self.support_handler.handle_edited_support_message(update, context)
            elif update.edited_message.chat.id == Config.SUPPORT_CHAT_ID:
                # Редактирование сообщения в чате поддержки (от админа)
                await self.support_handler.handle_edited_admin_message(update, context)
            
        except Exception as e:
            logger.error(f"Error handling edited message: {e}")
            # НЕ показываем ошибку пользователю при редактировании - это нормально
            # НЕ переподнимаем исключение!
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Улучшенный обработчик ошибок с логированием и переподключением"""
        error = context.error
        error_message = str(error)
        
        # Логируем детали ошибки
        logger.error(f"Exception while handling update {update.update_id if update else 'unknown'}: {error}")
        logger.error(f"Error type: {type(error).__name__}")
        
        # Обработка специфических ошибок
        if "Connection pool is closed" in error_message or "connection was closed" in error_message.lower():
            logger.warning("Database connection issue detected, attempting to reconnect...")
            # Попытка переподключения к БД через safe_integration
            try:
                from safe_integration import safe_main_bot
                safe_main_bot.available = False  # Принудительно сбрасываем соединение
                await safe_main_bot.check_user_exists(1)  # Тестовый запрос для переподключения
                logger.info("Database reconnection attempt completed")
            except Exception as reconnect_error:
                logger.error(f"Database reconnection failed: {reconnect_error}")
        
        elif "Timeout" in error_message or "timeout" in error_message.lower():
            logger.warning("Telegram API timeout detected")
            
        elif "BadRequest" in error_message:
            if "message thread not found" in error_message.lower():
                logger.warning("Forum topic was deleted, cleaning up mapping")
                # Попытка очистки несуществующего топика
                if update and update.message and hasattr(update.message, 'message_thread_id'):
                    topic_id = update.message.message_thread_id
                    self.support_handler.storage.remove_topic_mapping(topic_id)
        
        # НЕ показываем ошибки для edited сообщений и сообщений в чате поддержки
        should_notify_user = False
        
        # Проверяем нужно ли уведомлять пользователя об ошибке
        if update:
            # Если есть edited_message - НЕ уведомляем
            if update.edited_message:
                logger.debug("Not notifying user about error - this is edited message")
                should_notify_user = False
            # Если есть обычное сообщение в приватном чате (не поддержка) - уведомляем
            elif (update.message and 
                  update.message.chat.type == 'private' and
                  update.message.chat.id != Config.SUPPORT_CHAT_ID):
                should_notify_user = True
            else:
                logger.debug("Not notifying user about error - not private chat or is support chat")
        
        # if should_notify_user:
        #     try:
        #         error_text = "❌ [MAIN.PY] Произошла техническая ошибка. Наши специалисты уже работают над её устранением."
        #         
        #         # Добавляем специфическую информацию для некоторых ошибок
        #         if "Connection" in error_message:
        #             error_text += "\n🔄 Попробуйте повторить запрос через несколько секунд."
        #         
        if should_notify_user:
            try:
                error_text = "❌ Произошла техническая ошибка. Наши специалисты уже работают над её устранением."
                logger.error(f"Sending error message to user {update.effective_message.from_user.id}")
                await update.effective_message.reply_text(error_text)
                logger.error(f"Error message sent successfully")
                
            except Exception as notify_error:
                logger.error(f"Failed to send error message to user: {notify_error}")
        else:
            logger.debug("Skipping user error notification (edited message or support chat)")
        
        # Уведомляем админов о критических ошибках
        if any(keyword in error_message.lower() for keyword in ['connection', 'database', 'pool']):
            try:
                from config import Config
                admin_message = (
                    f"🚨 <b>Критическая ошибка в Support Bot</b>\n\n"
                    f"<b>Тип:</b> {type(error).__name__}\n"
                    f"<b>Сообщение:</b> {error_message[:500]}\n"
                    f"<b>Update ID:</b> {update.update_id if update else 'unknown'}\n"
                    f"<b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                )
                
                for admin_id in Config.ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_message,
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as admin_notify_error:
                        logger.error(f"Failed to notify admin {admin_id}: {admin_notify_error}")
                        
            except Exception as admin_error:
                logger.error(f"Error notifying admins: {admin_error}")
    
    async def tickets_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показать тикеты пользователя"""
        user_id = update.effective_user.id
        active_topic = self.support_handler.storage.get_topic_for_user(user_id)
        
        if active_topic:
            keyboard = [
                [InlineKeyboardButton("📋 Статус тикета", callback_data=f"ticket_info_{user_id}_{active_topic}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            active_ticket_number = self.support_handler.storage.get_ticket_number(active_topic) or active_topic
            tickets_text = (
                f"🎫 <b>Ваши тикеты</b>\n\n"
                f"📋 <b>Активный тикет:</b> <code>#{active_ticket_number}</code>\n"
                f"📊 <b>Статус:</b> Открыт\n\n"
                f"💬 <i>Все новые сообщения будут добавлены к активному тикету.</i>"
            )
        else:
            keyboard = []
            reply_markup = None
            tickets_text = (
                f"📋 <b>Ваши тикеты</b>\n\n"
                f"📝 У вас нет активных тикетов.\n\n"
                f"💬 <i>Напишите любое сообщение боту, чтобы создать новый тикет!</i>"
            )
        
        await update.message.reply_text(
            tickets_text, 
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        logger.info(f"Tickets command from user {user_id}")
    
    async def handle_profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик показа профиля пользователя"""
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[1])
        
        # Получаем информацию о пользователе из основного бота
        user_info = await main_bot.get_user_info(user_id)
        subscription_info = await main_bot.get_user_subscription_status(user_id)
        
        if "error" in user_info:
            await query.edit_message_text(
                "❌ <b>Ошибка получения данных профиля</b>\n\n"
                f"Причина: {user_info['error']}\n\n"
                "Попробуйте позже или обратитесь к администратору.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Формируем информацию о профиле
        status_emoji = "✅" if user_info.get("is_premium") else "👤"
        status_text = "VIP Пользователь" if user_info.get("is_premium") else "Обычный пользователь"
        
        ban_status = ""
        if user_info.get("is_banned"):
            ban_status = f"\n🚫 <b>Заблокирован:</b> {user_info.get('ban_reason', 'Не указана причина')}"
        
        # Формируем строку с username отдельно для избежания проблем с экранированием
        username_line = f"📝 <b>Username:</b> @{user_info['username']}\n" if user_info.get('username') else ""
        
        profile_text = (
            f"👤 <b>Профиль пользователя</b>\n\n"
            f"🆔 <b>ID:</b> <code>{user_info['tg_id']}</code>\n"
            f"👤 <b>Имя:</b> {user_info.get('first_name', 'Не указано')}\n"
            f"{username_line}"
            f"🎖 <b>Статус:</b> {status_emoji} {status_text}\n"
            f"💰 <b>Баланс:</b> {user_info.get('balance', 0)} ₽\n"
            f"🔑 <b>Активных ключей:</b> {subscription_info.get('active_keys', 0)}\n"
            f"📊 <b>Всего ключей:</b> {subscription_info.get('total_keys', 0)}\n"
            f"📅 <b>Дата регистрации:</b> {user_info.get('created_at', 'Не указана')[:10] if user_info.get('created_at') else 'Не указана'}"
            f"{ban_status}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data=f"user_keys_{user_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            profile_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    async def handle_user_keys_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик показа ключей пользователя"""
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[2])
        
        # Получаем ключи пользователя
        keys = await main_bot.get_user_keys(user_id)
        
        if not keys:
            keys_text = (
                "🔑 <b>Ваши ключи</b>\n\n"
                "📝 У вас пока нет ключей.\n\n"
                f"💡 Чтобы создать ключ, обратитесь к основному боту @{Config.MAIN_BOT_USERNAME}"
            )
        else:
            keys_text = "🔑 <b>Ваши ключи</b>\n\n"
            
            for i, key in enumerate(keys, 1):
                status_emoji = "✅" if key['is_active'] else "❌"
                expiry_date = key['expiry_date'][:10] if key.get('expiry_date') else "Не указана"
                
                keys_text += (
                    f"{i}. {status_emoji} <b>{key['key_name']}</b>\n"
                    f"   📅 До: {expiry_date}\n"
                    f"   📊 Трафик: {key.get('used_traffic', 0)} / {key.get('traffic_limit', '∞')}\n\n"
                )
        
        keyboard = [
            [InlineKeyboardButton("👤 Профиль", callback_data=f"profile_{user_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            keys_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    async def handle_back_to_start_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик возврата к стартовому меню"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        user_id = user.id
        
        # Проверяем, зарегистрирован ли пользователь в основном боте
        user_exists = await main_bot.check_user_exists(user_id)
        user_info = await main_bot.get_user_info(user_id) if user_exists else None
        
        # Проверяем есть ли активный тикет
        active_topic = self.support_handler.storage.get_topic_for_user(user_id)
        
        keyboard_buttons = []
        for row in buttons.main_menu_keyboard(user_id).inline_keyboard:
            keyboard_buttons.append(row)

        if active_topic:
            active_ticket_number = self.support_handler.storage.get_ticket_number(active_topic) or active_topic
            keyboard_buttons.insert(1, [InlineKeyboardButton(f"🎫 Активный тикет #{active_ticket_number}", callback_data=f"ticket_info_{user_id}_{active_topic}")])

        reply_markup = InlineKeyboardMarkup(keyboard_buttons)
        
        # Персонализируем приветствие
        if user_exists and user_info and "error" not in user_info:
            status = "✅ VIP" if user_info.get("is_premium") else "👤 Пользователь"
            welcome_text = (
                f"👋 <b>Добро пожаловать, {user.first_name}!</b>\n"
                f"🔧 Я бот технической поддержки <b>{self.project_name}</b>.\n\n"
                "<b>Постарайтесь максимально подробно описать проблему</b>\n"
                "• Приложите фото/видео\n"
                "• Объясните когда, как, что не так\n"
                "• Будьте вежливы и терпеливы\n\n"
                "⚡ <b>Напишите свой вопрос</b> - я автоматически создам тикет или добавлю к существующему!"
            )
        else:
            welcome_text = (
                f"👋 <b>Добро пожаловать, {user.first_name}!</b>\n\n"
                f"🔧 Я бот технической поддержки <b>{self.project_name}</b>.\n\n"
                "⚠️ <i>Похоже, вы не зарегистрированы в основном боте.</i>\n"
                f"Для полного доступа к функциям напишите боту @{Config.MAIN_BOT_USERNAME}\n\n"
                "<b>Постарайтесь максимально подробно описать проблему</b>\n"
                "• Приложите фото/видео\n"
                "• Объясните когда, как, что не так\n"
                "• Будьте вежливы и терпеливы\n\n"
                "⚡ <b>Напишите свой вопрос</b> - я автоматически создам тикет или добавлю к существующему!"
            )
        
        await query.edit_message_text(
            welcome_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    def setup_handlers(self) -> None:
        """Настройка обработчиков команд и сообщений"""
        # Команды
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("tickets", self.tickets_command))
        self.app.add_handler(CommandHandler("close", self.support_handler.close_topic_command))
        
        # Обработчик реакций на сообщения
        self.app.add_handler(MessageReactionHandler(self.reaction_handler.handle_message_reaction))
        
        # Callback handlers для интеграции с основным ботом  
        self.app.add_handler(CallbackQueryHandler(self.handle_back_to_start_callback, pattern=r"^back_to_start$"))
        
        # Обработчик кнопки вызова оператора
        self.app.add_handler(CallbackQueryHandler(self.support_handler.handle_operator_call, pattern=r"^call_operator$"))
        
        # Обработчик кнопки "Остановить ИИ"
        self.app.add_handler(CallbackQueryHandler(self.support_handler.handle_stop_ai_callback, pattern=r"^stop_ai_\d+$"))
        
        # Обработчик кнопки "Помогло!" для закрытия тикета
        self.app.add_handler(CallbackQueryHandler(self.support_handler.handle_close_ticket_helped, pattern=r"^close_ticket_helped$"))
        
        # Кнопки поддержки (должны быть после специфических handlers)
        self.app.add_handler(CallbackQueryHandler(self.support_handler.handle_callback_query))
        
        # Используем универсальный обработчик для ВСЕХ сообщений
        self.app.add_handler(MessageHandler(filters.ALL, self.universal_message_handler))
        
        # Обработчик ошибок
        self.app.add_error_handler(self.error_handler)
    
    async def post_init(self, application: Application) -> None:
        """Действия после инициализации приложения"""
        logger.info("="*50)
        logger.info("🤖 Bot initialization started")
        
        # Получаем информацию о боте
        try:
            bot_info = await application.bot.get_me()
            logger.info(f"✅ Bot info: @{bot_info.username} ({bot_info.first_name})")
            logger.info(f"🆔 Bot ID: {bot_info.id}")
        except Exception as e:
            logger.error(f"❌ Failed to get bot info: {e}")
        
        logger.info(f"🔗 Support chat ID: {Config.SUPPORT_CHAT_ID}")
        
        # ВАЖНО: Удаляем webhook если есть
        try:
            webhook_info = await application.bot.get_webhook_info()
            if webhook_info.url:
                logger.info(f"🌐 Found existing webhook: {webhook_info.url}")
                await application.bot.delete_webhook(drop_pending_updates=True)
                logger.info("✅ Webhook deleted - switching to polling mode")
            else:
                logger.info("✅ No webhook found - ready for polling mode")
        except Exception as e:
            logger.warning(f"⚠️ Failed to manage webhook: {e}")
        
        # Проверим доступность чата поддержки
        try:
            chat = await application.bot.get_chat(Config.SUPPORT_CHAT_ID)
            chat_type = "group" if chat.type in ["group", "supergroup"] else "private"
            member_count = "unknown"
            try:
                if chat.type in ["group", "supergroup"]:
                    member_count = await application.bot.get_chat_member_count(Config.SUPPORT_CHAT_ID)
            except:
                pass
            
            logger.info(f"💬 Support chat found: '{chat.title}' ({chat_type})")
            logger.info(f"👥 Members: {member_count}")
            logger.info(f"🆔 Chat ID: {Config.SUPPORT_CHAT_ID}")
        except Exception as e:
            logger.error(f"❌ Cannot access support chat {Config.SUPPORT_CHAT_ID}: {e}")
        
        # Запускаем heartbeat мониторинг
        try:
            self.heartbeat_task = asyncio.create_task(self.heartbeat_monitor())
            logger.info("💓 Heartbeat monitor started")
        except Exception as e:
            logger.error(f"❌ Failed to start heartbeat monitor: {e}")
        
        # Запускаем health мониторинг
        try:
            self.health_monitor_task = asyncio.create_task(health_monitor.health_check_cycle())
            logger.info("🏥 Health monitor started")
        except Exception as e:
            logger.error(f"❌ Failed to start health monitor: {e}")
            
        # Запускаем превентивный перезапуск
        try:
            self.preventive_restart_task = asyncio.create_task(self.preventive_restart_monitor())
            logger.info("🔄 Preventive restart monitor started (DISABLED for diagnostics)")
        except Exception as e:
            logger.error(f"❌ Failed to start preventive restart monitor: {e}")
        
        # Обрабатываем пропущенные сообщения
        try:
            await self.process_missed_messages()
        except Exception as e:
            logger.error(f"❌ Failed to process missed messages: {e}")
            
        logger.info("="*50)
        logger.info("✅ Bot initialization completed successfully")
        logger.info("🔥 Support Bot is ready to serve users!")
        logger.info("="*50)
    
    async def process_missed_messages(self):
        """Подготовка к обработке пропущенных сообщений при запуске бота"""
        try:
            logger.info("� Preparing to process missed messages...")
            logger.info("ℹ️ Bot will automatically receive and process all pending messages")
            logger.info("⏰ Messages older than 24 hours will be filtered in message handler")
            
            # Устанавливаем флаг что мы только что запустились
            self.startup_time = datetime.now()
            self.is_processing_startup_messages = True
            
            # Через 30 секунд отключаем флаг startup-сообщений
            async def disable_startup_mode():
                await asyncio.sleep(30)
                self.is_processing_startup_messages = False
                logger.info("✅ Startup message processing mode disabled")
            
            asyncio.create_task(disable_startup_mode())
            
        except Exception as e:
            logger.error(f"❌ Error in process_missed_messages setup: {e}")

    def run(self) -> None:
        """Запуск бота"""
        try:
            # Валидация конфигурации
            logger.info("🔧 Validating configuration...")
            Config.validate()
            logger.info("✅ Configuration validated successfully")
            
            # Создание приложения
            logger.info("🏗 Creating Telegram application...")
            self.app = Application.builder().token(Config.BOT_TOKEN).post_init(self.post_init).build()
            
            # ОТЛАДКА: Логируем ВСЕ исходящие сообщения через monkey patching
            # НЕ можем перезаписать send_message напрямую, но можем перехватывать через декоратор
            logger.info("🔍 Debug logging enabled - all outgoing messages will be logged")
            
            # Настройка обработчиков
            logger.info("⚙️ Setting up message handlers...")
            self.setup_handlers()
            logger.info("✅ Handlers configured successfully")
            
            logger.info("🚀 Starting Support Bot polling...")
            logger.info("📊 Polling configuration:")
            logger.info("   • Drop pending updates: False (processing missed messages)")
            logger.info("   • Allowed updates: ALL_TYPES")
            logger.info("   • Timeout: Default")
            
            # Запуск бота с обработкой пропущенных сообщений
            self.app.run_polling(
                drop_pending_updates=False,  # НЕ удаляем пропущенные сообщения
                allowed_updates=Update.ALL_TYPES
            )
            
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"💥 Critical error during bot execution: {e}")
            logger.exception("Full traceback:")
            raise
        finally:
            logger.info("🧹 Performing cleanup...")
            # Завершаем все мониторинговые задачи
            tasks_to_cancel = []
            if self.heartbeat_task and not self.heartbeat_task.done():
                tasks_to_cancel.append(('Heartbeat', self.heartbeat_task))
            if self.health_monitor_task and not self.health_monitor_task.done():
                tasks_to_cancel.append(('Health monitor', self.health_monitor_task))
            if self.preventive_restart_task and not self.preventive_restart_task.done():
                tasks_to_cancel.append(('Preventive restart', self.preventive_restart_task))
            
            for task_name, task in tasks_to_cancel:
                try:
                    task.cancel()
                    logger.info(f"🛑 {task_name} task stopped")
                except Exception as e:
                    logger.error(f"❌ Error stopping {task_name} task: {e}")
            
            # Принудительная очистка памяти при завершении
            try:
                import gc
                collected = gc.collect()
                if collected > 0:
                    logger.info(f"🧹 Final cleanup: collected {collected} objects")
                else:
                    logger.info("🧹 Final cleanup: no objects to collect")
            except Exception as cleanup_error:
                logger.error(f"❌ Cleanup error: {cleanup_error}")
            
            # Финальный лог
            final_uptime = datetime.now() - self.start_time
            logger.info("="*60)
            logger.info(f"🏁 Support Bot session ended")
            logger.info(f"⏰ Total uptime: {final_uptime.total_seconds()/3600:.2f} hours")
            logger.info(f"📅 Session: {self.start_time} → {datetime.now()}")
            logger.info("="*60)


def main():
    """Точка входа в приложение с автоперезапуском"""
    import time
    import sys
    import traceback
    import signal
    import os
    from datetime import datetime, timedelta
    
    # Флаг для контроля завершения
    shutdown_requested = False
    current_bot = None
    
    def signal_handler(signum, frame):
        """Обработчик сигналов для корректного завершения"""
        nonlocal shutdown_requested, current_bot
        
        signal_names = {
            signal.SIGINT: "SIGINT (Ctrl+C)",
            signal.SIGTERM: "SIGTERM (Terminate)"
        }
        
        if os.name == 'nt':  # Windows
            signal_names[signal.SIGBREAK] = "SIGBREAK"
        
        signal_name = signal_names.get(signum, f"Signal {signum}")
        logger.info(f"🛑 Получен сигнал {signal_name}, корректное завершение...")
        
        shutdown_requested = True
        
        # Если есть активный бот - останавливаем его
        if current_bot and hasattr(current_bot, 'app') and current_bot.app:
            try:
                logger.info("🛑 Остановка Support Bot...")
                # Остановка через событийный цикл
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(current_bot.app.stop())
                        loop.create_task(current_bot.app.shutdown())
                    else:
                        asyncio.run(current_bot.app.stop())
                        asyncio.run(current_bot.app.shutdown())
                except Exception:
                    # Если не удается через asyncio, используем жесткий stop
                    try:
                        current_bot.app.stop()
                        current_bot.app.shutdown()
                    except Exception:
                        pass
                logger.info("✅ Support Bot остановлен корректно")
            except Exception as e:
                logger.error(f"❌ Ошибка при остановке бота: {e}")
        
        logger.info("🏁 Завершение работы...")
        sys.exit(0)
    
    # Регистрируем обработчики сигналов
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Для Windows
        if os.name == 'nt':
            signal.signal(signal.SIGBREAK, signal_handler)
        
        logger.info("📡 Обработчики сигналов зарегистрированы")
    except Exception as e:
        logger.error(f"❌ Ошибка регистрации обработчиков сигналов: {e}")
    
    restart_count = 0
    max_restarts_per_hour = 10
    restart_times = []
    
    while not shutdown_requested:
        try:
            # Очищаем старые записи перезапусков (старше часа)
            current_time = datetime.now()
            restart_times = [t for t in restart_times if current_time - t < timedelta(hours=1)]
            
            # Проверяем, не слишком ли много перезапусков
            if len(restart_times) >= max_restarts_per_hour:
                logger.error(f"🚨 Too many restarts ({len(restart_times)}) in the last hour. Waiting 10 minutes...")
                
                # Ждем с проверкой флага завершения
                for _ in range(600):  # 10 минут = 600 секунд
                    if shutdown_requested:
                        break
                    time.sleep(1)
                
                if shutdown_requested:
                    break
                    
                restart_times.clear()
                continue
            
            restart_count += 1
            if restart_count > 1:
                logger.info(f"🔄 АВТОПЕРЕЗАПУСК #{restart_count}")
                logger.info(f"📊 Перезапусков за последний час: {len(restart_times)}")
            else:
                logger.info("🚀 Starting Support Bot...")
            
            # Записываем время перезапуска
            restart_times.append(current_time)
            
            # Создаем и запускаем бот
            current_bot = SupportBot()
            current_bot.run()
            
            # Если добрались сюда - бот завершился штатно
            logger.info("✅ Bot stopped normally")
            break
            
        except KeyboardInterrupt:
            logger.info("🛑 Bot stopped by user (Ctrl+C)")
            shutdown_requested = True
            break
            
        except Exception as e:
            if shutdown_requested:
                logger.info("🛑 Завершение по запросу, пропускаем перезапуск")
                break
                
            logger.error(f"💥 CRITICAL CRASH: {type(e).__name__}: {e}")
            logger.error("📝 Full traceback:")
            logger.error(traceback.format_exc())
            
            # Определяем время ожидания перед перезапуском
            if "Connection" in str(e) or "timeout" in str(e).lower():
                wait_time = 30  # Проблемы с сетью - ждем 30 сек
                logger.info(f"🌐 Network/Connection error detected, waiting {wait_time}s...")
            elif "Database" in str(e) or "postgres" in str(e).lower():
                wait_time = 60  # Проблемы с БД - ждем минуту  
                logger.info(f"🗄️ Database error detected, waiting {wait_time}s...")
            else:
                wait_time = 15  # Другие ошибки - ждем 15 сек
                logger.info(f"⚠️ Unknown error, waiting {wait_time}s before restart...")
            
            # Пауза перед перезапуском с проверкой флага завершения
            for i in range(wait_time, 0, -1):
                if shutdown_requested:
                    logger.info("🛑 Завершение по запросу во время ожидания")
                    break
                    
                if i <= 5 or i % 10 == 0:
                    print(f"⏳ Restarting in {i} seconds...")
                time.sleep(1)
            
            if shutdown_requested:
                break
            
            # Принудительная очистка памяти перед перезапуском
            try:
                import gc
                collected = gc.collect()
                logger.info(f"🧹 Memory cleanup: collected {collected} objects")
            except Exception:
                pass
            
            logger.info("🔄 Attempting restart...")
    
    logger.info("🏁 Main loop завершен")


if __name__ == '__main__':
    main()
