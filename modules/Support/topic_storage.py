#!/usr/bin/env python3
"""
ЭКСТРЕННОЕ ИСПРАВЛЕНИЕ topic_storage.py
Убираем threading.Lock который вызывает deadlock
"""

import json
import os
from typing import Dict, Optional
import logging
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

class TopicStorage:
    """Хранилище маппингов пользователь-топик БЕЗ threading.Lock"""
    
    def __init__(self, storage_file: str = "user_topics.json"):
        self.storage_file = storage_file
        
        # Основные маппинги
        self.user_topics: Dict[int, int] = {}  # user_id -> topic_id
        self.topic_users: Dict[int, int] = {}  # topic_id -> user_id
        self.ticket_numbers: Dict[int, int] = {}  # topic_id -> ticket_number
        self.number_to_topic: Dict[int, int] = {}  # ticket_number -> topic_id
        self.topic_created_at: Dict[int, datetime] = {}  # topic_id -> creation_time
        self.last_ticket_number: int = 0  # Последний использованный номер тикета
        self.max_inactive_hours = 200  # Максимальное время неактивности тикета в часах
        
        # УБИРАЕМ threading.Lock - это причина deadlock!
        # self._lock = threading.Lock()  # ЭТО ВЫЗЫВАЛО КРАШИ!
        
        self.load_from_file()
    
    def load_from_file(self) -> None:
        """Загрузка данных из файла"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Конвертируем ключи обратно в int
                    self.user_topics = {int(k): v for k, v in data.get('user_topics', {}).items()}
                    self.topic_users = {int(k): v for k, v in data.get('topic_users', {}).items()}
                    self.ticket_numbers = {int(k): v for k, v in data.get('ticket_numbers', {}).items()}
                    self.number_to_topic = {int(k): v for k, v in data.get('number_to_topic', {}).items()}
                    self.last_ticket_number = data.get('last_ticket_number', 0)
                    
                    # Восстанавливаем время создания топиков
                    topic_created_raw = data.get('topic_created_at', {})
                    self.topic_created_at = {}
                    for topic_id, timestamp_str in topic_created_raw.items():
                        try:
                            self.topic_created_at[int(topic_id)] = datetime.fromisoformat(timestamp_str)
                        except Exception:
                            # Для старых записей без времени устанавливаем текущее время
                            self.topic_created_at[int(topic_id)] = datetime.now()
                    
                    logger.info(f"Loaded {len(self.user_topics)} user-topic mappings from storage, last ticket number: {self.last_ticket_number}")
        except Exception as e:
            logger.error(f"Failed to load storage from file: {e}")
            logger.info("Starting with empty storage")
    
    def save_to_file(self) -> None:
        """Сохранение данных в файл"""
        try:
            # Создаем резервную копию
            backup_file = f"{self.storage_file}.backup"
            if os.path.exists(self.storage_file):
                try:
                    os.replace(self.storage_file, backup_file)
                except Exception as e:
                    logger.warning(f"Failed to create backup: {e}")
            
            # Конвертируем время в строки для JSON
            topic_created_serializable = {}
            for topic_id, created_time in self.topic_created_at.items():
                topic_created_serializable[topic_id] = created_time.isoformat()
            
            data = {
                'user_topics': self.user_topics,
                'topic_users': self.topic_users,
                'ticket_numbers': self.ticket_numbers,
                'number_to_topic': self.number_to_topic,
                'topic_created_at': topic_created_serializable,
                'last_ticket_number': self.last_ticket_number
            }
            
            # Атомарная запись через временный файл
            temp_file = f"{self.storage_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            os.replace(temp_file, self.storage_file)
            logger.debug(f"Saved {len(self.user_topics)} mappings to storage")
            
        except Exception as e:
            logger.error(f"Failed to save storage to file: {e}")
    
    def add_topic_mapping(self, user_id: int, topic_id: int) -> int:
        """Добавить маппинг пользователя к топику и вернуть номер тикета"""
        # УБИРАЕМ with self._lock: - это причина deadlock!
        
        # Генерируем новый номер тикета
        self.last_ticket_number += 1
        ticket_number = self.last_ticket_number
        
        # Сохраняем маппинги
        self.user_topics[user_id] = topic_id
        self.topic_users[topic_id] = user_id
        self.ticket_numbers[topic_id] = ticket_number
        self.number_to_topic[ticket_number] = topic_id
        self.topic_created_at[topic_id] = datetime.now()
        
        self.save_to_file()
        logger.info(f"Added mapping: user {user_id} -> topic {topic_id} (ticket #{ticket_number})")
        
        return ticket_number
    
    def get_topic_for_user(self, user_id: int) -> Optional[int]:
        """Получить ID топика для пользователя"""
        return self.user_topics.get(user_id)
    
    def get_user_for_topic(self, topic_id: int) -> Optional[int]:
        """Получить ID пользователя для топика"""
        return self.topic_users.get(topic_id)
    
    def remove_topic_mapping(self, topic_id: int) -> bool:
        """Удалить маппинг по ID топика"""
        if topic_id not in self.topic_users:
            return False
        
        user_id = self.topic_users[topic_id]
        ticket_number = self.ticket_numbers.get(topic_id)
        
        # Удаляем все связанные записи
        del self.topic_users[topic_id]
        del self.user_topics[user_id]
        
        if ticket_number:
            del self.ticket_numbers[topic_id]
            del self.number_to_topic[ticket_number]
        
        if topic_id in self.topic_created_at:
            del self.topic_created_at[topic_id]
        
        self.save_to_file()
        logger.info(f"Removed mapping for topic {topic_id} (user {user_id})")
        
        return True
    
    def remove_user_mapping(self, user_id: int) -> bool:
        """Удалить маппинг по ID пользователя"""
        topic_id = self.user_topics.get(user_id)
        if not topic_id:
            return False
        
        return self.remove_topic_mapping(topic_id)
    
    def remove_mapping(self, user_id: int) -> bool:
        """Алиас для remove_user_mapping (для совместимости)"""
        return self.remove_user_mapping(user_id)
    
    def get_all_active_topics(self) -> Dict[int, int]:
        """Получить все активные маппинги пользователь -> топик"""
        return self.user_topics.copy()
    
    def clear_all_mappings(self) -> None:
        """Очистить все маппинги (для отладки)"""
        # УБИРАЕМ with self._lock: - это причина deadlock!
        
        self.user_topics = {}
        self.topic_users = {}
        self.ticket_numbers = {}
        self.number_to_topic = {}
        self.topic_created_at = {}
        self.last_ticket_number = 0
        self.save_to_file()
        logger.info("Cleared all topic mappings")
    
    def get_ticket_number(self, topic_id: int) -> Optional[int]:
        """Получить номер тикета для топика"""
        return self.ticket_numbers.get(topic_id)
    
    def get_topic_by_ticket_number(self, ticket_number: int) -> Optional[int]:
        """Получить ID топика по номеру тикета"""
        return self.number_to_topic.get(ticket_number)
    
    def get_topic_age(self, topic_id: int) -> Optional[timedelta]:
        """Получить возраст топика"""
        if topic_id in self.topic_created_at:
            return datetime.now() - self.topic_created_at[topic_id]
        return None
    
    def get_active_topics_count(self) -> int:
        """Получить количество активных топиков"""
        return len(self.user_topics)
    
    def get_topic_creation_time(self, topic_id: int) -> Optional[datetime]:
        """Получить время создания топика"""
        return self.topic_created_at.get(topic_id)
    
    # УБИРАЕМ весь threading код - он вызывал deadlock!
    # def _start_cleanup_thread(self):
    # def _cleanup_inactive_topics(self):
    # cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    
    def cleanup_old_topics(self):
        """Ручная очистка старых тикетов (БЕЗ threading)"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=self.max_inactive_hours)
            topics_to_remove = []
            
            # БЕЗ with self._lock: - убираем deadlock
            for topic_id, created_time in self.topic_created_at.items():
                if created_time < cutoff_time:
                    topics_to_remove.append(topic_id)
            
            for topic_id in topics_to_remove:
                self.remove_topic_mapping(topic_id)
                logger.info(f"Cleaned up old topic {topic_id}")
            
            if topics_to_remove:
                logger.info(f"Cleaned up {len(topics_to_remove)} old topics")
            
        except Exception as e:
            logger.error(f"Manual cleanup failed: {e}")
    
    def validate_and_clean(self):
        """Валидация и очистка некорректных записей"""
        try:
            # Проверяем консистентность маппингов
            inconsistent_users = []
            inconsistent_topics = []
            
            for user_id, topic_id in self.user_topics.items():
                if self.topic_users.get(topic_id) != user_id:
                    inconsistent_users.append(user_id)
            
            for topic_id, user_id in self.topic_users.items():
                if self.user_topics.get(user_id) != topic_id:
                    inconsistent_topics.append(topic_id)
            
            # Очищаем некорректные записи
            for user_id in inconsistent_users:
                del self.user_topics[user_id]
                logger.warning(f"Removed inconsistent user mapping: {user_id}")
            
            for topic_id in inconsistent_topics:
                del self.topic_users[topic_id]
                logger.warning(f"Removed inconsistent topic mapping: {topic_id}")
            
            if inconsistent_users or inconsistent_topics:
                self.save_to_file()
                logger.info(f"Cleaned up {len(inconsistent_users)} user and {len(inconsistent_topics)} topic inconsistencies")
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
    
    def get_stats(self) -> Dict:
        """Получить статистику хранилища"""
        return {
            'active_topics': len(self.user_topics),
            'total_tickets': self.last_ticket_number,
            'oldest_topic': min(self.topic_created_at.values()) if self.topic_created_at else None,
            'newest_topic': max(self.topic_created_at.values()) if self.topic_created_at else None
        }
    
    # ========== МЕТОДЫ-АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ ==========
    # Эти методы нужны для support_handler.py
    
    def add_mapping(self, user_id: int, topic_id: int) -> int:
        """Алиас для add_topic_mapping() - для совместимости с support_handler.py"""
        return self.add_topic_mapping(user_id, topic_id)
    
    def get_next_ticket_number(self) -> int:
        """Получить следующий номер тикета (для предварительного показа)"""
        return self.last_ticket_number + 1
    
    def remove_mapping(self, user_id: int) -> bool:
        """Алиас для remove_user_mapping() - для совместимости с support_handler.py"""
        return self.remove_user_mapping(user_id)
    
    def close_topic(self, topic_id: int) -> bool:
        """Закрыть топик - алиас для remove_topic_mapping() - для совместимости с support_handler.py"""
        return self.remove_topic_mapping(topic_id)
