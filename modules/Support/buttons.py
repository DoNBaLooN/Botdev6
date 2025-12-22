"""
Кнопки для модуля технической поддержки
Все кнопки и клавиатуры, используемые в Support боте
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import List, Optional

class SupportButtons:
    """Класс с кнопками для модуля поддержки"""
    
    # === НАЗВАНИЯ КНОПОК ===
    
    # Основные кнопки
    WRITE_SUPPORT = "🆘 Написать в поддержку"
    HELP_INFO = "❓ Помощь"
    FAQ = "📚 Частые вопросы"
    MY_TICKETS = "📋 Мои тикеты"
    CLOSE_TICKET = "❌ Закрыть тикет"
    CALL_OPERATOR = "👨‍💻 Позвать оператора"
    BACK_TO_MENU = "🔙 В главное меню"

    # Кнопки модерации
    BLOCK_USER = "🚫 Заблокировать"
    UNBLOCK_USER = "✅ Разблокировать"
    
    # === CALLBACK DATA ===
    
    # Основные действия
    CB_WRITE_SUPPORT = "write_support"
    CB_HELP_INFO = "help_info"
    CB_FAQ_MENU = "faq_menu"
    CB_FAQ_SUBSCRIPTION = "faq_subscription"
    CB_FAQ_ROUTER = "faq_router"
    CB_FAQ_ROUTER_YOUTUBE = "faq_router_youtube"
    CB_FAQ_ROUTER_NO_INTERNET = "faq_router_no_internet"
    CB_FAQ_ROUTER_ADMIN_PANEL = "faq_router_admin_panel"
    CB_FAQ_ROUTER_CHANGE_WIFI_PASSWORD = "faq_router_change_wifi_password"
    CB_FAQ_ROUTER_CHANGE_WIFI_NAME = "faq_router_change_wifi_name"
    CB_FAQ_SUBSCRIPTION_VPN_SLOW = "faq_subscription_vpn_slow"
    CB_MY_TICKETS = "my_tickets"
    CB_CLOSE_TICKET = "close_ticket"
    CB_CALL_OPERATOR = "call_operator"
    CB_BACK_MENU = "back_to_start"

    # Модерация
    CB_BLOCK_USER = "block_user"
    CB_UNBLOCK_USER = "unblock_user"
    
    # === ОСНОВНЫЕ КЛАВИАТУРЫ ===
    
    @classmethod
    def main_menu_keyboard(cls, user_id: int = None) -> InlineKeyboardMarkup:
        """Главное меню"""
        keyboard = [
            [InlineKeyboardButton(cls.WRITE_SUPPORT, callback_data=cls.CB_WRITE_SUPPORT)]
        ]
        
        if user_id:
            keyboard.append([InlineKeyboardButton(cls.MY_TICKETS, callback_data=f"{cls.CB_MY_TICKETS}_{user_id}")])
        else:
            keyboard.append([InlineKeyboardButton(cls.MY_TICKETS, callback_data=cls.CB_MY_TICKETS)])
            
        keyboard.append([InlineKeyboardButton(cls.HELP_INFO, callback_data=cls.CB_HELP_INFO)])

        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def help_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура для помощи"""
        keyboard = [
            [InlineKeyboardButton(cls.BACK_TO_MENU, callback_data=cls.CB_BACK_MENU)]
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def faq_main_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура с основными разделами FAQ"""
        keyboard = [
            [InlineKeyboardButton("🧾 Подписка", callback_data=cls.CB_FAQ_SUBSCRIPTION)],
            [InlineKeyboardButton("📡 Роутер", callback_data=cls.CB_FAQ_ROUTER)],
            [InlineKeyboardButton(cls.WRITE_SUPPORT, callback_data=cls.CB_WRITE_SUPPORT)],
            [InlineKeyboardButton(cls.BACK_TO_MENU, callback_data=cls.CB_BACK_MENU)],
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def faq_router_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура с подсказками по роутеру"""
        keyboard = [
            [InlineKeyboardButton("🧩 YouTube не работает", callback_data=cls.CB_FAQ_ROUTER_YOUTUBE)],
            [InlineKeyboardButton("🌐 Пропал интернет", callback_data=cls.CB_FAQ_ROUTER_NO_INTERNET)],
            [InlineKeyboardButton("🔑 Доступ в админку", callback_data=cls.CB_FAQ_ROUTER_ADMIN_PANEL)],
            [InlineKeyboardButton("🔐 Изменить пароль Wi-Fi", callback_data=cls.CB_FAQ_ROUTER_CHANGE_WIFI_PASSWORD)],
            [InlineKeyboardButton("📝 Изменить имя Wi-Fi", callback_data=cls.CB_FAQ_ROUTER_CHANGE_WIFI_NAME)],
            [InlineKeyboardButton("⬅️ Назад", callback_data=cls.CB_FAQ_MENU)],
            [InlineKeyboardButton(cls.WRITE_SUPPORT, callback_data=cls.CB_WRITE_SUPPORT)],
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def faq_subscription_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура с подсказками по подписке"""
        keyboard = [
            [InlineKeyboardButton("🛡️ Плохо работает VPN", callback_data=cls.CB_FAQ_SUBSCRIPTION_VPN_SLOW)],
            [InlineKeyboardButton("⬅️ Назад", callback_data=cls.CB_FAQ_MENU)],
            [InlineKeyboardButton(cls.WRITE_SUPPORT, callback_data=cls.CB_WRITE_SUPPORT)],
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def faq_answer_keyboard(cls, return_to: str) -> InlineKeyboardMarkup:
        """Клавиатура для экранов с ответами"""
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data=return_to)],
            [InlineKeyboardButton(cls.WRITE_SUPPORT, callback_data=cls.CB_WRITE_SUPPORT)],
        ]
        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def write_support_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура для написания в поддержку"""
        keyboard = [
            [InlineKeyboardButton(cls.FAQ, callback_data=cls.CB_FAQ_MENU)],
            [InlineKeyboardButton(cls.BACK_TO_MENU, callback_data=cls.CB_BACK_MENU)]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # === КЛАВИАТУРЫ ДЛЯ ТИКЕТОВ ===
    
    @classmethod
    def ticket_user_keyboard(cls, has_active_ticket: bool = False) -> InlineKeyboardMarkup:
        """Клавиатура для пользователя с тикетом"""
        keyboard = []
        
        if has_active_ticket:
            keyboard.append([InlineKeyboardButton(cls.CLOSE_TICKET, callback_data=cls.CB_CLOSE_TICKET)])
        
        keyboard.extend([
            [InlineKeyboardButton(cls.CALL_OPERATOR, callback_data=cls.CB_CALL_OPERATOR)],
            [InlineKeyboardButton(cls.BACK_TO_MENU, callback_data=cls.CB_BACK_MENU)]
        ])
        
        return InlineKeyboardMarkup(keyboard)
    
    @classmethod
    def call_operator_keyboard(cls) -> InlineKeyboardMarkup:
        """Клавиатура для вызова оператора"""
        keyboard = [
            [InlineKeyboardButton(cls.CALL_OPERATOR, callback_data=cls.CB_CALL_OPERATOR)]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # === КЛАВИАТУРЫ ДЛЯ ОПЕРАТОРОВ ===
    
    @classmethod
    def operator_keyboard(cls, user_id: int, topic_id: int, is_blocked: bool = False) -> InlineKeyboardMarkup:
        """Клавиатура оператора для модерации пользователя"""
        keyboard = []
        
        # Первый ряд: Статус и Закрыть тикет
        keyboard.append([
            InlineKeyboardButton("📊 Статус", callback_data=f"ticket_status_{user_id}_{topic_id}"),
            InlineKeyboardButton("🔒 Закрыть тикет", callback_data=f"close_ticket_{user_id}_{topic_id}")
        ])
        
        # Второй ряд: Кнопка блокировки/разблокировки
        if is_blocked:
            keyboard.append([InlineKeyboardButton(cls.UNBLOCK_USER, callback_data=f"{cls.CB_UNBLOCK_USER}_{user_id}")])
        else:
            keyboard.append([InlineKeyboardButton(cls.BLOCK_USER, callback_data=f"{cls.CB_BLOCK_USER}_{user_id}")])
        
        return InlineKeyboardMarkup(keyboard)
    
    # === УТИЛИТЫ ===
    
    @classmethod
    def empty_keyboard(cls) -> InlineKeyboardMarkup:
        """Пустая клавиатура"""
        return InlineKeyboardMarkup([])
    
    @classmethod
    def single_button(cls, text: str, callback_data: str) -> InlineKeyboardMarkup:
        """Одиночная кнопка"""
        keyboard = [[InlineKeyboardButton(text, callback_data=callback_data)]]
        return InlineKeyboardMarkup(keyboard)
    
    @classmethod
    def parse_callback_data(cls, callback_data: str) -> tuple:
        """Парсинг callback_data"""
        parts = callback_data.split('_')
        if len(parts) >= 2:
            return parts[0] + '_' + parts[1], parts[2:] if len(parts) > 2 else []
        return callback_data, []
    
    @classmethod
    def build_callback_data(cls, action: str, *args) -> str:
        """Создание callback_data"""
        if args:
            return f"{action}_{'_'.join(map(str, args))}"
        return action

# Создаем глобальный экземпляр для использования в модуле  
buttons = SupportButtons()
