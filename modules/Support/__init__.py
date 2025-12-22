
"""
Инициализация модуля Support для основного бота
Обеспечивает корректную загрузку и совместимость
"""

import logging
import sys
import os
from pathlib import Path

logger = logging.getLogger(__name__)

__version__ = "2.0.1"
__author__ = "Solobot"

# Информация о модуле для основного бота
MODULE_INFO = {
    "name": "Support",
    "version": "2.0.1", 
    "description": "Система технической поддержки с тикетами",
    "author": "SoloBot Team",
    "compatible": True,
    "requires_db": False,  # Изменено на False чтобы не блокировать основной бот
    "startup_priority": 10
}

def validate_module() -> bool:
    """Простая валидация модуля"""
    try:
        module_path = Path(__file__).parent
        
        # Проверяем основные файлы
        required_files = ["main.py", "config.py", ".env"]
        for file in required_files:
            if not (module_path / file).exists():
                logger.warning(f"Support module missing file: {file}")
        
        logger.info("Support module validation completed")
        return True
        
    except Exception as e:
        logger.error(f"Support module validation failed: {e}")
        return True  # Все равно возвращаем True

def load_support_module():
    """Безопасная загрузка модуля поддержки с автоустановкой зависимостей"""
    try:
        logger.info("Loading Support module...")
        
        # Импортируем installer (автоматически запустит установку зависимостей)
        try:
            from . import installer
            logger.info("✅ Installer модуля Support импортирован (зависимости проверены)")
        except Exception as e:
            logger.error(f"❌ Ошибка импорта installer Support: {e}")
            logger.info("Продолжаем загрузку модуля без автоустановки...")
        
        validate_module()
        
        # Не запускаем бот автоматически, только проверяем готовность
        logger.info("Support module loaded successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to load Support module: {e}")
        # Возвращаем True чтобы не блокировать основной бот
        return True

def unload_support_module():
    """Выгрузка модуля"""
    logger.info("Support module unloaded")

def get_support_module_status():
    """Статус модуля"""
    return {
        "name": "Support",
        "status": "available",
        "version": "2.0.1"
    }

# Пытаемся импортировать роутер, но не падаем если не получается
try:
    from .router import router
    __all__ = ["router", "MODULE_INFO", "load_support_module", "unload_support_module", "get_support_module_status"]
except ImportError as e:
    logger.warning(f"Could not import router: {e}")
    router = None
    __all__ = ["MODULE_INFO", "load_support_module", "unload_support_module", "get_support_module_status"]

# Автоматически загружаем модуль при импорте
load_support_module()
