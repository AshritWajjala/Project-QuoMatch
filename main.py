from app.core.logger import setup_logger
from app.core.exceptions import setup_exception_handler
from app.clients.ollama_client import OllamaClient
from app.clients.gemini_client import GeminiClient
from app.ingestion.pdf_parser import PDFIngestion
from app.src.classifier import Classification
from app.src.extractor import Extraction
from app.core.config import get_settings

from pprint import pprint

logger = setup_logger()
setup_exception_handler()
settings = get_settings()

def main():
    logger.info("Application starting (Remote Exec)...")
    
    # 1. Instantiate your chosen client (e.g., Ollama for now)
    classification_client = OllamaClient(model=settings.CLASSIFIER_MODEL)
    extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL)
    gemini_model = GeminiClient(api_key=settings.GEMINI_API_KEY.get_secret_value())
    
    # 2. Convert pdf to List[Images]
    pdf_path = "/home/lucifer/Projects/Project-QuoMatch/app/data/Jump Trade - WR and Opengear-0409.pdf"
    image_list = PDFIngestion.pdf_to_pil_images(pdf_path=pdf_path)

    # eml_path = "/Users/ashritw/Downloads/REQUIREMENT FOR _DELL (or) HP (or) LENOVO LAPTOP_.eml"
    
    # 3. Run Classification
    classifier = Classification(llm_client=classification_client)

    classifier_result = classifier.start_classification(images=image_list)
    
    # 4. Run Extraction with the images returned by the classifier
    extractor = Extraction(llm_client=extraction_client)
    # gemini_extractor = Extraction(llm_client=gemini_model)


    # extraction_result = extractor.initiate_extraction(images=classifier_result)
    extraction_result = extractor.initiate_pdf_extraction(images=classifier_result)
    
    reconciled_result = extractor._reconcile(payload=extraction_result)
    
    logger.info(f"Extracted Payload:\n{reconciled_result.model_dump_json(indent=2)}")
    
    logger.info("Application completed successfully.")

if __name__ == "__main__":
    main()