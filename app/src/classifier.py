import logging
from typing import List
from PIL import Image

from app.clients.base import BaseLLMClient
from app.core.exceptions import ClassificationError, LLMClientError
from app.core.prompts import (
    PAGE_CLASSIFIER_SYSTEM_PROMPT,
    build_page_classification_user_prompt,
)
from app.schemas.page_classification_schema import DocumentClassificationResult
from app.util.utils import compress_image_to_bytes

logger = logging.getLogger(__name__)


class Classification:

  def __init__(self, client: BaseLLMClient):
    self.client = client

  def start_classification(self, images: List[Image.Image]) -> List[Image.Image]:
    if not images:
      return []

    # Single-page documents need no classification
    if len(images) == 1:
      logger.info("Single-page document detected. Retaining Page 1 directly.")
      return images

    try:
      compressed_img_list = [compress_image_to_bytes(img) for img in images]
    except Exception as e:
      raise ClassificationError(
          f"Error occurred while compressing images: {e}"
      ) from e

    system_prompt = PAGE_CLASSIFIER_SYSTEM_PROMPT
    user_content = build_page_classification_user_prompt(len(images))

    try:
      response: DocumentClassificationResult = self.client.generate_response(
          system_prompt=system_prompt,
          user_content=user_content,
          response_schema=DocumentClassificationResult,
          images=compressed_img_list,
      )
    except Exception as e:
        logger.warning(
            f"Classification inference failed: {e}. Failing open: passing all {len(images)} pages to extractor."
        )
        return images

    # Log decisions for visibility
    for page in response.pages:
      status = "KEEP" if page.is_commercial else "DROP"
      logger.info("Page %d: [%s] - %s", page.page_index + 1, status, page.reason)

    # Collect unique indices to maintain chronological order and prevent duplicates
    commercial_indices = {
        p.page_index
        for p in response.pages
        if p.is_commercial and 0 <= p.page_index < len(images)
    }

    # Fallback if every page was marked non-commercial
    if not commercial_indices:
        logger.warning(
            "Classifier marked all pages as non-commercial (possible false negative). "
            "Failing open: passing all %d pages to Stage 2.", len(images)
        )   
        return images

    return [images[i] for i in sorted(commercial_indices)]