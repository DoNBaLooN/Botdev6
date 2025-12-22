import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

class Config:
    """Конфигурация бота"""
    
    # Название проекта (берется из основного .env или по умолчанию)
    PROJECT_NAME = os.getenv('PROJECT_NAME', 'VPN BOT')
    
    # Username основного бота (без @)
    MAIN_BOT_USERNAME = os.getenv('MAIN_BOT_USERNAME', '')
    
    # Telegram Bot настройки
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    SUPPORT_CHAT_ID = int(os.getenv('SUPPORT_CHAT_ID', 0))
    ADMIN_IDS = [int(x.strip()) for x in os.getenv('ADMIN_IDS', '123456789').split(',') if x.strip()]  # Список ID администраторов
    
    # GigaChat настройки
    GIGACHAT_TOKEN = os.getenv('GIGACHAT_TOKEN')
    GIGACHAT_ENABLED = os.getenv('GIGACHAT_ENABLED', 'True').lower() == 'true'
    
    # Дополнительные настройки
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate(cls):
        """Валидация конфигурации"""
        required_fields = [
            ('BOT_TOKEN', cls.BOT_TOKEN),
            ('SUPPORT_CHAT_ID', cls.SUPPORT_CHAT_ID),
        ]
        
        missing = []
        for field_name, value in required_fields:
            if not value or (isinstance(value, int) and value == 0):
                missing.append(field_name)
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")
        
        return True
