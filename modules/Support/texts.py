"""
Тексты для модуля технической поддержки
Все тексты сообщений, используемые в Support боте
"""
import os
from typing import Dict, Any

def get_config_value(key: str, default: str = "") -> str:
    """Получить значение из .env файла модуля"""
    return os.getenv(key, default)

class SupportTexts:
    """Класс с текстами для модуля поддержки"""
    
    def __init__(self):
        # Получаем настройки из .env файла модуля
        self.service_name = get_config_value('SUPPORT_SERVICE_NAME', '')
        self.bot_username = get_config_value('SUPPORT_BOT_USERNAME', '')
        self.news_channel = get_config_value('SUPPORT_NEWS_CHANNEL', '')
        self.vpn_protocol = get_config_value('SUPPORT_VPN_PROTOCOL', 'VLESS')
        self.app_name_ios = get_config_value('SUPPORT_APP_NAME_IOS', 'Happ')
        self.app_name_android = get_config_value('SUPPORT_APP_NAME_ANDROID', 'Happ')
        self.project_name = get_config_value('PROJECT_NAME', 'Solobot')
    
    # === ПРИВЕТСТВИЕ И ОСНОВНЫЕ СООБЩЕНИЯ ===
    
    def welcome_message(self, first_name: str) -> str:
        """Приветственное сообщение"""
        return (
            f"👋 <b>Добро пожаловать, {first_name}!</b>\n\n"
            f"🔧 Я бот технической поддержки <b>{self.project_name}</b>.\n\n"
            "Постарайтесь максимально подробно описать проблему\n"
            "• Приложите фото/видео\n"
            "• Объясните когда, как, что не так\n"
            "• Будьте вежливы и терпеливы\n\n"
            "⚡️ Напишите свой вопрос - я автоматически создам тикет или добавлю к существующему!"
        )
    
    def help_message(self) -> str:
        """Сообщение помощи"""
        return (
            "❓ <b>Помощь по использованию бота</b>\n\n"
            "🔧 <b>Основные функции:</b>\n"
            "• Создание тикетов поддержки\n"
            "• Просмотр истории обращений\n"
            "• Получение информации о вашем аккаунте\n\n"
            "💬 <b>Как писать в поддержку:</b>\n"
            "1. Просто отправьте сообщение с описанием проблемы\n"
            "2. Бот автоматически создаст тикет\n"
            "3. Все последующие сообщения будут добавлены в тот же тикет\n\n"
            "<b>⚡️ Команды:</b>\n"
            "/start - главное меню\n"
            "/help - эта справка\n"
            "/tickets - ваши тикеты\n\n"
            "🆘 Если что-то не работает, попробуйте /start"
        )
    
    def write_support_message(self) -> str:
        """Сообщение для написания в поддержку"""
        return (
            "💬 <b>Написать в поддержку</b>\n\n"
            "⚠️ <b>Перед тем как писать, обязательно посмотрите раздел «Частые вопросы (FAQ)».</b>\n"
            "В нём уже есть решения большинства проблем. Это поможет вам решить вопрос быстрее.\n\n"
            "Если ответа там нет — опишите проблему максимально подробно:\n"
            "• На каком устройстве возникла проблема\n"
            "• Что именно не работает\n"
            "• Когда началась проблема\n"
            "• Приложите скриншоты, если возможно\n\n"
            "✍️ <i>Теперь напишите ваше сообщение:</i>"
        )

    # === FAQ ===

    def faq_menu_message(self) -> str:
        """Главное сообщение FAQ"""
        return (
            "❓ <b>Часто задаваемые вопросы</b>\n\n"
            "Выберите интересующий раздел. Если не нашли ответ — напишите нам в поддержку."
        )

    def faq_router_intro(self) -> str:
        """Сообщение с подсказками по роутеру"""
        return (
            "📡 <b>Подсказки по роутеру</b>\n\n"
            "Выберите проблему, чтобы увидеть инструкцию по её решению."
        )

    def faq_router_youtube(self) -> str:
        """Инструкция при проблемах с YouTube"""
        return (
            "🧩 <b>YouTube не работает</b>\n\n"
            "1. Проверьте, что интернет работает на основном роутере.\n"
            "2. Подключитесь к Wi-Fi <b>VlessWB_*</b>.\n"
            "3. Перейдите по адресу <a href=\"http://192.168.9.1\">http://192.168.9.1</a>.\n"
            "   Логин: <code>root</code>\n"
            "   Пароль: <code>Qwentyj</code>\n"
            "4. Откройте <b>Службы → Podkop → Диагностика</b>, нажмите <b>Перезапустить Podkop</b> и подождите 1 минуту.\n"
            "5. После перезапуска убедитесь, что статус <b>sing-box</b> отмечен зелёным цветом (работает корректно).\n"
            "6. Если не помогло — напишите буквы после <b>VlessWB</b> (Название Wi-Fi сети) в поддержку для проверки соединения."
        )

    def faq_router_no_internet(self) -> str:
        """Инструкция если пропал интернет"""
        return (
            "🌐 <b>Пропал интернет на роутере</b>\n\n"
            "1. Проверьте, что интернет работает на основном роутере.\n"
            "2. Подключитесь к Wi-Fi <b>VlessWB_*</b>.\n"
            "3. Перейдите по адресу <a href=\"http://192.168.9.1\">http://192.168.9.1</a>.\n"
            "   Логин: <code>root</code>\n"
            "   Пароль: <code>Qwentyj</code>\n"
            "4. Откройте <b>Службы → Podkop → Диагностика</b>, нажмите <b>Перезапустить Podkop</b> и подождите 1 минуту.\n"
            "5. После перезапуска убедитесь, что статус <b>sing-box</b> отмечен зелёным цветом (работает корректно).\n"
            "6. Если не помогло — напишите буквы после <b>VlessWB</b> (Название Wi-Fi сети) в поддержку для проверки соединения."
        )

    def faq_router_admin_panel(self) -> str:
        """Инструкция входа в админку"""
        return (
            "🔑 <b>Как зайти в админку роутера</b>\n\n"
            "1. Подключитесь к Wi‑Fi <b>VlessWB_*</b>.\n"
            "2. В браузере откройте <a href=\"http://192.168.9.1\">http://192.168.9.1</a>.\n"
            "   Логин: <code>root</code>\n"
            "   Пароль: <code>Qwentyj</code>\n"
            "3. Если страница не загружается — убедитесь, что подключены именно к VPN‑роутеру, а не к основному."
        )

    def faq_router_change_wifi_password(self) -> str:
        """Инструкция по смене пароля Wi-Fi"""
        return (
            "🔐 <b>Изменение пароля Wi‑Fi в OpenWRT LuCI</b>\n\n"
            "<b>Доступ к панели управления:</b>\n"
            "Адрес: <a href=\"http://192.168.9.1\">http://192.168.9.1</a>\n"
            "Логин: <code>root</code>\n"
            "Пароль: <code>Qwentyj</code>\n\n"
            "1. Откройте браузер и перейдите по адресу <a href=\"http://192.168.9.1\">http://192.168.9.1</a>.\n"
            "   Введите логин <code>root</code> и пароль <code>Qwentyj</code>.\n"
            "2. В верхнем меню выберите <b>Сеть → Беспроводная сеть</b>.\n"
            "   Отобразятся сети 2.4 ГГц (VlessWB) и 5 ГГц (VlessWB_5G).\n"
            "3. Для сети 2.4 ГГц нажмите <b>Изменить</b> → вкладка <b>Беспроводная защита</b>.\n"
            "   В поле <b>Ключ</b> введите новый пароль (минимум 8 символов) и нажмите <b>Сохранить</b>.\n"
            "4. Повторите шаг 3 для сети 5 ГГц.\n"
            "5. Нажмите <b>Сохранить и применить</b> внизу страницы.\n"
            "6. Переподключите устройства к сети с новым паролем."
        )

    def faq_router_change_wifi_name(self) -> str:
        """Инструкция по смене имени Wi-Fi"""
        return (
            "📝 <b>Изменение имени Wi‑Fi сети (SSID) в OpenWRT LuCI</b>\n\n"
            "<b>Доступ к панели управления:</b>\n"
            "Адрес: <a href=\"http://192.168.9.1\">http://192.168.9.1</a>\n"
            "Логин: <code>root</code>\n"
            "Пароль: <code>Qwentyj</code>\n\n"
            "1. Откройте браузер и перейдите по адресу <a href=\"http://192.168.9.1\">http://192.168.9.1</a>.\n"
            "   Введите логин <code>root</code> и пароль <code>Qwentyj</code>.\n"
            "2. В верхнем меню выберите <b>Сеть → Беспроводная сеть</b>.\n"
            "   Отобразятся сети 2.4 ГГц (VlessWB) и 5 ГГц (VlessWB_5G).\n"
            "3. Для сети 2.4 ГГц нажмите <b>Изменить</b> и в поле <b>SSID</b> укажите новое имя (например, MyWiFi_2.4).\n"
            "   Нажмите <b>Сохранить</b>.\n"
            "4. Для сети 5 ГГц повторите те же действия (например, MyWiFi_5G).\n"
            "5. Нажмите <b>Сохранить и применить</b> внизу страницы.\n"
            "6. Подключайтесь к Wi‑Fi с обновлённым именем."
        )

    def faq_subscription_intro(self) -> str:
        """Сообщение с подсказками по подписке"""
        return (
            "🧾 <b>Подсказки по подписке</b>\n\n"
            "Частые решения проблем с подключением и скоростью."
        )

    def faq_subscription_vpn_slow(self) -> str:
        """Инструкция при проблемах с VPN"""
        return (
            "🛡️ <b>Плохо работает VPN</b>\n\n"
            "1. Попробуйте сменить страну сервера в приложении.\n"
            "2. Сделайте тест скорости с включённым VPN на <a href=\"https://2ip.io/speed/\">https://2ip.io/speed/</a>.\n"
            "3. Повторите тест с выключенным VPN на <a href=\"https://2ip.io/speed/\">https://2ip.io/speed/</a>.\n"
            "4. Отправьте оба результата в поддержку для диагностики."
        )

    # === СООБЩЕНИЯ О ТИКЕТАХ ===
    
    def ticket_created_user(self, ticket_id: int) -> str:
        """Сообщение пользователю о создании тикета"""
        return (
            f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
            "💬 <i>Продолжайте писать в этот чат - все сообщения передаются в поддержку.</i>"
        )
    
    def ticket_existing_user(self, ticket_id: int) -> str:
        """Сообщение о существующем активном тикете"""
        return (
            f"💬 <i>У вас есть один активный тикет #{ticket_id}. "
            "Все новые сообщения будут добавлены к нему.</i>"
        )
    
    def ticket_closed_user(self) -> str:
        """Сообщение пользователю о закрытии тикета"""
        return (
            "✅ <b>Тикет закрыт</b>\n\n"
            "💬 <i>Если у вас есть новые вопросы, просто напишите боту!</i>"
        )
    
    def no_ticket_to_close(self) -> str:
        """Сообщение если нет тикета для закрытия"""
        return (
            "💬 <i>Напишите любое сообщение боту, чтобы создать новый тикет.</i>"
        )
    
    def continue_ticket_message(self) -> str:
        """Сообщение о продолжении общения в тикете"""
        return (
            "💬 <i>Все новые сообщения будут добавлены к активному тикету.</i>"
        )
    
    def new_ticket_prompt(self) -> str:
        """Сообщение-приглашение создать новый тикет"""
        return (
            "💬 <i>Напишите любое сообщение боту, чтобы создать новый тикет!</i>"
        )
    
    # === СООБЩЕНИЯ ДЛЯ ОПЕРАТОРОВ ===
    
    def operator_call_message(self) -> str:
        """Сообщение когда пользователь вызывает оператора"""
        return (
            "💬 <i>Пользователь будет ожидать ответа от живого оператора.</i>"
        )
    
    def ai_suffix_operator_call(self) -> str:
        """Суффикс для AI ответа с возможностью вызвать оператора или закрыть тикет"""
        return "\n\n❓ Если проблема решена - нажмите 'Помогло!'\n💬 Если нужна дополнительная помощь - нажмите 'Позвать оператора'"
    
    # === СТАТУСНЫЕ СООБЩЕНИЯ ===
    
    def bot_help_message(self) -> str:
        """Помощь по боту поддержки"""
        return (
            "🆘 <b>Помощь по боту поддержки</b>\n\n"
            "Этот бот создает тикеты и передает их в чат поддержки.\n"
            "Пользователи могут писать сюда свои вопросы, "
            "а операторы отвечать из чата поддержки."
        )
    
    # === СИСТЕМНЫЕ СООБЩЕНИЯ ===
    
    def config_validation_start(self) -> str:
        """Сообщение о начале валидации конфигурации"""
        return "🔧 Validating configuration..."
    
    def auto_restart_disabled(self) -> str:
        """Сообщение об отключении автоперезапуска"""
        return "🔧 АВТОПЕРЕЗАПУСК ОТКЛЮЧЕН ДЛЯ ДИАГНОСТИКИ"
    
    def continue_for_diagnosis(self) -> str:
        """Сообщение о продолжении работы для диагностики"""
        return "🔧 Бот продолжит работать для выявления настоящей проблемы"
    
    def support_chat_found(self, chat_title: str, chat_type: str) -> str:
        """Сообщение о найденном чате поддержки"""
        return f"💬 Support chat found: '{chat_title}' ({chat_type})"
    
    # === СООБЩЕНИЯ GIGACHAT ===
    
    def ai_remove_suffix(self, ai_response: str) -> str:
        """Удаляет стандартный суффикс из ответа ИИ"""
        # Убираем старые варианты текста
        response = ai_response.replace('❓ Если хотите позвать оператора - нажмите кнопку ниже', '')
        # Убираем новые варианты текста
        response = response.replace('❓ Если проблема решена - нажмите \'Помогло!\'\n💬 Если нужна дополнительная помощь - нажмите \'Позвать оператора\'', '')
        return response.strip()
    
    def clean_ai_response_for_admin(self, ai_response: str) -> str:
        """Очищает ответ ИИ для отображения администраторам с сохранением форматирования"""
        # Убираем стандартные суффиксы
        response = self.ai_remove_suffix(ai_response)
        
        # Исправляем неправильные HTML теги
        import re
        
        # Исправляем потенциальные ошибки в HTML тегах
        response = re.sub(r'</c>', '</b>', response)  # Заменяем </c> на </b>
        response = re.sub(r'<c>', '<b>', response)    # Заменяем <c> на <b>
        
        # Проверяем все парные теги
        def fix_html_tags(text):
            tags_to_check = [
                ('b', '<b>', '</b>'),
                ('i', '<i>', '</i>'),
                ('code', '<code>', '</code>'),
                ('blockquote', '<blockquote>', '</blockquote>')
            ]
            
            for tag_name, open_tag, close_tag in tags_to_check:
                open_count = text.count(open_tag)
                close_count = text.count(close_tag)
                
                # Если есть несоответствие, убираем эти теги
                if open_count != close_count:
                    text = re.sub(f'</?{tag_name}>', '', text)
            
            # Проверяем на явно сломанные теги
            if re.search(r'<[^>]*<[^>]*>', text) or re.search(r'</[^>]*</[^>]*>', text):
                # Убираем все HTML теги если структура сломана
                text = re.sub(r'<[^>]+>', '', text)
            
            return text
        
        response = fix_html_tags(response)
        
        # Убираем существующие символы цитат из ответа
        response = re.sub(r'^>\s*', '', response, flags=re.MULTILINE)
        
        # Проверяем что ответ не пустой после очистки
        if not response.strip():
            return "<blockquote>Ответ не может быть обработан</blockquote>"
        
        # Оборачиваем весь ответ в blockquote для правильного отображения в Telegram
        return f"<blockquote>{response.strip()}</blockquote>"
    
    # === ССЫЛКИ И КОНТАКТЫ ===
    
    def main_bot_link(self) -> str:
        """Ссылка на основной бот"""
        return self.bot_username
    
    def news_channel_link(self) -> str:
        """Ссылка на канал новостей"""
        return self.news_channel
    
    def get_service_info(self) -> Dict[str, str]:
        """Получить информацию о сервисе"""
        return {
            'service_name': self.service_name,
            'bot_username': self.bot_username,
            'news_channel': self.news_channel,
            'vpn_protocol': self.vpn_protocol,
            'app_name_ios': self.app_name_ios,
            'app_name_android': self.app_name_android,
            'project_name': self.project_name
        }
    
    # === МОДЕРАЦИЯ ===
    
    def blocked_user_message(self) -> str:
        """Сообщение для заблокированного пользователя"""
        return (
            "🚫 <b>Доступ ограничен</b>\n\n"
            "Ваш аккаунт был заблокирован администратором.\n"
            "Для решения вопроса обратитесь к администратору проекта."
        )
    
    def user_blocked_notification(self, user_id: int, username: str = None) -> str:
        """Уведомление о блокировке пользователя"""
        user_info = f"@{username}" if username else f"ID: {user_id}"
        return f"🚫 Пользователь {user_info} заблокирован"
    
    def user_unblocked_notification(self, user_id: int, username: str = None) -> str:
        """Уведомление о разблокировке пользователя"""
        user_info = f"@{username}" if username else f"ID: {user_id}"
        return f"✅ Пользователь {user_info} разблокирован"
    
    def ticket_closed_by_admin_notification(self, ticket_number: str = None) -> str:
        """Уведомление пользователю о закрытии тикета администратором"""
        ticket_info = f"#{ticket_number}" if ticket_number else ""
        return (
            f"🔒 <b>Ваш тикет {ticket_info} был закрыт</b>\n\n"
            f"Администратор закрыл ваше обращение.\n"
            f"Если у вас остались вопросы, можете создать новый тикет."
        )

# Создаем глобальный экземпляр для использования в модуле
texts = SupportTexts()
