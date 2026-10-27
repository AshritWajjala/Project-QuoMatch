from typing import List, Optional
from PIL import Image

from app.clients.base import BaseLLMClient
from app.core.exceptions import setup_exception_handler, ExtractionError
from app.core.logger import setup_logger
from app.core.prompts import QUOTE_EXTRACTION_SYSTEM_PROMPT, build_quote_extraction_user_prompt
from app.schemas.page_extraction_schema import (
    QuoteExtractionPayload,
    CanonicalItem,
    DocumentReconciliation
)
from app.util.utils import compress_image_to_bytes

logger = setup_logger()
setup_exception_handler()

class Extraction:
    def __init__(self, llm_client: BaseLLMClient, reconciliation_tolerance: float = 0.05):
        self.llm_client = llm_client
        self.reconciliation_tolerance = reconciliation_tolerance
    
    def initiate_extraction(self, images: List[Image.Image]):
        
        # If there are no images extracted from classification process
        if not images:
            logger.info("No docs found for extraction.")
            raise ExtractionError("No docs found for extraction.")
        
        # Initializing system prompt & user content for VLM
        system_prompt = QUOTE_EXTRACTION_SYSTEM_PROMPT
        page_numbers = [i+1 for i in range(len(images))]
        user_content = build_quote_extraction_user_prompt(page_numbers=page_numbers)

        try:
            compressed_img_list = [compress_image_to_bytes(img, max_dim=1600, quality=85) for img in images]
        except Exception as e:
            raise ExtractionError(f"Error occurred while compressing images: {e}") from e        
            
        try:
            # Raw Data Extraction
            response: QuoteExtractionPayload = self.llm_client.generate_response(
                system_prompt=system_prompt,
                user_content=user_content,
                response_schema=QuoteExtractionPayload,
                images=compressed_img_list)
            
            return response
        
        except Exception as e:
            logger.error(f"Error occured while trying to extract data from images: {e}") 
            raise ExtractionError(f"Extraction inference failed: {e}") from e
    
    def _reconcile(self, payload: QuoteExtractionPayload) -> DocumentReconciliation:
        canonical_items: List[CanonicalItem] = []
        running_subtotal: float = 0.0

        for idx, item in enumerate(payload.items, start=1):
            discount_multiplier = 1.0 - (item.discount_percent / 100.0)
            expected_row_total = round(
                item.quantity * item.unit_price * discount_multiplier, 2
            )

            row_delta = round(abs(expected_row_total - item.total_price), 2)
            is_row_verified = row_delta <= self.reconciliation_tolerance

            discrepancy_note: Optional[str] = None
            if not is_row_verified:
                discrepancy_note = (
                    f"Row {idx} calculation mismatch: {item.quantity} * {item.unit_price} "
                    f"(less {item.discount_percent}% disc) = {expected_row_total:.2f}, "
                    f"but document reported {item.total_price:.2f} (delta: {row_delta:.2f})."
                )
                logger.warning(discrepancy_note)

            canonical_items.append(
                CanonicalItem(
                    **item.model_dump(),
                    math_verified=is_row_verified,
                    row_delta=row_delta,
                    discrepancy_note=discrepancy_note,
                )
            )
            running_subtotal += item.total_price

        running_subtotal = round(running_subtotal, 2)
        sum_taxes_and_fees = round(sum(payload.taxes_and_fees.values()), 2)
        calculated_grand_total = round(running_subtotal + sum_taxes_and_fees, 2)

        reconciliation_delta = round(
            abs(calculated_grand_total - payload.reported_grand_total), 2
        )
        is_reconciled = reconciliation_delta <= self.reconciliation_tolerance

        if not is_reconciled:
            logger.warning(
                "Document reconciliation failed: Subtotal (%.2f) + Taxes/Fees (%.2f) ="
                " %.2f, but Reported Grand Total is %.2f (delta: %.2f)",
                running_subtotal,
                sum_taxes_and_fees,
                calculated_grand_total,
                payload.reported_grand_total,
                reconciliation_delta,
            )
        else:
            logger.info(
                "Document reconciled successfully: %.2f == %.2f (delta: %.2f)",
                calculated_grand_total,
                payload.reported_grand_total,
                reconciliation_delta,
            )

        return DocumentReconciliation(
            quote_number=payload.quote_number,
            quote_date=payload.quote_date,
            vendor_name=payload.vendor_name,
            currency=payload.currency,
            total_rows_extracted=len(canonical_items),
            items=canonical_items,
            calculated_subtotal=running_subtotal,
            reported_subtotal=payload.reported_subtotal,
            total_taxes_and_fees=sum_taxes_and_fees,
            taxes_and_fees_breakdown=payload.taxes_and_fees,
            reported_grand_total=payload.reported_grand_total,
            calculated_grand_total=calculated_grand_total,
            reconciliation_delta=reconciliation_delta,
            is_reconciled=is_reconciled,
        )
                
            