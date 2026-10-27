from app.core.logger import setup_logger
from app.core.exceptions import setup_exception_handler
from app.clients.ollama_client import OllamaClient
from app.util.utils import pdf_to_pil_images
from app.src.classifier import Classification
from app.src.extractor import Extraction
from app.core.config import get_settings

from pprint import pprint

logger = setup_logger()
setup_exception_handler()
settings = get_settings()

def main():
    logger.info("Application starting...")
    
    # 1. Instantiate your chosen client (e.g., Ollama for now)
    # classification_client = OllamaClient(model=settings.CLASSIFIER_MODEL)
    # extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL)
    
    # Remote Exec 
    remote_classification_client = OllamaClient(model=settings.CLASSIFIER_MODEL, host_url=settings.HOME_PC_IP.get_secret_value())
    remote_extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL, host_url=settings.HOME_PC_IP.get_secret_value())
    
    # 2. Convert pdf to List[Images]
    pdf_path = "/Users/ashritw/Documents/Projects/Project-QuoMatch/app/data/Camp Systems 1.pdf"
    image_list = pdf_to_pil_images(pdf_path=pdf_path)

    eml_path = "/Users/ashritw/Downloads/REQUIREMENT FOR _DELL (or) HP (or) LENOVO LAPTOP_.eml"
    
    # 3. Run Classification
    # classifier = Classification(llm_client=classification_client)
    # remote_classifier = Classification(llm_client=remote_classification_client)

    
    # classifier_result = remote_classifier.start_classification(images=image_list)
    
    # 4. Run Extraction with the images returned by the classifier
    # extractor = Extraction(llm_client=extraction_client)
    remote_extractor = Extraction(llm_client=remote_extraction_client)


    # extraction_result = extractor.initiate_extraction(images=classifier_result)
    extraction_result = remote_extractor.initiate_email_extraction(eml_source=eml_path)
    
    reconciled_result = remote_extractor._reconcile(payload=extraction_result)
    
    pprint(reconciled_result.model_dump(), indent=2)
    
    logger.info("Application completed successfully.")

if __name__ == "__main__":
    main()