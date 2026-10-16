import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """Abstract interface for all Vision & Language model clients."""

    @abstractmethod
    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        response_schema: Type[BaseModel],
        images: Optional[List[bytes]] = None,
        content: str = "",
        temperature: float = 0.0,
    ) -> BaseModel:
        """
        Sends messages (and optional images) to the model and validates
        the output against a target Pydantic schema.

        Raises:
            LLMClientError: If inference, connection, or response validation fails.
        """
        pass