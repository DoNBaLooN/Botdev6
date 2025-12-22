"""
Модуль с инструкциями для техподдержки VPN-сервиса
Все инструкции вынесены в отдельные переменные для экономии токенов
"""
import os

def get_env_value(key: str, default: str = "") -> str:
    """Получить значение из .env файла"""
    return os.getenv(key, default)

# ==================================================================================
# ИНСТРУКЦИИ ПО НАСТРОЙКЕ VPN - ОТДЕЛЬНЫЕ ПЕРЕМЕННЫЕ
# ==================================================================================

def get_happ_instruction() -> str:
    """Сжатая инструкция по настройке HAPP"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    app_name = get_env_value('SUPPORT_APP_NAME', 'Happ')
    
    return f"""📱 <b>БЫСТРАЯ НАСТРОЙКА VPN ({app_name.upper()})</b>

<blockquote><b>1. Открыть бота</b>
• Перейдите в {bot_username}
• Нажмите «Мои подписки» (🔑)</blockquote>

<blockquote><b>2. Выбрать подписку</b>
• Выберите нужную подписку из списка
• Нажмите «Подключить устройство»</blockquote>

<blockquote><b>3. Выбрать Windows</b>
• В списке устройств выберите «Windows»
• Нажмите «Скачать» для загрузки приложения</blockquote>

<blockquote><b>4. Установить приложение</b>
• Запустите скачанный установщик
• Установите {app_name} на компьютер</blockquote>

<blockquote><b>5. Подключить подписку</b>
• В WebApp нажмите кнопку «Подключить»
• {app_name} автоматически добавит подписку</blockquote>

<blockquote><b>6. Запустить VPN</b>
• Выберите страну-сервер
• Нажмите большую кнопку питания для подключения</blockquote>

✅ <b>Готово! VPN работает!</b>

💡 <b>Важно:</b> Запускайте {app_name} от имени администратора для корректной работы

[IMAGES:happ:all]"""

def get_android_tv_instruction() -> str:
    """Инструкция для Android TV"""
    app_name = get_env_value('SUPPORT_APP_NAME', 'Happ')
    
    return f"""📺 <b>БЫСТРАЯ НАСТРОЙКА {app_name.upper()} НА ANDROID TV</b>

<b>Что понадобится:</b>
• Телефон с установленным приложением {app_name}
• Флешка-USB (подойдёт любая)
• Телевизор/приставка на Android TV

<b>1. Скачиваем приложение для ТВ</b>
• На телефоне или компьютере откройте ссылку: {app_name}.apk
• Скачанный файл {app_name}.apk перетащите на флешку (как обычную картинку или документ)

<b>2. Устанавливаем {app_name} на телевизор</b>
• Вставьте флешку в USB-порт ТВ
• Откройте на ТВ «Файлы» или любой другой файловый менеджер
• Найдите {app_name}.apk → нажмите Установить → ОК

<b>3. Подготовка экрана с QR-кодом</b>
• Запустите {app_name} на ТВ
• Появится большой QR-код и кнопка «Пропустить»
• НИЧЕГО НЕ НАЖИМАЙТЕ — оставьте QR-код на экране

<b>4. Передаём подписку с телефона</b>
• Откройте {app_name} на телефоне
• Внизу тапните «QR-код»
• Наведите камеру телефона на QR-код, который светится на ТВ
• На телефоне откроется список серверов
• Поставьте галочки рядом с нужными странами и нажмите «Отправить»

<b>5. Подключаемся к VPN на ТВ</b>
• На ТВ появится ваша подписка
• Выберите сервер (страну), который хотите использовать
• Нажмите большую кнопку Power — кольцо должно загореться цветом → подключение готово!

<b>Частые вопросы:</b>
• Надо ли удалять файл с флешки? — Можно, он больше не нужен
• Как выключить VPN? — Откройте {app_name} на ТВ и снова нажмите кнопку Power
• Нет файлового менеджера? — Установите "TV File Commander" из Google Play на ТВ

✅ <b>VPN на Android TV настроен!</b>

[IMAGES:android_tv:all]"""

def get_steam_deck_instruction() -> str:
    """Инструкция для Steam Deck"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    service_name = get_env_value('SUPPORT_SERVICE_NAME', 'VPN-сервис')
    app_name = get_env_value('SUPPORT_APP_NAME', 'Happ')
    
    return f"""🎮 <b>STEAM DECK: УСТАНОВКА И НАСТРОЙКА {app_name.upper()}</b>

<b>1. Переключитесь в режим рабочего стола</b>
• Нажмите кнопку Steam на Steam Deck
• Выберите Power (Питание) → Switch to Desktop (Переключиться на рабочий стол)
• Steam Deck перейдет в режим рабочего стола, как обычный ПК

<b>2. Скачайте {app_name}.AppImage</b>
• Откройте браузер (например, Firefox или Chrome)
• Перейдите по ссылке: {app_name} (GitHub Releases)
• Скачайте файл {app_name}.linux.x86.AppImage

<b>3. Сделайте файл исполняемым</b>
• Откройте файловый менеджер (Dolphin)
• Перейдите в папку загрузки
• Щёлкните правой кнопкой по {app_name}.linux.x86.AppImage → Properties (Свойства)
• На вкладке Permissions (Разрешения) поставьте галочку Is executable (Исполняемый файл)
• Нажмите OK

Или выполните в терминале:
<code>chmod +x /путь/к/{app_name}.linux.x86.AppImage</code>

<b>4. Запустите {app_name}</b>
• Дважды кликните по {app_name}.linux.x86.AppImage
• Если появится предупреждение, выберите Run (Запустить)

<b>5. (Опционально) Добавьте {app_name} в Steam</b>
• Откройте Steam в режиме рабочего стола
• Меню Games (Игры) → Add a Non-Steam Game to My Library
• Выберите Happ.linux.x86.AppImage и нажмите Add Selected Programs
• Теперь HAPP появится в вашей библиотеке Steam

<b>6. Вернитесь в игровой режим</b>
• На рабочем столе найдите значок Return to Gaming Mode
• Нажмите на него для возврата в стандартный режим Steam Deck

<b>7. Получите ссылку-подписку и подключитесь</b>
• Откройте Telegram и перейдите в {bot_username}
• Скопируйте свою ссылку-подписку (как в инструкции для Windows)
• Вставьте её в HAPP на Steam Deck (через Add Configuration → Subscription)
• Подключитесь к нужному серверу {service_name} VPN

<b>8. (Опционально) Автозапуск HAPP</b>
• Откройте System Settings → Startup and Shutdown → Autostart
• Добавьте Happ.linux.x86.AppImage в список автозагрузки

✅ <b>HAPP на Steam Deck настроен!</b>

[IMAGES:steam_deck:all]"""

def get_oculus_quest_instruction() -> str:
    """Инструкция для Oculus Quest"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    service_name = get_env_value('SUPPORT_SERVICE_NAME', 'VPN-сервис')
    
    return f"""🥽 <b>OCULUS QUEST — НАСТРОЙКА VPN-КЛИЕНТОВ HAPP ИЛИ V2RAYTUN</b>

<b>Что понадобится:</b>
На шлеме Quest:
• Meta Quest / Quest 2 / Quest 3
• Кабель USB‑C ↔ USB‑A/USB‑C
• Подписка в боте {bot_username}
• .apk‑файлы Happ и V2RayTun с сайта {service_name}

На компьютере:
• Любой ПК (Windows 10/11 или macOS/Linux)
• Подключение к Интернету
• SideQuest — скачать с GitHub

<b>1. Включаем режим разработчика (Developer Mode)</b>
• Создайте учётную запись разработчика Meta: developer.oculus.com
• Включите 2‑фа (SMS или приложение‑аутентификатор)
• Откройте мобильное приложение Meta Quest → Устройства → ваш шлем → Режим разработчика → включите
• Перезагрузите гарнитуру

БЕЗ DEVELOPER MODE УСТАНОВКА СТОРОННИХ APK НЕВОЗМОЖНА.

<b>2. Скачиваем и ставим SideQuest на ПК</b>
• Откройте релизы: SideQuest GitHub
• Скачайте дистрибутив для вашей ОС
• В Windows появится окно «Windows protected your PC». Нажмите More info → Run anyway

<b>3. Подключаем шлем к SideQuest</b>
• Соедините Quest и ПК кабелем USB‑C
• В гарнитуре подтвердите запрос USB‑debugging → ✓ «Всегда разрешать»
• В левом верхнем углу SideQuest загорится зелёный кружок — шлем определился

<b>4. Скачиваем APK Happ или V2RayTun</b>
• Скачайте Happ.apk или V2RayTun_universal.apk (актуальные APK)
• После загрузки оба файла окажутся в «Загрузках»

<b>5. Устанавливаем APK через SideQuest</b>
• Нажмите иконку «Install APK from folder» (телевизор со стрелкой)
• Выберите оба файла v2RayTun_universal.apk и Happ.apk
• Внизу появится строка Installing Apk… а после завершения — APK installed ok!!
• Проверка: откройте Installed apps в SideQuest — в списке появится «Telegram»

<b>6. Устанавливаем Telegram</b>
• Если SideQuest уже показал, что Telegram установлен, переходите к шагу 7
• Если нет — используйте QLoader

<b>7. Копируем VPN‑ссылку из бота</b>
• В шлеме откройте Telegram (Unknown Sources)
• Перейдите к {bot_username} → Меню → Мои подписки → Получить ссылку
• Нажмите на длинную строку, выберите Copy

<b>8. Импорт подписки в Happ</b>
• Запустите Happ → нажмите «+» в правом верхнем углу
• Выберите Import → From Clipboard — приложение само найдёт ссылку
• Сохраните → в списке появится ваша подписка
• При первом подключении появится запрос «Приложение Happ пытается установить VPN …» — нажмите OK

<b>9. Импорт подписки в V2RayTun (альтернатива)</b>
• Запустите V2RayTun → нажмите «+» → меню Импорт из буфера обмена
• Убедитесь, что конфигурация «{service_name}VPN …» появилась в списке
• При первом подключении подтвердите запрос VPN

<b>10. Проверяем и включаем обновления Quest</b>
• Settings → System → Software Update
• Включите тумблеры Automatic updates, Security updates и дождитесь загрузки патчей

<b>11. Подключаемся к VPN</b>
• В Happ или V2RayTun выберите страну (Германия, США, …)
• Нажмите большую кнопку питания
• В строке состояния Quest появится иконка 🔑 — это значит, VPN активен

<b>Частые вопросы:</b>
• SideQuest не видит шлем — Проверьте кабель, Developer Mode, перезапустите ПК и Quest
• APK не устанавливается — Закройте SideQuest, откройте заново, убедитесь, что вверху зелёный кружок
• Happ показывает 0 Kbit/s — Попробуйте другой сервер, обновите конфигурацию кнопкой ↻, проверьте дата/время в шлеме
• Где найти установленные программы? — В гарнитуре: Library → Unknown Sources
• Можно ли удалить ненужный клиент? — Да. SideQuest → Installed apps → Uninstall

✅ <b>VPN на Oculus Quest настроен!</b>

[IMAGES:oculus_quest:all]"""

def get_balance_instruction() -> str:
    """Инструкция по пополнению баланса"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    
    return f"""💰 <b>КАК ПРАВИЛЬНО ПОПОЛНИТЬ БАЛАНС В БОТЕ</b>

<blockquote><b>Шаг 1: Откройте бота</b>
• Перейдите в {bot_username} в Telegram</blockquote>

<blockquote><b>Шаг 2: Перейдите в личный кабинет</b>
• Нажмите на кнопку Личный кабинет в главном меню бота</blockquote>

<blockquote><b>Шаг 3: Выберите пополнение баланса</b>
• В личном кабинете выберите раздел Пополнить баланс и нажмите на него</blockquote>

<blockquote><b>Шаг 4: Выберите способ оплаты</b>
• Выберите удобный для вас способ оплаты: ЮКасса, быстрый перевод или Юмани</blockquote>

<blockquote><b>Шаг 5: Выберите сумму пополнения</b>
• Вам будет предложен шаблон суммы. Вы можете выбрать одну из предложенных сумм или ввести свою</blockquote>

<blockquote><b>Шаг 6: Подтвердите оплату</b>
• После выбора суммы нажмите кнопку Пополнить для перехода к оплате</blockquote>

🎉 <b>Поздравляем! Вы успешно пополнили баланс и теперь готовы пользоваться всеми преимуществами!</b>

[IMAGES:balance:all]"""

def get_coupon_instruction() -> str:
    """Инструкция по активации купона"""
    return """🧾 <b>КАК АКТИВИРОВАТЬ КУПОН НА VPN</b>

<blockquote><b>Шаг 1: Зайдите в личный кабинет бота</b>
• Откройте Telegram-бот и нажмите кнопку «Кабинет» или «Мои устройства»</blockquote>

<blockquote><b>Шаг 2: Перейдите в раздел «Баланс»</b>
• В меню выберите пункт «Баланс»</blockquote>

<blockquote><b>Шаг 3: Выберите «Активировать купон»</b>
• Внутри раздела «Баланс» нажмите кнопку «Активировать купон»</blockquote>

<blockquote><b>Шаг 4: Введите купон</b>
• Введите ваш промо- или активационный купон и нажмите Ввод / Enter</blockquote>

💡 <b>Альтернативные способы:</b>

<blockquote><b>Если купон был отправлен вам текстом или ссылкой:</b>
• Просто вставьте его в чат с ботом и нажмите Enter</blockquote>

<blockquote><b>Если это специальная ссылка с активацией:</b>
• Перейдите по ней, и купон будет активирован автоматически</blockquote>

✅ <b>Купон успешно активирован!</b>

[IMAGES:coupon:all]"""

def get_refresh_instruction() -> str:
    """Инструкция по обновлению подписки"""
    return """🔄 <b>КАК ОБНОВИТЬ ПОДПИСКУ</b>

<blockquote><b>В боте:</b>
• Личный кабинет → Мои подписки → выбрать подписку → кнопка "Обновить"</blockquote>

<blockquote><b>В приложении VPN:</b>
• Найдите кнопку обновления (🔄) и нажмите её
• Перезапустите приложение</blockquote>

✅ <b>Подписка обновлена!</b>

[IMAGES:refresh:all]"""

def get_macbook_instruction() -> str:
    """Сжатая инструкция по настройке HAPP для MacBook"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    
    return f"""💻 <b>БЫСТРАЯ НАСТРОЙКА VPN НА MacBook</b>

<blockquote><b>1. Открыть бота</b>
• Перейдите в {bot_username}
• Нажмите «Мои подписки» (🔑)</blockquote>

<blockquote><b>2. Выбрать подписку</b>
• Выберите нужную подписку из списка
• Нажмите «Подключить устройство»</blockquote>

<blockquote><b>3. Выбрать macOS</b>
• В списке устройств выберите «macOS»
• Нажмите «Скачать» для загрузки приложения</blockquote>

<blockquote><b>4. Подключить подписку</b>
• В WebApp нажмите кнопку «Подключить»
• HAPP автоматически добавит подписку</blockquote>

<blockquote><b>5. Запустить VPN</b>
• Выберите страну-сервер
• Нажмите большую кнопку Подключить для подключения</blockquote>

✅ <b>Готово! VPN работает!</b>

[IMAGES:happ:all]"""

def get_ios_instruction() -> str:
    """Инструкция для iPhone/iPad"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    app_name_ios = get_env_value('SUPPORT_APP_NAME_IOS', 'Happ')
    
    return f"""📱 <b>НАСТРОЙКА VPN НА iPhone/iPad</b>

<blockquote><b>Шаг 1: Скачивание приложения</b>
• Откройте App Store на вашем iPhone или iPad
• В поиске введите "{app_name_ios}" 
• Скачайте и установите приложение</blockquote>

<blockquote><b>Шаг 2: Получение ссылки-подписки</b>
• Перейдите в {bot_username}
• Нажмите "Личный кабинет" → "Мои подписки"
• Выберите вашу подписку
• Нажмите "Подключить устройство" → выберите "iPhone/iPad"
• Скопируйте длинную ссылку-подписки</blockquote>

<blockquote><b>Шаг 3: Добавление подписки в приложение</b>
• Откройте приложение {app_name_ios}
• Нажмите "+" или "Добавить подписку"
• Вставьте скопированную ссылку в поле URL
• Нажмите "Добавить" или "Сохранить"</blockquote>

<blockquote><b>Шаг 4: Подключение к VPN</b>
• В списке серверов выберите нужную страну
• Нажмите большую кнопку подключения (⚡ или Power)
• При первом подключении разрешите создание VPN-конфигурации
• Введите код разблокировки iPhone, если потребуется</blockquote>

<blockquote><b>Шаг 5: Проверка подключения</b>
• В статусной строке iPhone появится значок VPN
• Приложение покажет статус "Подключено"
• Можете проверить ваш IP-адрес в браузере</blockquote>

<b>💡 Решение проблем:</b>

<blockquote><b>Если VPN не подключается:</b>
• Настройки → Общие → Сброс → Сбросить настройки сети
• Перезагрузите iPhone/iPad
• Попробуйте другой сервер в приложении</blockquote>

<blockquote><b>Если приложение не находится:</b>
• Ищите именно "{app_name_ios}", а не название VPN-сервиса
• Проверьте регион App Store (должен быть не российский)
• Попробуйте поиск на английском: "Happ VPN"</blockquote>

✅ <b>VPN на iPhone/iPad настроен!</b>

[IMAGES:happ:all]"""

def get_connect_instruction() -> str:
    """Общая инструкция по подключению VPN"""
    bot_username = get_env_value('SUPPORT_BOT_USERNAME', '@your_bot')
    
    return f"""🔗 <b>КАК ПОДКЛЮЧИТЬ VPN</b>

<blockquote><b>1. Откройте бота</b>
• Перейдите в {bot_username}
• Нажмите кнопку «Мои подписки» 🔑</blockquote>

<blockquote><b>2. Выберите подписку</b>
• Выберите вашу активную подписку из списка
• Нажмите кнопку «Подключить устройство»</blockquote>

<blockquote><b>3. Следуйте инструкциям</b>
• Выберите ваше устройство (Windows, Android, iOS и т.д.)
• Следуйте пошаговым инструкциям</blockquote>

<blockquote><b>4. Настройте приложение</b>
• Скачайте и установите приложение для вашего устройства
• Импортируйте конфигурацию или добавьте подписку</blockquote>

<blockquote><b>5. Подключитесь к серверу</b>
• Выберите страну-сервер в приложении
• Нажмите кнопку подключения</blockquote>

✅ <b>Готово! VPN работает!</b>

💡 <b>Если возникли проблемы:</b>
• Проверьте что подписка активна и оплачена
• Убедитесь что интернет работает без VPN
• Попробуйте другой сервер
• Перезапустите приложение"""

# ==================================================================================
# СЛОВАРЬ ИНСТРУКЦИЙ ДЛЯ БЫСТРОГО ДОСТУПА
# ==================================================================================

INSTRUCTIONS = {
    'happ': get_happ_instruction,
    'android_tv': get_android_tv_instruction, 
    'steam_deck': get_steam_deck_instruction,
    'oculus_quest': get_oculus_quest_instruction,
    'balance': get_balance_instruction,
    'coupon': get_coupon_instruction,
    'refresh': get_refresh_instruction,
    'connect': get_connect_instruction,  # Новая инструкция по подключению
    'подключить': get_connect_instruction,  # Алиас на русском
    'настроить': get_connect_instruction,  # Алиас для настройки
    'ios': get_ios_instruction,
    'iphone': get_ios_instruction,  # Алиас для iOS
    'ipad': get_ios_instruction,    # Алиас для iOS
    'macbook': get_macbook_instruction,
    'macos': get_macbook_instruction,  # Алиас для MacBook
    'mac': get_macbook_instruction     # Алиас для MacBook
}

def get_instruction(instruction_name: str) -> str:
    """
    Получить инструкцию по имени
    
    Args:
        instruction_name: Название инструкции (happ, android_tv, steam_deck, oculus_quest, balance, coupon, refresh)
    
    Returns:
        Текст инструкции или пустую строку если не найдена
    """
    if instruction_name in INSTRUCTIONS:
        return INSTRUCTIONS[instruction_name]()
    return ""

def get_available_instructions() -> list:
    """Получить список доступных инструкций"""
    return list(INSTRUCTIONS.keys())
