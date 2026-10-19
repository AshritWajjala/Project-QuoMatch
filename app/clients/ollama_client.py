from app.clients.base import BaseLLMClient
from app.core.logger import setup_logger
from app.core.exceptions import LLMClientError
from ollama import Client
from typing import Optional, List, Type, Any, Dict
from pydantic import BaseModel

logger = setup_logger()

class OllamaClient(BaseLLMClient):
    """Client for handling local models via Ollama."""
    
    def __init__(self, model: str, num_predict: Optional[int]=None ,  timeout: int = 400, num_ctx: int = 16384, host_url: Optional[str]=None):
        self.host_url = host_url 
        self.model = model
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.client = Client(host=self.host_url, timeout=timeout) 
        logger.info(f"Initialized OllamaClient with host_url: {self.host_url}")

    def generate_response(self,
                          system_prompt: str, 
                          user_content: str, 
                          response_schema: Type[BaseModel], 
                          images: Optional[List[bytes]], 
                          temperature: float = 0.0
                          ) -> BaseModel:
        logger.info(f"Sending prompt to Ollama model --> ({self.model})...")
        
        user_payload: Dict[str, Any] = {"role": "user", "content": user_content}
        if images:
            user_payload["images"] = images
        
        messages = [
            {"role": "system", "content": system_prompt},
            user_payload
        ]
        
        try:
            response = self.client.chat(
                messages=messages,
                model=self.model,
                format=response_schema.model_json_schema(),
                options={"temperature": temperature, "num_ctx": self.num_ctx, "num_predict":self.num_predict}
            )
            logger.info("LLM response generated.")
                   
        except Exception as e:
            raise LLMClientError(f"Ollama Inference Error: {e}") from e
        
        try:
            logger.info(f"Validating Response Schema (set to {response_schema})")
            return response_schema.model_validate_json(response.message.content)
        
        except Exception as e:
            raise LLMClientError(f"Pydantic Validation Error: {e}") from e
        
