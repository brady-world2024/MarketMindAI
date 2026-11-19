"""Local single-user ChatGPT plan OAuth, separate from API-key providers."""
from .errors import PlanError
from .service import LocalChatGPTAuth

__all__ = ["LocalChatGPTAuth", "PlanError"]
