from app.core.logger import setup_logger
from app.core.exceptions import setup_exception_handler
from app.clients.ollama_client import OllamaClient
from app.util.utils import pdf_to_pil_images
from app.src.classifier import Classification

logger = setup_logger()
setup_exception_handler()

def main():
    logger.info("Application starting...")
    
    # 1. Instantiate your chosen client (e.g., Ollama for now)
    ai_client = OllamaClient(model="minicpm-v:8b")
    
    # 2. Convert pdf to List[Images]
    pdf_path = "/home/lucifer/Projects/Project-QuoMatch/app/data/Camp Systems 1.pdf"
    image_list = pdf_to_pil_images(pdf_path=pdf_path)
    
    #. Inject it into your extractor
    # extractor = PDFExtractor(client=ai_client)
    
    # 3. Run Classification
    classifier = Classification(client=ai_client)
    classifier_result = classifier.start_classification(images=image_list)
    
    print(classifier_result)
    
    logger.info("Application completed successfully.")

if __name__ == "__main__":
    main()