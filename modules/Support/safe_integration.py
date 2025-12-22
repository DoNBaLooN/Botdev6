"""
Безопасная интеграция с основным ботом McQueen Connection
Использует динамический импорт без конфликтов с переподключением к БД
"""

import asyncio
import sys
import os
import importlib.util
from pathlib import Path
from typing import Optional, List, Dict
import time
import logging

logger = logging.getLogger(__name__)

class SafeMainBotIntegration:
    """Класс для безопасной интеграции с основным ботом с автоматическим переподключением"""
    
    def __init__(self):
        self.available = False
        self._database = None
        self._models = None
        self.main_bot_path = Path(__file__).parent.parent.parent
        self._last_connection_check = 0
        self._connection_check_interval = 300  # 5 минут
        self._max_retries = 3
        self._retry_delay = 5  # секунд
        self._init_integration()
    
    def _init_integration(self):
        """Инициализация интеграции через динамический импорт"""
        try:
            logger.info("[INIT] Начинаем инициализацию интеграции с основным ботом")
            
            # Путь к модулям основного бота
            db_module_path = self.main_bot_path / "database" / "db.py"
            models_module_path = self.main_bot_path / "database" / "models.py"
            config_module_path = self.main_bot_path / "config.py"
            
            logger.info(f"[INIT] Проверяем пути:")
            logger.info(f"[INIT] - db.py: {db_module_path.exists()}")
            logger.info(f"[INIT] - models.py: {models_module_path.exists()}")
            logger.info(f"[INIT] - config.py: {config_module_path.exists()}")
            
            if not db_module_path.exists() or not models_module_path.exists() or not config_module_path.exists():
                logger.error("❌ Модули основного бота не найдены")
                return
            
            # Добавляем путь основного бота в sys.path для импорта зависимостей
            original_path = sys.path.copy()
            original_cwd = os.getcwd()
            
            try:
                # Меняем рабочую директорию и путь
                os.chdir(str(self.main_bot_path))
                sys.path.insert(0, str(self.main_bot_path))
                
                # Сначала импортируем config
                spec_config = importlib.util.spec_from_file_location("config", config_module_path)
                config_module = importlib.util.module_from_spec(spec_config)
                spec_config.loader.exec_module(config_module)
                
                # Добавляем config в sys.modules для последующих импортов
                sys.modules['config'] = config_module
                
                # Теперь импортируем database.db
                spec_db = importlib.util.spec_from_file_location("database.db", db_module_path)
                db_module = importlib.util.module_from_spec(spec_db)
                spec_db.loader.exec_module(db_module)
                self._database = db_module
                
                # Динамический импорт database.models
                spec_models = importlib.util.spec_from_file_location("database.models", models_module_path)
                models_module = importlib.util.module_from_spec(spec_models)
                spec_models.loader.exec_module(models_module)
                self._models = models_module
                
                self.available = True
                logger.info("✅ Интеграция с основным ботом успешно инициализирована")
                
            finally:
                # Восстанавливаем sys.path и рабочую директорию
                sys.path = original_path
                os.chdir(original_cwd)
                # Убираем config из sys.modules чтобы не конфликтовал
                if 'config' in sys.modules:
                    del sys.modules['config']
                
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации интеграции: {e}")
            self.available = False
    
    def _check_and_reconnect(self) -> bool:
        """Проверка и переподключение к базе данных при необходимости"""
        current_time = time.time()
        
        # Проверяем не слишком ли часто
        if current_time - self._last_connection_check < self._connection_check_interval:
            return self.available
        
        self._last_connection_check = current_time
        
        try:
            if not self.available or not self._database:
                logger.warning("Database connection lost, attempting to reconnect...")
                self._init_integration()
                
            # Простая проверка соединения
            return self.available
        except Exception as e:
            logger.error(f"Database reconnection failed: {e}")
            return False
    
    async def _execute_with_retry(self, operation_func, operation_name: str, *args, **kwargs):
        """Выполнение операции с повторными попытками"""
        last_exception = None
        
        for attempt in range(self._max_retries):
            try:
                # Проверяем соединение перед выполнением
                if not self._check_and_reconnect():
                    raise Exception("Database connection not available")
                
                result = await operation_func(*args, **kwargs)
                
                # Если попытка успешна после переподключения, логируем это
                if attempt > 0:
                    logger.info(f"{operation_name} succeeded after {attempt + 1} attempts")
                
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"{operation_name} attempt {attempt + 1} failed: {e}")
                
                if attempt < self._max_retries - 1:
                    # Сбрасываем соединение для следующей попытки
                    self.available = False
                    await asyncio.sleep(self._retry_delay)
                else:
                    logger.error(f"{operation_name} failed after {self._max_retries} attempts")
        
        # Если все попытки неудачны, возвращаем ошибку
        return {"error": f"{operation_name} failed: {str(last_exception)}"}
    
    async def get_user_info(self, tg_id: int) -> dict:
        """Получение информации о пользователе с автоматическим переподключением"""
        
        async def _get_user_info():
            # Импортируем SQLAlchemy функции
            from sqlalchemy import select
            
            async with self._database.async_session_maker() as session:
                stmt = select(
                    self._models.User.tg_id,
                    self._models.User.username,
                    self._models.User.first_name,
                    self._models.User.last_name,
                    self._models.User.language_code,
                    self._models.User.balance,
                    self._models.User.trial,
                    self._models.User.created_at,
                    self._models.User.updated_at
                ).where(self._models.User.tg_id == tg_id)
                
                result = await session.execute(stmt)
                user_data = result.first()
                
                if not user_data:
                    return None  # Возвращаем None для незарегистрированных пользователей
                
                return {
                    "id": user_data.tg_id,  # используем tg_id как id
                    "tg_id": user_data.tg_id,
                    "username": user_data.username,
                    "first_name": user_data.first_name,
                    "last_name": user_data.last_name,
                    "is_premium": user_data.trial > 0,  # считаем premium если есть trial
                    "balance": float(user_data.balance or 0),
                    "created_at": user_data.created_at.isoformat() if user_data.created_at else None,
                    "updated_at": user_data.updated_at.isoformat() if user_data.updated_at else None,
                    "trial": user_data.trial,
                    "referral_code": None,  # поле отсутствует в модели
                    "language": user_data.language_code or "ru"
                }
        
        return await self._execute_with_retry(_get_user_info, "get_user_info")
    
    async def get_user_keys(self, tg_id: int) -> list:
        """Получение ключей пользователя с автоматическим переподключением"""
        
        logger.info(f"[DEBUG] Запрос ключей для пользователя {tg_id}")
        
        async def _get_user_keys():
            from sqlalchemy import select
            
            async with self._database.async_session_maker() as session:
                logger.info(f"[DEBUG] Подключение к БД успешно для пользователя {tg_id}")
                
                # Получаем ключи пользователя
                stmt = select(
                    self._models.Key.client_id,  # это primary key в модели Key
                    self._models.Key.tg_id,
                    self._models.Key.email,
                    self._models.Key.created_at,
                    self._models.Key.expiry_time,
                    self._models.Key.key,
                    self._models.Key.server_id,
                    self._models.Key.tariff_id,
                    self._models.Key.is_frozen,
                    self._models.Key.alias,
                    self._models.Key.remnawave_link
                ).where(self._models.Key.tg_id == tg_id)
                
                result = await session.execute(stmt)
                keys_data = result.fetchall()
                
                logger.info(f"[DEBUG] Найдено {len(keys_data)} ключей для пользователя {tg_id}")
                
                keys_list = []
                for key in keys_data:
                    # Конвертируем timestamp в дату если нужно
                    expiry_date = None
                    created_date = None
                    
                    if key.expiry_time:
                        from datetime import datetime
                        try:
                            # Проверяем, если timestamp в миллисекундах (больше чем разумная дата)
                            if key.expiry_time > 9999999999:  # больше чем 2001 год в секундах
                                expiry_date = datetime.fromtimestamp(key.expiry_time / 1000).isoformat()
                            else:
                                expiry_date = datetime.fromtimestamp(key.expiry_time).isoformat()
                        except (ValueError, OSError) as e:
                            logger.warning(f"Could not convert expiry_time {key.expiry_time}: {e}")
                            expiry_date = str(key.expiry_time)
                    
                    if key.created_at:
                        try:
                            if isinstance(key.created_at, int):
                                # Проверяем, если timestamp в миллисекундах
                                if key.created_at > 9999999999:
                                    created_date = datetime.fromtimestamp(key.created_at / 1000).isoformat()
                                else:
                                    created_date = datetime.fromtimestamp(key.created_at).isoformat()
                            else:
                                created_date = key.created_at.isoformat()
                        except (ValueError, OSError) as e:
                            logger.warning(f"Could not convert created_at {key.created_at}: {e}")
                            created_date = str(key.created_at)
                    
                    # Получаем информацию о сервере - server_id уже содержит название сервера
                    server_name = key.server_id  # В данной базе server_id уже содержит название
                    
                    key_info = {
                        "client_id": key.client_id,  # используем это поле для отображения
                        "key_name": key.alias or f"Key-{key.client_id[:8]}" if key.client_id else "Unknown",
                        "key_uuid": key.key,
                        "server_id": key.server_id,
                        "server_name": server_name,  # используем server_id как название сервера
                        "tariff_id": key.tariff_id,
                        "expiry_date": expiry_date,
                        "is_active": not key.is_frozen if key.is_frozen is not None else True,
                        "traffic_limit": None,  # в модели нет этого поля
                        "used_traffic": None,   # в модели нет этого поля
                        "created_at": created_date,
                        "email": key.email,
                        "remnawave_link": key.remnawave_link
                    }
                    keys_list.append(key_info)
                    logger.debug(f"[DEBUG] Ключ добавлен: {key.email or key.client_id}")
                
                logger.info(f"[DEBUG] Итого обработано ключей: {len(keys_list)}")
                return keys_list
        
        result = await self._execute_with_retry(_get_user_keys, "get_user_keys")
        
        logger.info(f"[DEBUG] Результат _execute_with_retry для пользователя {tg_id}: type={type(result)}, len={len(result) if isinstance(result, list) else 'N/A'}")
        
        # Если результат содержит ошибку, логируем её и возвращаем пустой список
        if isinstance(result, dict) and "error" in result:
            logger.error(f"Ошибка получения ключей для пользователя {tg_id}: {result['error']}")
            return []
        
        if isinstance(result, list):
            logger.info(f"[DEBUG] Возвращаем {len(result)} ключей для пользователя {tg_id}")
            return result
        
        logger.warning(f"[DEBUG] Неожиданный тип результата для пользователя {tg_id}: {type(result)}")
        return []
    
    async def check_user_exists(self, tg_id: int) -> bool:
        """Проверка существования пользователя с автоматическим переподключением"""
        
        async def _check_user_exists():
            from sqlalchemy import select, func
            
            async with self._database.async_session_maker() as session:
                stmt = select(func.count()).select_from(self._models.User).where(self._models.User.tg_id == tg_id)
                result = await session.execute(stmt)
                count = result.scalar()
                return count > 0
        
        result = await self._execute_with_retry(_check_user_exists, "check_user_exists")
        return result if isinstance(result, bool) else False
    
    async def get_user_subscription_status(self, tg_id: int) -> dict:
        """Получение статуса подписки пользователя"""
        user_info = await self.get_user_info(tg_id)
        if "error" in user_info:
            return user_info
        
        keys = await self.get_user_keys(tg_id)
        active_keys = [key for key in keys if key.get("is_active", False)]
        
        return {
            "user_id": user_info["id"],
            "tg_id": tg_id,
            "is_premium": user_info.get("is_premium", False),
            "balance": user_info.get("balance", 0),
            "total_keys": len(keys),
            "active_keys": len(active_keys),
            "keys": keys
        }

    async def check_user_exists(self, tg_id: int) -> bool:
        """Проверка существования пользователя в базе данных"""
        
        async def _check_user_exists():
            from sqlalchemy import select
            
            async with self._database.async_session_maker() as session:
                stmt = select(self._models.User.tg_id).where(self._models.User.tg_id == tg_id)
                result = await session.execute(stmt)
                user = result.first()
                return user is not None
        
        try:
            result = await self._execute_with_retry(_check_user_exists, "check_user_exists")
            
            # Если результат - это ошибка, пользователь не существует
            if isinstance(result, dict) and "error" in result:
                return False
                
            return result
        except Exception as e:
            logger.error(f"Ошибка проверки существования пользователя {tg_id}: {e}")
            return False

    def _test_connection_only(self):
        """Простая проверка подключения без миграций и без импорта database модулей"""
        try:
            import os
            from pathlib import Path
            
            print("[DEBUG] Starting simple database check...")
            
            # Проверяем структуру проекта вместо импорта модулей  
            bot_root = Path(__file__).parents[2]
            
            # Проверяем наличие ключевых файлов БД
            required_db_files = [
                bot_root / "database" / "__init__.py",
                bot_root / "database" / "db.py", 
                bot_root / "config.py"
            ]
            
            missing_files = []
            for file_path in required_db_files:
                if not file_path.exists():
                    missing_files.append(str(file_path))
            
            if missing_files:
                print(f"[WARNING] Missing database files: {missing_files}")
                return False
            
            # Проверяем переменные окружения для БД
            config_file = bot_root / "config.py"
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_content = f.read()
                    
                if 'DATABASE_URL' not in config_content:
                    print("[WARNING] DATABASE_URL not found in config")
                    return False
                    
                print("[INFO] Database configuration files are present")
                print("[INFO] Database integration check passed (structure-based)")
                return True
                
            except Exception as e:
                print(f"[ERROR] Could not read config file: {e}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Database structure check failed: {e}")
            return False

# Глобальный экземпляр интеграции
safe_main_bot = SafeMainBotIntegration()
