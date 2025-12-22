ENABLE = True
MERCHANT_ID = "6d39a204-491d-4a62-9ec8-b5e406568c9d"
API_KEY = "G5toDEKpzeryFcMX1KEooFlLhZil32LSTglOwEOzfpOyiURD23lLDi1MVHH43a7p749x0zyI0XX0BPBSqn2PknR7ljtAGwrvYQP5"
CALLBACK_PATH = "/platega/webhook"
SUCCESS_URL = "https://t.me/WBVLess_bot"
FAILED_URL = "https://t.me/WBVLess_bot"

# Методы оплаты Platega. Включайте/выключайте по необходимости.
# code: 2 (SBP/QR), 9 (ALL_RU), 10 (CardRu P2P), 11 (Card 2DS), 12 (International)
PAYMENT_METHODS = [
    {"code": 2, "label": "🏦 СБП", "enable": True},
    {"code": 9, "label": "ALL_RU", "enable": False},
    {"code": 10, "label": "CardRu", "enable": False},
    {"code": 11, "label": "Card", "enable": False},
    {"code": 12, "label": "International", "enable": False},
]

# Быстрый флоу (fast flow)
FAST_FLOW_ENABLE: bool = True
# Ключ, по которому модуль будет найден загрузчиком быстрого флоу
PAYMENT_KEY: str = "PLATEGA_FAST"


