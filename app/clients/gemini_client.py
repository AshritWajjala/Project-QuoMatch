import os
from typing import Any, List, Optional, Type
from google import genai
from google.genai import types
from pydantic import BaseModel

from app.clients.base import BaseLLMClient
from app.core.config import get_settings
from app.core.exceptions import LLMClientError
from app.core.logger import setup_logger

logger = setup_logger()
settings = get_settings()


class GeminiClient(BaseLLMClient):
  """Client for handling Google Gemini models via the Google GenAI SDK."""

  def __init__(
        self,
        model: str = "gemini-3.5-flash-lite",
        api_key: Optional[str] = None,
    ):
      self.model = model
      
      raw_key = (
          api_key
          or getattr(settings, "GEMINI_API_KEY", None)
          or os.getenv("GEMINI_API_KEY")
      )

      # Handle Pydantic SecretStr safely
      if hasattr(raw_key, "get_secret_value"):
        self.api_key = raw_key.get_secret_value()
      elif raw_key is not None:
        self.api_key = str(raw_key)
      else:
        self.api_key = None

      if not self.api_key:
        raise LLMClientError("GEMINI_API_KEY is not configured in settings or environment.")

      self.client = genai.Client(api_key=self.api_key)
      logger.info(f"Initialized GeminiClient with model: {self.model}")

  def generate_response(
      self,
      system_prompt: str,
      user_content: str,
      response_schema: Type[BaseModel],
      images: Optional[List[bytes]] = None,
      temperature: float = 0.0,
  ) -> BaseModel:
    logger.info(f"Sending prompt to Gemini model --> ({self.model})...")

    # 1. Build contents: images (as Part objects) + user prompt text
    contents: List[Any] = []
    if images:
      for img_bytes in images:
        contents.append(
            types.Part.from_bytes(
                data=img_bytes,
                mime_type="image/png",
            )
        )
    contents.append(user_content)

    # 2. Configure system instruction, temperature, and structured output schema
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=response_schema,
    )

    # 3. Execute generation
    try:
      response = self.client.models.generate_content(
          model=self.model,
          contents=contents,
          config=config,
      )
      logger.info("LLM response generated.")

    except Exception as e:
      raise LLMClientError(f"Gemini Inference Error: {e}") from e

    raw_text = response.text
    # For Debugging
    # logger.info(f"RAW GEMINI OUTPUT:\n{raw_text}")

    # 4. Validate output with target Pydantic schema
    try:
      logger.info(f"Validating Response Schema (set to {response_schema})")
      return response_schema.model_validate_json(raw_text)

    except Exception as e:
      logger.error(
          f"Failed schema validation against raw content: {raw_text[:500] if raw_text else 'None'}"
      )
      raise LLMClientError(f"Pydantic Validation Error: {e}") from e