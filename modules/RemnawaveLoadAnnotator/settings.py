"""Настройки модуля Remnawave Load Annotator."""

ENABLED = True

INTERVAL_SEC = 300  # Интервал опроса node_exporter (секунды)
DELTA_MIN = 5  # Минимальное изменение процента, чтобы обновить ремарк
MAX_REMARK_LEN = 40  # Максимальная длина ремарка в Remnawave
CONNECT_TIMEOUT = 10  # Таймаут HTTP-запросов к node_exporter (секунды)

SCALE_PER_CORE = False  # Включить мягкую шкалу нагрузки на ядро
PER_CORE_MIN = 0.2
PER_CORE_MAX = 1.0

# Конфигурация нод.
# Для каждой ноды нужно указать отображаемое имя, endpoint node_exporter и UUID хоста в Remnawave.
# Получить список хостов и их UUID можно из панели администратора бота (кнопка «📋 Хосты Remnawave»).
# Пример записи:
# {
#     "title": "🇩🇪 Германия",
#     "endpoint": "de-host:9100",
#     "uuid": "f964a24b-28c4-4f5e-bd90-483302cab127",
# }
NODES = ()
