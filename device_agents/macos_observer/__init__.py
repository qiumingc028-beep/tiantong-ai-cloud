from .agent import MacReadonlyObserverAgent
from .config import MacObserverConfig
from .screen_capture import StaticScreenCaptureProvider
from .vision import LocalRuleBasedVisionProvider
from .window_provider import StaticWindowProvider

__all__ = [
    "MacObserverConfig",
    "MacReadonlyObserverAgent",
    "StaticScreenCaptureProvider",
    "LocalRuleBasedVisionProvider",
    "StaticWindowProvider",
]
