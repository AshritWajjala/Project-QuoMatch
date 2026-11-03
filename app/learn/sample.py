from app.core.logger import setup_logger
from app.core.exceptions import setup_exception_handler
from app.clients.ollama_client import OllamaClient
from app.ingestion.pdf_parser import PDFIngestion
from app.src.classifier import Classification
from app.src.extractor import Extraction
from app.core.config import get_settings

import time

logger = setup_logger()
setup_exception_handler()
settings = get_settings()

def main():
    start_time = time.perf_counter()
    logger.info("Application starting...")
    
    remote_extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL)

    
    # 4. Run Extraction with the images returned by the classifier
    # extractor = Extraction(llm_client=extraction_client)
    remote_extractor = Extraction(llm_client=remote_extraction_client)


    # extraction_result = extractor.initiate_extraction(images=classifier_result)
    excel_path = "/home/lucifer/Downloads/test_quote_3_highest_products.xlsx"
    extraction_result = remote_extractor.initiate_excel_extraction(excel_source=excel_path)
    
    reconciled_result = remote_extractor._reconcile(payload=extraction_result)
    
    logger.info(f"Validated Payload:\n{reconciled_result.model_dump_json(indent=2)}")
    
    logger.info("Application completed successfully.")
    
    end_time = time.perf_counter()
    execution_time = end_time - start_time
    print(f"Execution time: {execution_time:.6f} seconds")
    
if __name__ == "__main__":
    main()