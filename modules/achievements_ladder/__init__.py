# Ensure models are imported so that SQLAlchemy can discover them
from . import models  # noqa: F401
from .router import router
