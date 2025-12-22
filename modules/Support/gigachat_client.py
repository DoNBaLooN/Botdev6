import aiohttp
import asyncio
import json
import os
import sys
import uuid
import re
import ssl
import logging
from typing import Optional, Dict, Any
from datetime import datetime

# Попытка импорта certifi для SSL
try:
    import certifi
    SSL_AVAILABLE = True
except ImportError:
    SSL_AVAILABLE = False
    logging.warning("certifi не установлен, используем базовые SSL настройки")

# Попытка импорта config
try:
    import config
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("config.py не найден, используем переменные окружения")
    
    class DummyConfig:
        pass
    config = DummyConfig()

from instructions import get_instruction

logger = logging.getLogger(__name__)

class GigaChatClient:
    """Клиент для работы с GigaChat API с поддержкой тегов инструкций"""
    
    def __init__(self):
        self.token = getattr(config, 'GIGACHAT_TOKEN', '') or os.getenv('GIGACHAT_TOKEN')
        if not self.token:
            logger.error("GIGACHAT_TOKEN не найден в config.py или переменных окружения")
            logger.info("Добавьте токен в config.py: GIGACHAT_TOKEN = 'ваш_токен'")
            
        self.base_url = "https://gigachat.devices.sberbank.ru/api/v1"
        self.access_token = None
        self.session = None
        self._session_created = False  # Флаг для ленивой инициализации
        
        # Счетчик сообщений для каждого пользователя
        self.user_message_count = {}
        
        # Количество сообщений после которого показывать кнопку оператора  
        self.operator_button_after = int(os.getenv('OPERATOR_BUTTON_AFTER_MESSAGE', '3'))
        
    async def _ensure_session(self):
        """Обеспечивает создание HTTP сессии"""
        if not self._session_created:
            # Настройка SSL с более мягкой проверкой для GigaChat API
            ssl_context = ssl.create_default_context()
            
            # Для продакшн окружения отключаем строгую проверку SSL
            # поскольку API Сбербанка может использовать самоподписанные сертификаты
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            logger.info("SSL контекст настроен с отключенной верификацией для GigaChat API")
            
            # Создание коннектора с SSL
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            # Создание сессии
            timeout = aiohttp.ClientTimeout(total=30)  # 30 секунд общий таймаут
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            self._session_created = True
            logger.info("HTTP сессия создана успешно")

    async def get_access_token(self):
        """Получение access token для API GigaChat"""
        await self._ensure_session()
        
        auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {self.token}'
        }
        
        data = 'scope=GIGACHAT_API_PERS'
        
        try:
            async with self.session.post(auth_url, headers=headers, data=data) as response:
                if response.status == 200:
                    result = await response.json()
                    self.access_token = result.get('access_token')
                    logger.info("Access token получен успешно")
                    return self.access_token
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения токена: {response.status} - {error_text}")
                    return None
        except Exception as e:
            error_msg = str(e)
            if "SSL" in error_msg or "certificate" in error_msg:
                logger.error(f"SSL ошибка при получении токена: {e}")
                logger.info("Попробуйте: 1) Обновить certifi: pip install --upgrade certifi")
                logger.info("           2) Проверить настройки прокси/VPN")
                logger.info("           3) Использовать другую сеть")
            else:
                logger.error(f"Исключение при получении токена: {e}")
            return None

    def _process_instruction_tags(self, text: str) -> str:
        """Обрабатывает теги инструкций в тексте"""
        def replace_tag(match):
            instruction_name = match.group(1)
            instruction_text = get_instruction(instruction_name)
            if instruction_text:
                return instruction_text
            else:
                # Удаляем несуществующие теги вместо их отображения
                logger.warning(f"Удален несуществующий тег: [instruction:{instruction_name}]")
                return ""
        
        return re.sub(r'\[instruction:([^\]]+)\]', replace_tag, text)

    def _validate_ai_response(self, ai_response: str, user_message: str) -> str:
        """Строго проверяет ответ ИИ и заменяет на правильный при необходимости"""
        
        # Критически плохие паттерны - заменяем на правильный ответ
        bad_patterns = [
            r'\[b\].*?\[/b\].*?1\..*?2\..*?3\.',  # Жирный текст + список пунктов
            r'[Кк]упоны можно активировать',       # Самодельная инструкция по купонам
            r'1\.\s*📲.*?[Оо]ткройте приложение', # Пункты с эмодзи  
            r'[Пп]ерейдите в раздел.*?[Кк]упоны', # Описание интерфейса
            r'[Вв]ведите код купона',              # Самодельные шаги
            r'\[b\].*?следующим образом.*?\[/b\]', # Неправильные заголовки
        ]
        
        # Если ИИ написал плохой ответ - принудительно заменяем
        for pattern in bad_patterns:
            if re.search(pattern, ai_response, re.DOTALL | re.IGNORECASE):
                logger.warning(f"ИИ создал самодельную инструкцию, принудительная замена на правильную")
                
                # Определяем правильный тег на основе сообщения пользователя
                correct_tag = self._get_correct_instruction_tag(user_message)
                if correct_tag:
                    return f"Вот что нужно сделать:\n\n{correct_tag}"
                else:
                    return "Обратитесь к оператору для получения подробной инструкции."
        
        # Критические форматирования
        critical_patterns = [
            r'\[b\]instruction:', 
            r'Инструкция:\s*\[b\]',
        ]
        
        for pattern in critical_patterns:
            if re.search(pattern, ai_response, re.IGNORECASE):
                logger.warning(f"Критически плохой формат, используем fallback")
                fallback = self._get_fallback_response(user_message)
                if fallback:
                    return f"Помогу решить проблему!\n\n{fallback}"
        
        return ai_response
    
    def _get_correct_instruction_tag(self, user_message: str) -> str:
        """Определяет правильный тег инструкции для сообщения"""
        message_lower = user_message.lower()
        
        # Проверяем специфичные действия с приоритетом
        if any(word in message_lower for word in ['купон', 'промокод', 'активировать']):
            return "[instruction:coupon]"
        elif any(word in message_lower for word in ['не работает', 'не подключается', 'нет интернета']):
            return "[instruction:refresh]"
        elif any(word in message_lower for word in ['подключить', 'подключение', 'настроить впн', 'настроить vpn']):
            return "[instruction:connect]"
        elif any(word in message_lower for word in ['баланс', 'пополнить', 'оплата']):
            return "[instruction:balance]"
        
        # Проверяем конкретные устройства/платформы с инструкциями
        elif any(word in message_lower for word in ['ios', 'iphone', 'ipad', 'айфон', 'айпад']):
            return "[instruction:ios]"
        elif 'android tv' in message_lower:
            return "[instruction:android_tv]"
        elif any(word in message_lower for word in ['windows', 'пк', 'компьютер']):
            return "[instruction:windows_linux_macos_pc]"
        
        # Проверяем другие устройства без специфичных инструкций - даем общую инструкцию подключения
        elif any(word in message_lower for word in [
            'android', 'андроид', 'телефон', 'смартфон',  # Android устройства
            'macos', 'mac', 'мак', 'макбук', 'macbook',   # macOS
            'linux', 'линукс', 'ubuntu', 'debian',        # Linux
            'steam deck', 'стим дек',                      # Steam Deck
            'oculus', 'quest', 'окулус', 'квест',         # VR устройства
            'router', 'роутер', 'маршрутизатор',           # Роутеры
            'smart tv', 'смарт тв', 'телевизор'           # Smart TV (кроме Android TV)
        ]):
            return "[instruction:connect]"
        
        # Если нет конкретного устройства/действия - возвращаем None для свободного ответа ИИ
        return None

    async def generate_response(self, user_message: str, user_id: int, conversation_history: list = None) -> str:
        """Генерация ответа от GigaChat с учетом счетчика сообщений"""
        # Увеличиваем счетчик сообщений пользователя
        self.user_message_count[user_id] = self.user_message_count.get(user_id, 0) + 1
        current_count = self.user_message_count[user_id]
        
        logger.info(f"Генерация ответа для пользователя {user_id}, сообщение #{current_count}")
        
        # Проверяем, нужно ли показать кнопку оператора
        should_show_operator = current_count >= self.operator_button_after
        if should_show_operator:
            logger.info(f"Пользователь {user_id} достиг {current_count} сообщений, кнопка оператора будет показана")

        # Если нет токена, используем fallback
        if not self.token:
            logger.warning("Токен отсутствует, используем fallback ответ")
            fallback = self._get_fallback_response(user_message)
            if fallback:
                # Обрабатываем теги инструкций даже в fallback-режиме
                fallback = self._process_instruction_tags(fallback)
                return fallback
            else:
                # Готовый ответ без тегов инструкций
                return "🤖 Сейчас у меня технические проблемы с ИИ, но я постараюсь помочь! Если у вас проблемы с подключением - попробуйте обновить подписку в приложении или опишите проблему подробнее."

        # Получаем настройки из .env файла модуля (приоритет) или config как fallback
        service_name = os.getenv('SUPPORT_SERVICE_NAME', getattr(config, 'SUPPORT_SERVICE_NAME', ''))
        bot_username = os.getenv('SUPPORT_BOT_USERNAME', getattr(config, 'SUPPORT_BOT_USERNAME', ''))
        news_channel = os.getenv('SUPPORT_NEWS_CHANNEL', getattr(config, 'SUPPORT_NEWS_CHANNEL', ''))
        vpn_protocol = os.getenv('SUPPORT_VPN_PROTOCOL', getattr(config, 'SUPPORT_VPN_PROTOCOL', 'VLESS'))
        app_name_ios = os.getenv('SUPPORT_APP_NAME_IOS', getattr(config, 'SUPPORT_APP_NAME_IOS', 'Happ'))
        app_name_android = os.getenv('SUPPORT_APP_NAME_ANDROID', getattr(config, 'SUPPORT_APP_NAME_ANDROID', 'Happ'))

        # Проверяем историю на повторяющиеся инструкции
        recent_instructions = []
        if conversation_history:
            for msg in conversation_history[-4:]:  # Последние 4 сообщения
                if msg.get('role') == 'assistant':
                    content = msg.get('content', '')
                    # Ищем теги инструкций в предыдущих ответах
                    instruction_matches = re.findall(r'\[instruction:([^\]]+)\]', content)
                    recent_instructions.extend(instruction_matches)
        
        # Добавляем информацию о повторах в промпт
        repeat_warning = ""
        if recent_instructions:
            repeat_warning = f"\n\n🔄 В последних сообщениях уже были инструкции: {', '.join(set(recent_instructions))}. Если пользователь снова жалуется на ту же проблему - НЕ повторяй инструкцию, а предложи связаться с оператором."

        # Проверяем, какая инструкция нужна для данного сообщения
        suggested_instruction = self._get_correct_instruction_tag(user_message)
        
        # МАКСИМАЛЬНО ЖЕСТКИЙ системный промпт
        system_message = f"""ТЫ ПОМОЩНИК ТЕХНИЧЕСКОЙ ПОДДЕРЖКИ сервиса {service_name}.

🎯 ТВОИ ОСНОВНЫЕ ЗАДАЧИ:
1. Отвечать на VPN-связанные вопросы с помощью тегов инструкций
2. Отвечать на ЛЮБЫЕ другие вопросы как обычный ИИ-ассистент (БЕЗ тегов!)
3. Быть полезным и дружелюбным

📋 ДОСТУПНЫЕ ТЕГИ ИНСТРУКЦИЙ (ТОЛЬКО для VPN вопросов):
• [instruction:connect] - для ЛЮБЫХ вопросов о подключении/настройке VPN на ЛЮБЫХ устройствах
• [instruction:refresh] - для проблем "не работает", "не подключается", "нет интернета"  
• [instruction:coupon] - для активации купонов/промокодов
• [instruction:balance] - для вопросов о балансе/оплате
• [instruction:ios] - ТОЛЬКО для специфичных проблем iOS (не подключение!)
• [instruction:android_tv] - для Android TV
• [instruction:windows_linux_macos_pc] - для Windows/ПК/компьютер

🔥 ЛОГИКА РАБОТЫ:
▶️ ЕСЛИ ВОПРОС ПРО VPN:
1. Если упоминается "подключить/подключение/настроить" + ЛЮБОЕ устройство = [instruction:connect]
2. Если просто устройство без слов подключения:
   - iOS/iPhone/iPad → [instruction:ios] 
   - Android TV → [instruction:android_tv]
   - Windows/ПК → [instruction:windows_linux_macos_pc]
   - Другие устройства (Android, macOS, роутер, Smart TV, Linux) → [instruction:connect]
3. Если "не работает/не подключается" = [instruction:refresh]
4. Купоны/промокоды = [instruction:coupon]
5. Баланс/оплата = [instruction:balance]

🔄 ОСОБЫЕ СЛУЧАИ:
• Если пользователь пишет "НЕ ПОМОГЛО" / "не помогло" / "ничего не изменилось":
"Понимаю, что предыдущее решение не сработало. Попробуем другой подход:

• Проверьте подписку (активна ли она и нужная ли подписка добавлена)
• Смените сервер в приложении VPN
• Перезагрузите устройство полностью  
• Временно отключите антивирус
• Проверьте интернет без VPN

Если проблема останется - обратитесь к оператору, он проведет индивидуальную диагностику."

▶️ ЕСЛИ ВОПРОС НЕ ПРО VPN:
- Отвечай как обычный ИИ-ассистент
- БЕЗ ТЕГОВ инструкций
- Будь полезным и информативным
- Примеры: погода, рецепты, общие вопросы, программирование, учеба и т.д.

➡️ ПРИМЕРЫ VPN вопросов:
"как подключить iOS" → Покажу как подключить VPN:

[instruction:connect]

"не работает VPN" → Давайте исправим проблему:

[instruction:refresh]

"купон" → Как активировать купон:

[instruction:coupon]

🚨 ОБЯЗАТЕЛЬНЫЙ ФОРМАТ ДЛЯ VPN ОТВЕТОВ:
1. Краткое пояснение (например: "Покажу как подключить VPN:", "Давайте исправим проблему:")
2. Пустая строка
3. Тег инструкции [instruction:*]
4. НИЧЕГО БОЛЬШЕ!

➡️ ПРИМЕРЫ НЕ-VPN вопросов:
"привет" → Привет! Как дела? Чем могу помочь?
"как приготовить борщ" → [детальный рецепт борща]
"что такое Python" → [объяснение про Python]

❌ НЕПРАВИЛЬНО (НЕ ДЕЛАЙ ТАК):
1) "как подключить iOS" → [instruction:connect] (БЕЗ пояснения)
2) "как подключить iOS" → Покажу как подключить VPN: [instruction:connect] (без пустой строки)
3) "как подключить iOS" → Покажу как подключить VPN:

[instruction:connect]

А еще попробуйте перезагрузить... (текст ПОСЛЕ тега)

✅ ПРАВИЛЬНО:
"как подключить iOS" → Покажу как подключить VPN:

[instruction:connect]

⚠️ ПРАВИЛА ФОРМАТИРОВАНИЯ:
• Для VPN: краткое пояснение + тег инструкции
• Для не-VPN: обычный развернутый ответ
• НЕ используй [b][/b] теги
• НЕ создавай свои инструкции с пунктами 1,2,3

🚨 КРИТИЧЕСКИ ВАЖНО:
• ОБЯЗАТЕЛЬНО пиши пояснение ПЕРЕД каждым тегом [instruction:*]
• Примеры пояснений: "Покажу как подключить VPN:", "Давайте исправим проблему:", "Вот что нужно сделать:"
• После пояснения - ПУСТАЯ СТРОКА, затем тег
• ЕСЛИ ты используешь тег [instruction:*] - НЕ ДОБАВЛЯЙ НИЧЕГО ПОСЛЕ НЕГО!
• Тег инструкции = ПОЛНЫЙ И ОКОНЧАТЕЛЬНЫЙ ответ
• НЕ дублируй информацию своими словами после тега
• НЕ объясняй дополнительно что делать после тега
• Тег заменится на готовую инструкцию автоматически
• ОБЯЗАТЕЛЬНО отвечай на фразы "не помогло", "ничего не изменилось" специальным текстом выше

💡 ГЛАВНОЕ: Будь полезным помощником для ЛЮБЫХ вопросов, не только VPN!

Если VPN проблема повторяется - предложи обратиться к оператору вместо той же инструкции.{repeat_warning}"""

        # Формируем сообщения для диалога
        messages = [{"role": "system", "content": system_message}]
        
        # Добавляем историю разговора если есть
        if conversation_history:
            for msg in conversation_history[-6:]:  # Последние 6 сообщений для контекста
                messages.append(msg)
        
        # Добавляем текущее сообщение пользователя
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.1,   # Немного увеличили для более естественных ответов на общие вопросы
            "max_tokens": 500,    # Увеличили для развернутых ответов на не-VPN вопросы
            "stream": False
        }

        await self._ensure_session()
        
        if not self.access_token:
            await self.get_access_token()
        
        if not self.access_token:
            logger.error("Не удалось получить access token")
            fallback = self._get_fallback_response(user_message)
            if fallback:
                # Обрабатываем теги инструкций даже при проблемах с ИИ
                return self._process_instruction_tags(fallback)
            else:
                return "⚠️ У меня сейчас проблемы с подключением к ИИ, но я могу помочь с базовыми вопросами!\n\n💡 Попробуйте написать:\n• «как подключить впн»\n• «обновить подписку»\n• «настроить на android tv»\n\nИли обратитесь к оператору для персональной помощи."

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }

        try:
            async with self.session.post(f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    if 'choices' in result and result['choices']:
                        ai_response = result['choices'][0]['message']['content']
                        
                        # Проверяем качество ответа ИИ
                        ai_response = self._validate_ai_response(ai_response, user_message)
                        
                        # Обрабатываем теги инструкций
                        ai_response = self._process_instruction_tags(ai_response)
                        
                        # Исправляем HTML форматирование
                        ai_response = self._validate_html_tags(ai_response)
                        
                        logger.info(f"Ответ ИИ для пользователя {user_id}: {ai_response[:100]}...")
                        return ai_response
                    else:
                        logger.error("Неожиданная структура ответа от GigaChat")
                        return self._get_fallback_response(user_message) or "Извините, получил неожиданный ответ от ИИ."
                
                elif response.status == 401:
                    logger.warning("Access token истек, получаем новый")
                    await self.get_access_token()
                    # Повторяем запрос
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    async with self.session.post(f"{self.base_url}/chat/completions", headers=headers, json=payload) as retry_response:
                        if retry_response.status == 200:
                            result = await retry_response.json()
                            if 'choices' in result and result['choices']:
                                ai_response = result['choices'][0]['message']['content']
                                ai_response = self._process_instruction_tags(ai_response)
                                ai_response = self._validate_html_tags(ai_response)
                                return ai_response
                
                # Если все попытки не удались
                error_text = await response.text()
                logger.error(f"Ошибка API GigaChat: {response.status} - {error_text}")
                fallback = self._get_fallback_response(user_message)
                return self._process_instruction_tags(fallback) if fallback else "Извините, сейчас у меня проблемы с ИИ. Попробуйте позже или обратитесь к оператору."

        except Exception as e:
            logger.error(f"Исключение при запросе к GigaChat: {e}")
            fallback = self._get_fallback_response(user_message)
            return self._process_instruction_tags(fallback) if fallback else "Произошла ошибка при обращении к ИИ. Пожалуйста, попробуйте позже."

    def _validate_html_tags(self, text: str) -> str:
        """Проверяет и исправляет HTML теги для Telegram"""
        if not text:
            return text
            
        # Список разрешённых тегов для Telegram
        allowed_tags = ['b', 'i', 'code', 'blockquote']
        
        # Удаляем неподдерживаемые теги
        text = re.sub(r'<(?!/?(?:' + '|'.join(allowed_tags) + r')\b)[^>]*>', '', text)
        
        # Исправляем markdown в HTML
        text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)  # **bold** -> <b>bold</b>
        text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)      # *italic* -> <i>italic</i>
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)   # ` -> <code>
        
        # Исправляем вложенные теги (Telegram не поддерживает)
        text = re.sub(r'<b><i>([^<]+)</i></b>', r'<b>\1</b>', text)
        text = re.sub(r'<i><b>([^<]+)</b></i>', r'<i>\1</i>', text)
        
        # Проверяем на незакрытые теги и исправляем их
        open_tags = re.findall(r'<(b|i|code|blockquote)>', text)
        close_tags = re.findall(r'</(b|i|code|blockquote)>', text)
        
        for tag in open_tags:
            if open_tags.count(tag) > close_tags.count(tag):
                text += f'</{tag}>'
        
        return text

    def _get_fallback_response(self, user_message: str) -> str:
        """Получение fallback ответа на основе ключевых слов"""
        message_lower = user_message.lower()
        
        # Подключение и настройка VPN - приоритет #1
        connect_keywords = ['подключить', 'подключение', 'как подключить', 'настроить', 'как настроить', 'настройка впн', 'подключить впн', 'настроить впн']
        if any(keyword in message_lower for keyword in connect_keywords):
            return "[instruction:connect]"
        
        # Обновление подписки - приоритет #2
        refresh_keywords = [
            'обновить', 'refresh', 'как обновить', 'обновление', 'подписку', 'подписка',
            'не работает', 'не подключается', 'не соединяется', 'ошибка подключения', 'нет интернета',
            'перестал работать', 'пропал интернет', 'не грузит', 'медленно работает',
            'обновить happ', 'переустановить', 'happ не работает', 'приложение не работает'
        ]
        if any(keyword in message_lower for keyword in refresh_keywords):
            return "[instruction:refresh]"
        
        # Настройка устройств
        if 'android tv' in message_lower:
            return "[instruction:android_tv]"
        
        if any(keyword in message_lower for keyword in ['windows', 'linux', 'macos', 'компьютер', 'пк']):
            return "[instruction:windows_linux_macos_pc]"
        
        if 'steam deck' in message_lower:
            return "[instruction:steam_deck]"
        
        if 'oculus' in message_lower or 'quest' in message_lower:
            return "[instruction:oculus_quest]"
        
        if 'happ' in message_lower or 'настройка' in message_lower:
            return "[instruction:happ]"
        
        # Вопросы про баланс и оплату
        balance_keywords = ['баланс', 'пополнить', 'оплата', 'деньги', 'счет']
        if any(keyword in message_lower for keyword in balance_keywords):
            return "[instruction:balance]"
        
        # Купоны и промокоды
        coupon_keywords = ['купон', 'промокод', 'скидка', 'активировать']
        if any(keyword in message_lower for keyword in coupon_keywords):
            return "[instruction:coupon]"
        
        # Общие фразы
        greetings = ['привет', 'здравствуй', 'добрый', 'hello', 'hi']
        if any(greeting in message_lower for greeting in greetings):
            return "Привет! Я помощник технической поддержки. Чем могу помочь?"
        
        # По умолчанию
        return None

    def reset_user_message_count(self, user_id: int):
        """Сбрасывает счетчик сообщений для пользователя"""
        if user_id in self.user_message_count:
            old_count = self.user_message_count[user_id]
            self.user_message_count[user_id] = 0
            logger.info(f"Счетчик сообщений для пользователя {user_id} сброшен с {old_count} на 0")
        else:
            logger.debug(f"Счетчик для пользователя {user_id} уже был равен 0")

def get_gigachat_client():
    """Фабричная функция для создания клиента GigaChat"""
    return GigaChatClient()
