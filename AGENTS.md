**Документация-промт для модулей Solo\_bot (расширенная с примерами)**

Ты создаёшь независимый модуль для Solo\_bot.

---

### Цели модульной системы

* **Изоляция** — модуль в `modules/<name>/`, хранит свои тексты/настройки.
* **Подключаемость** — модуль подключается автоматически, если в `router.py` экспортируется `router`.
* **Расширяемость UI** — хуки для добавления/удаления кнопок.
* **Безопасность** — ошибки модуля логируются и не ломают ядро.

---

### Структура модуля (минимум)

```
modules/
  my_module/
    __init__.py   # экспорт router, импорт моделей
    router.py     # основной код: Router, хуки
    texts.py      # тексты
    settings.py   # настройки
    models.py     # (опц.) таблицы SQLAlchemy
    db.py         # (опц.) DAO
```

**Пример `__init__.py`:**

```python
__all__ = ("router",)
from .router import router
from . import models  # noqa: F401
```

---

### Работа с базой данных

* Таблицы описываются в `models.py`, импортируются в `__init__.py`.
* Использовать `AsyncSession`.
* Даты/время — naive UTC (`TIMESTAMP WITHOUT TIME ZONE`).

**Пример модели:**

```python
from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey
from database.models import Base

class ChannelBonusClaim(Base):
    __tablename__ = "channel_bonus_claims"
    tg_id = Column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), primary_key=True)
    claimed_at = Column(DateTime, default=datetime.utcnow)
```

**DAO (`db.py`):**

```python
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from .models import ChannelBonusClaim

async def has_claim(session: AsyncSession, tg_id: int) -> bool:
    res = await session.execute(select(ChannelBonusClaim).where(ChannelBonusClaim.tg_id == tg_id))
    return res.scalar_one_or_none() is not None

async def set_claim(session: AsyncSession, tg_id: int):
    stmt = (insert(ChannelBonusClaim)
            .values(tg_id=tg_id)
            .on_conflict_do_nothing(index_elements=[ChannelBonusClaim.tg_id]))
    await session.execute(stmt)
    await session.commit()
```

---

### Хуки (через `register_hook`)

Доступные: `start_menu`, `profile_menu`, `view_key_menu`, `pay_menu_buttons`, `admin_panel`, `periodic_notifications`.

**Пример кнопки в профиле:**

```python
from aiogram.types import InlineKeyboardButton
from hooks.hooks import register_hook

async def profile_menu_hook(**kwargs):
    return {"after": "balance", "button": InlineKeyboardButton(text="🏆 Топ", callback_data="top_referrers")}

register_hook("profile_menu", profile_menu_hook)
```

**Протокол кнопок:**

* Добавление в конец: `{"button": btn}`
* Вставка после: `{"after": "balance", "button": btn}`
* Удаление: `{"remove": "callback_data"}`
* Удаление по префиксу: `{"remove_prefix": "legacy_"}`

**Пример замены кнопки:**

```python
async def view_key_menu_hook(key_name: str, **kwargs):
    return [
        {"remove": f"connect_tv|{key_name}"},
        {"button": InlineKeyboardButton(text="📺 Happ TV", callback_data=f"happ_tv|{key_name}")},
    ]
register_hook("view_key_menu", view_key_menu_hook)
```

---

### Периодические уведомления

```python
from hooks.hooks import register_hook

async def periodic_notify(bot, session, keys, **kwargs):
    # keys — список активных подписок
    pass

register_hook("periodic_notifications", periodic_notify)
```

---

### Быстрые сценарии оплаты (опционально)

```python
def get_fast_flow_handler():
    return {"payment_key": "my_flow", "handler": my_flow_handler}
```

---

### Вебхуки модулей (опционально)

```python
def get_webhook_data():
    return {"path": "/api/my_module", "handler": my_webhook_handler}
```

---

### FSM и UX

* Всегда добавляй кнопку «Назад»/«Отмена».
* Очищай состояние при ошибке/завершении.

**Пример кнопки «Назад»:**

```python
@router.callback_query(F.data.startswith("my_flow_cancel|"))
async def my_flow_cancel(callback: CallbackQuery, state: FSMContext, session):
    await state.clear()
    await callback.message.edit_text("Возврат в профиль")
```

---

### Тексты и настройки

**settings.py:**

```python
ENABLE_BUTTON = True
MIN_TOPUP_RUB = 100
TOP_N = 5
```

**texts.py:**

```python
BTN_TOP = "🏆 Топ пригласивших"
TITLE = "<b>🏆 Топ пригласивших</b>\n"
ENTRY = "{place}. <code>{masked_id}</code> — {count} рефералов\n"
```

---

### Лучшие практики

* Обработчики короткие, бизнес-логика вынесена в функции.
* Сетевые вызовы через `aiohttp` с таймаутом 10–15 сек.
* Логирование через `from logger import logger`.

---

### Чек-лист публикации

* `router` экспортирован.
* Тексты → `texts.py`, настройки → `settings.py`.
* FSM очищается.
* Хуки зарегистрированы.
* Кнопки меняются через протокол.
* Сетевые вызовы с таймаутами.
* Даты/время согласованы с БД.

---
