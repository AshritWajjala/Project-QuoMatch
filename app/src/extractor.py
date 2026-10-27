
from pathlib import Path
from typing import List, Optional, Union
from PIL import Image

from app.clients.base import BaseLLMClient
from app.core.exceptions import setup_exception_handler, ExtractionError
from app.core.logger import setup_logger
from app.core.prompts import QUOTE_EXTRACTION_SYSTEM_PROMPT, build_quote_extraction_user_prompt, EMAIL_QUOTE_EXTRACTION_SYSTEM_PROMPT
from app.schemas.page_extraction_schema import (
    QuoteExtractionPayload,
    CanonicalItem,
    DocumentReconciliation
)
from app.util.email_parser_utils import EmailIngestionService
from app.util.utils import compress_image_to_bytes

logger = setup_logger()
setup_exception_handler()


class Extraction:
    """Handles multi-format extraction and deterministic math reconciliation for quotations.

    Attributes:
        llm_client (BaseLLMClient): Client interface for executing LLM inference.
        reconciliation_tolerance (float): Maximum permissible delta for floating point
            comparisons between line item calculations and stated totals.
    """

    def __init__(self, llm_client: BaseLLMClient, reconciliation_tolerance: float = 0.05):
        """Initializes the Extraction service.

        Args:
            llm_client (BaseLLMClient): The LLM client implementation to use.
            reconciliation_tolerance (float, optional): Monetary tolerance for
                reconciliation deltas. Defaults to 0.05.
        """
        self.llm_client = llm_client
        self.reconciliation_tolerance = reconciliation_tolerance

    def initiate_pdf_extraction(self, images: List[Image.Image]) -> QuoteExtractionPayload:
        """Extracts structured quote data from pre-classified PDF page images.

        Args:
            images (List[Image.Image]): Rendered PIL images of retained PDF document pages.

        Returns:
            QuoteExtractionPayload: Validated extraction payload adhering to schema.

        Raises:
            ExtractionError: If no images are supplied, image compression fails,
                or model inference encounters an unhandled exception.
        """
        # If there are no images extracted from classification process
        if not images:
            logger.info("No docs found for extraction.")
            raise ExtractionError("No docs found for extraction.")

        # Initializing system prompt & user content for VLM
        system_prompt = QUOTE_EXTRACTION_SYSTEM_PROMPT
        page_numbers = [i + 1 for i in range(len(images))]
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
                images=compressed_img_list
            )
            return response

        except Exception as e:
            logger.error(f"Error occured while trying to extract data from images: {e}")
            raise ExtractionError(f"Extraction inference failed: {e}") from e

    def initiate_email_extraction(self, eml_source: Union[str, Path]) -> QuoteExtractionPayload:
        """Extracts structured quote data directly from an RFC 822 email file (.eml).

        Parses the email structure, prunes historical reply thread blocks,
        and prompts the LLM in text-only mode to capture line items and unstructured
        trailing specifications located underneath the quotation table.

        Args:
            eml_source (Union[str, Path]): Local file system path to the .eml file.

        Returns:
            QuoteExtractionPayload: Validated extraction payload adhering to schema.

        Raises:
            ExtractionError: If file loading, reply pruning, or model inference fails.
        """
        eml_path = Path(eml_source)
        if not eml_path.exists():
            logger.error(f"Email file not found: {eml_path.resolve()}")
            raise ExtractionError(f"Email file not found at: {eml_path.resolve()}")

        try:
            cleaned_message_body = EmailIngestionService.extract_active_message_content(eml_path)
        except Exception as e:
            logger.error(f"Failed to parse and clean email content from {eml_path.name}: {e}")
            raise ExtractionError(f"Email body extraction failed: {e}") from e

        if not cleaned_message_body.strip():
            logger.error(f"Extracted active email body is empty for {eml_path.name}")
            raise ExtractionError("Email message body is empty after stripping reply history.")

        system_prompt = EMAIL_QUOTE_EXTRACTION_SYSTEM_PROMPT
        user_content = (
            f"Extract all commercial quote line items, specifications, and totals from this active "
            f"email message:\n\n{cleaned_message_body}"
        )

        try:
            response: QuoteExtractionPayload = self.llm_client.generate_response(
                system_prompt=system_prompt,
                user_content=user_content,
                response_schema=QuoteExtractionPayload,
                images=None
            )
            return response
        except Exception as e:
            logger.error(f"Error occurred while extracting data from email: {e}")
            raise ExtractionError(f"Email extraction inference failed: {e}") from e

    def _reconcile(self, payload: QuoteExtractionPayload) -> DocumentReconciliation:
        """Executes deterministic math reconciliation and line-item delta verification.

        Validates calculated line totals against stated rates and discounts, verifies
        statutory taxes, checks reported grand totals against row sums, and normalizes
        attributes into canonical representations.

        Args:
            payload (QuoteExtractionPayload): Raw extraction payload from PDF or Email.

        Returns:
            DocumentReconciliation: Fully verified, deterministic financial record.
        """
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