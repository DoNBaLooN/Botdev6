"""
Модуль для управления заблокированными пользователями
"""

import json
import os
from typing import Set
from pathlib import Path

class BlockedUsers:
    """Класс для управления заблокированными пользователями"""
    
    def __init__(self):
        # Путь к файлу с заблокированными пользователями
        self.module_dir = Path(__file__).parent
        self.blocked_file = self.module_dir / "blocked_users.json"
        self._blocked_users: Set[int] = set()
        self._load_blocked_users()
    
    def _load_blocked_users(self):
        """Загрузить список заблокированных пользователей"""
        try:
            if self.blocked_file.exists():
                with open(self.blocked_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._blocked_users = set(data.get('blocked_users', []))
        except Exception as e:
            print(f"Ошибка при загрузке заблокированных пользователей: {e}")
            self._blocked_users = set()
    
    def _save_blocked_users(self):
        """Сохранить список заблокированных пользователей"""
        try:
            data = {
                'blocked_users': list(self._blocked_users)
            }
            with open(self.blocked_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка при сохранении заблокированных пользователей: {e}")
    
    def block_user(self, user_id: int) -> bool:
        """
        Заблокировать пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            bool: True если пользователь был заблокирован, False если уже был заблокирован
        """
        if user_id not in self._blocked_users:
            self._blocked_users.add(user_id)
            self._save_blocked_users()
            return True
        return False
    
    def unblock_user(self, user_id: int) -> bool:
        """
        Разблокировать пользователя
        
        Args:
            user_id: ID пользователя
            
        Returns:
            bool: True если пользователь был разблокирован, False если не был заблокирован
        """
        if user_id in self._blocked_users:
            self._blocked_users.remove(user_id)
            self._save_blocked_users()
            return True
        return False
    
    def is_blocked(self, user_id: int) -> bool:
        """
        Проверить, заблокирован ли пользователь
        
        Args:
            user_id: ID пользователя
            
        Returns:
            bool: True если пользователь заблокирован
        """
        return user_id in self._blocked_users
    
    def get_blocked_users(self) -> Set[int]:
        """
        Получить список всех заблокированных пользователей
        
        Returns:
            Set[int]: Множество ID заблокированных пользователей
        """
        return self._blocked_users.copy()
    
    def get_blocked_count(self) -> int:
        """
        Получить количество заблокированных пользователей
        
        Returns:
            int: Количество заблокированных пользователей
        """
        return len(self._blocked_users)

# Создаем глобальный экземпляр для использования в модуле
blocked_users = BlockedUsers()
