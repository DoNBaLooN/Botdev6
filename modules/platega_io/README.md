Platega — модуль пополнения баланса

Описание
Модуль добавляет платёжку Platega в меню пополнения баланса и собственный вебхук подтверждения платежей. Поддерживает ввод произвольной суммы и режим быстрого флоу для недостающей суммы при оплате/продлении. Интеграция с меню теперь выполняется через хук providers_config (новая система платежей).

Возможности
- Кнопка оплаты в меню «Пополнить» через providers_config (без ручной вставки кнопок)
- Выбор способа оплаты (настраиваемые методы)
- Быстрый флоу (fast flow) для недостающей суммы: отображает требуемую сумму и сразу предлагает оплату Platega
- Ввод произвольной суммы
- Вебхук подтверждения платежей с автоматическим зачислением на баланс

Установка и включение
1) Положите модуль в каталог modules/platega_io
2) Убедитесь, что ядро загружает модульные роутеры и вебхуки:
   - utils/modules_loader.load_modules_from_folder — для кнопок и хендлеров
   - utils/modules_loader.load_module_webhooks — для вебхуков
   - web.register_web_routes — там автоматически регистрируются пути модулей
3) Проверьте настройки в modules/platega/settings.py

Настройки (modules/platega/settings.py)
- ENABLE: включает/выключает модуль
- MERCHANT_ID, API_KEY: реквизиты Platega
- CALLBACK_PATH: маршрут вебхука, по умолчанию /platega/webhook
- SUCCESS_URL, FAILED_URL: ссылки возврата после оплаты
- PAYMENT_METHODS: список методов Platega с полями code/label/enable
- FAST_FLOW_ENABLE: включает быстрый флоу (для совместимости; в новой системе используется providers_config + handlers)
- (необязательно) PAYMENT_KEY: legacy-ключ для fast-flow через get_fast_flow_handler()

WebHook
- Модуль экспортирует get_webhook_data(), который возвращает {"path": CALLBACK_PATH, "handler": aiohttp_handler}
- Регистрация происходит автоматически в web/register_web_routes
- Вебхук проверяет заголовки X-MerchantId и X-Secret, и при статусе CONFIRMED:
  - Начисляет баланс пользователю tg_id из payload
  - Пишет запись о платеже через add_payment(session, tg_id, amount, "platega")

Использование — из меню пополнения
1) Откройте Профиль → Пополнить
2) Выберите способ Platega
3) Выберите сумму или нажмите «Ввести сумму»
4) Перейдите по ссылке «Оплатить», затем вернитесь и нажмите «Готово»

Быстрый флоу (fast flow)
- В новой системе fast-flow настраивается через providers_config: модуль экспортирует провайдера `PLATEGA` с полями
  - currency: "RUB"
  - value: "pay_platega"
  - fast: "handle_custom_amount_input_platega"
  - module: "platega_io"
- В config.py укажите провайдера для fast-flow:
  USE_NEW_PAYMENT_FLOW = "PLATEGA"  # или список, например ["PLATEGA", "KASSAI_CARDS"]
- При нехватке средств (создание/продление/подарок) общий механизм вызовет
  handlers.payments.platega_io.handlers.handle_custom_amount_input_platega(),
  который создаёт ссылку оплаты и показывает кнопку «Оплатить»

Callbacks
- pay_platega — старт выбора метода/суммы
- pay_plg|{method_code} — быстрый старт по конкретному методу
- platega_method|{method_code} — выбор метода
- platega_amount|{method_code}|{amount} — выбор суммы
- plg_custom_amount|{method_code} — ввод произвольной суммы, далее текстовое сообщение с суммой

Зависимости
- aiohttp (в проекте уже используется)
- aiogram (ядро бота)
- SQLAlchemy (ядро бота)

Примечания
- Если ни один метод не включён в PAYMENT_METHODS, модуль по умолчанию использует метод 2 (СБП / QR).
- Минимальную/максимальную сумму можно валидировать в обработчике handle_platega_custom_amount_input.

Тексты
- Все тексты модуля находятся в modules/platega_io/texts.py

