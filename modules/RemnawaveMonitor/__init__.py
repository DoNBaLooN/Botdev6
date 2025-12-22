from . import (
    models,  # noqa: F401
    settings as _settings,
)


if getattr(_settings, "ENABLED", True):
    from .router import router
else:
    from aiogram import Router
    router = Router()

__all__ = ("router",)
