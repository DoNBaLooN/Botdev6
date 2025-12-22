import json
import os
from typing import Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TicketStateManager:
    """Управление состояниями тикетов"""
    
    def __init__(self, file_path: str = "ticket_states.json"):
        self.file_path = file_path
        self.states = self._load_states()
        
    def _load_states(self) -> Dict:
        """Загружает состояния тикетов из файла"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка при загрузке состояний тикетов: {e}")
        return {}
    
    def _save_states(self):
        """Сохраняет состояния тикетов в файл"""
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении состояний тикетов: {e}")
    
    def set_ai_mode(self, user_id: int):
        """Устанавливает режим ИИ для пользователя"""
        user_key = str(user_id)
        if user_key not in self.states:
            self.states[user_key] = {}
        
        self.states[user_key].update({
            'mode': 'ai',
            'last_update': datetime.now().isoformat(),
            'operator_called': False
        })
        self._save_states()
        logger.info(f"Установлен режим ИИ для пользователя {user_id}")
    
    def set_operator_mode(self, user_id: int):
        """Устанавливает режим оператора для пользователя"""
        user_key = str(user_id)
        if user_key not in self.states:
            self.states[user_key] = {}
        
        self.states[user_key].update({
            'mode': 'operator',
            'last_update': datetime.now().isoformat(),
            'operator_called': True
        })
        self._save_states()
        logger.info(f"Установлен режим оператора для пользователя {user_id}")
    
    def is_ai_mode(self, user_id: int) -> bool:
        """Проверяет, находится ли пользователь в режиме ИИ"""
        user_key = str(user_id)
        if user_key in self.states:
            current_mode = self.states[user_key].get('mode', 'ai')
            logger.debug(f"Проверка режима для пользователя {user_id}: {current_mode}")
            return current_mode == 'ai'
        
        # По умолчанию новые пользователи начинают с ИИ
        logger.debug(f"Новый пользователь {user_id}, устанавливаем режим ИИ")
        self.set_ai_mode(user_id)
        return True
    
    def is_operator_mode(self, user_id: int) -> bool:
        """Проверяет, находится ли пользователь в режиме оператора"""
        user_key = str(user_id)
        return user_key in self.states and self.states[user_key].get('mode') == 'operator'
    
    def mark_operator_called(self, user_id: int):
        """Отмечает, что оператор был вызван"""
        user_key = str(user_id)
        if user_key not in self.states:
            self.states[user_key] = {}
        
        self.states[user_key]['operator_called'] = True
        self.states[user_key]['last_update'] = datetime.now().isoformat()
        self._save_states()
        logger.info(f"Отмечен вызов оператора для пользователя {user_id}")
    
    def reset_user_state(self, user_id: int):
        """Сбрасывает состояние пользователя (используется при закрытии тикета)"""
        user_key = str(user_id)
        if user_key in self.states:
            del self.states[user_key]
            self._save_states()
            logger.info(f"Сброшено состояние для пользователя {user_id}")
    
    def get_user_state(self, user_id: int) -> Dict:
        """Получает полное состояние пользователя"""
        user_key = str(user_id)
        return self.states.get(user_key, {})
    
    def cleanup_old_states(self, days: int = 7):
        """Очищает старые состояния (старше указанного количества дней)"""
        from datetime import timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days)
        users_to_remove = []
        
        for user_id, state in self.states.items():
            try:
                last_update = datetime.fromisoformat(state.get('last_update', ''))
                if last_update < cutoff_date:
                    users_to_remove.append(user_id)
            except Exception:
                # Если дата не парсится, удаляем запись
                users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            del self.states[user_id]
        
        if users_to_remove:
            self._save_states()
            logger.info(f"Очищено {len(users_to_remove)} старых состояний пользователей")
