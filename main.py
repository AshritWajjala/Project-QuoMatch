from app.core.logger import setup_logger
from app.core.exceptions import setup_exception_handler
from app.clients.ollama_client import OllamaClient
from app.util.utils import pdf_to_pil_images
from app.src.classifier import Classification
from app.src.extractor import Extraction

import json
from pprint import pprint

logger = setup_logger()
setup_exception_handler()

def main():
    logger.info("Application starting...")
    
    # 1. Instantiate your chosen client (e.g., Ollama for now)
    classification_client = OllamaClient(model="qwen2.5vl:7b")
    extraction_client = OllamaClient(model="qwen2.5vl:7b")
    
    # 2. Convert pdf to List[Images]
    pdf_path = "/home/lucifer/Projects/Project-QuoMatch/app/data/Camp Systems 1.pdf"
    image_list = pdf_to_pil_images(pdf_path=pdf_path)
    
    # 3. Run Classification
    classifier = Classification(llm_client=classification_client)
    classifier_result = classifier.start_classification(images=image_list)
    
    # 4. Run Extraction with the images returned by the classifier
    extractor = Extraction(llm_client=extraction_client)
    extraction_result = extractor.initiate_extraction(images=classifier_result)
    
    reconciled_result = extractor._reconcile(payload=extraction_result)
    
    pprint(reconciled_result.model_dump(), indent=2)
    
    logger.info("Application completed successfully.")

if __name__ == "__main__":
    main()