import io
from pathlib import Path
from typing import List
from PIL import Image
import pymupdf 

from app.core.exceptions import QuoMatchException
from app.core.logger import setup_logger

logger = setup_logger()


def pdf_to_pil_images(pdf_path: str, dpi: int = 200) -> List[Image.Image]:
    """
    Renders all pages of a PDF into a list of PIL Images using PyMuPDF.
    """
    path = Path(pdf_path)
    if not path.exists():
        logger.error("PDF file not found at path: %s", pdf_path)
        raise QuoMatchException(f"PDF file not found: {pdf_path}")

    try:
        doc = pymupdf.open(str(path))
        num_pages = len(doc)
        logger.info("Rendering %d page(s) from '%s' at %d DPI", num_pages, path.name, dpi)

        images: List[Image.Image] = []
        # PyMuPDF scale factor: 72 DPI is base 1.0
        scale = dpi / 72.0
        matrix = pymupdf.Matrix(scale, scale)

        for page_idx in range(num_pages):
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=matrix)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)

        doc.close()
        return images
    except Exception as e:
        logger.error("Failed to convert PDF '%s' to images: %s", pdf_path, e)
        raise QuoMatchException(f"Error rendering PDF pages: {e}") from e


def compress_image_to_bytes(image: Image.Image, max_dim: int = 512, quality: int = 60) -> bytes:
    """
    Resizes and compresses an image in-memory to keep classification token sizes small.
    """
    try:
        img_copy = image.copy()
        img_copy.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

        if img_copy.mode != "RGB":
            img_copy = img_copy.convert("RGB")

        buffer = io.BytesIO()
        img_copy.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception as e:
        logger.error("Failed to compress image: %s", e)
        raise QuoMatchException(f"Image compression error: {e}") from e