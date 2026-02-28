"""browser2api — Turn browser UIs into programmatic image generation APIs."""

__version__ = "0.1.0"

from .base import AbstractImageClient, AbstractLoginHandler, LoginManager
from .browser import BrowserManager, get_browser_manager
from .types import GeneratedImage, GenerationResult, GenerationStatus, Platform

__all__ = [
    "Platform",
    "GeneratedImage",
    "GenerationResult",
    "GenerationStatus",
    "AbstractImageClient",
    "AbstractLoginHandler",
    "LoginManager",
    "BrowserManager",
    "get_browser_manager",
    "__version__",
]
