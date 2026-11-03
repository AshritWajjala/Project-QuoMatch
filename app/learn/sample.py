from app.clients.ollama_client import OllamaClient
from app.core.config import get_settings
from app.src.extractor import Extraction
from app.ingestion.pdf_parser import PDFIngestion
from PIL import Image
import time
from pprint import pprint

settings = get_settings()

start_time = time.perf_counter()

img_path = '/Users/ashritw/Downloads/WhatsApp Image 2026-10-30 at 11.36.40.jpeg'
remote_extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL, host_url=settings.HOME_PC_IP.get_secret_value())

remote_extractor = Extraction(llm_client=remote_extraction_client)


with Image.open(img_path) as img:
    img.load()

images = [img]


extractor_result = remote_extractor.initiate_pdf_extraction(images=images)

reconciled_result = remote_extractor._reconcile(payload=extractor_result)

pprint(reconciled_result.model_dump(), indent=2)

for index, item in enumerate(reconciled_result.items):
    print(f"Item{index+1}: {item.product_id}")

end_time = time.perf_counter()
elapsed_time = end_time - start_time

# 3. Print or log the result
print(f"\nExecution finished in {elapsed_time:.4f} seconds.")