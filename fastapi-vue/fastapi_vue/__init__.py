"""FastAPI Vue integration - serve Vue frontend from FastAPI."""

from .environ import env
from .staticfiles import Frontend

__all__ = ["Frontend", "env"]
