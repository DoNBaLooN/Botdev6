"""Ruletka module package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import models  # noqa: F401

__all__ = ("router",)


if TYPE_CHECKING:  # pragma: no cover - for static type checkers only
    from .router import router as router


def __getattr__(name: str):
    if name == "router":
        from .router import router as _router

        return _router
    raise AttributeError(f"module 'ruletka' has no attribute {name!r}")
