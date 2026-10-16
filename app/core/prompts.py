"""
app/core/prompts.py

Centralized repository for system instructions and user prompt templates.
Houses both Stage 1 (Page Classification) and Stage 2 (Quote Extraction) prompts.
"""

from typing import List


# ==============================================================================
# STAGE 1: PAGE CLASSIFICATION PROMPTS
# ==============================================================================

PAGE_CLASSIFIER_SYSTEM_PROMPT = """
You are an expert procurement document page classifier.
Analyze the provided document page image(s) and determine whether each page is COMMERCIAL or NON-COMMERCIAL.

DECISION CRITERIA:
1. Mark as COMMERCIAL (is_commercial = True):
   - The page contains commercial quote line items (products, part numbers, descriptions with quantities or prices).
   - The page contains financial summaries, subtotals, tax breakdowns (GST/VAT), or grand totals.
   - HYBRID PAGES: If a page has ANY line items or pricing totals, even if mixed with Terms & Conditions or Bank Info, you MUST mark it as TRUE.

2. Mark as NON-COMMERCIAL (is_commercial = False):
   - The page is exclusively legal contract clauses, export controls, or general terms & conditions (zero pricing).
   - The page is a hardware technical datasheet / architecture diagram (like port counts, throughput Mbps) with no quotation pricing.
   - The page is a blank end-customer template / blank registration form.
   - The page contains only signature blocks or bank details with NO products, quantities, or financial totals.

Classify each page index accurately.
""".strip()


def build_page_classification_user_prompt(total_pages: int) -> str:
    """
    Constructs the user content string mapping page indices to page labels.
    Explicitly provides 0-based indices so the VLM returns exact programmatic bounds.
    """
    page_lines = [
        f"- Image index {idx}: Page {idx + 1}"
        for idx in range(total_pages)
    ]
    index_list_str = "\n".join(page_lines)

    return (
        "Classify the following document pages based on the attached images:\n"
        f"{index_list_str}\n\n"
        "Evaluate each page image according to the rules and output the classification list."
    )


# ==============================================================================
# STAGE 2: QUOTE & LINE ITEM EXTRACTION PROMPTS
# ==============================================================================

QUOTE_EXTRACTION_SYSTEM_PROMPT = """
You are an expert procurement and financial document extraction specialist.
Analyze the provided document page image(s) and extract the quotation details into a strict JSON object conforming to the target schema.

Follow these operational invariants:

1. LINE ITEMS IDENTIFICATION:
   - Identify every distinct commercial product, service, subscription, or explicit fee (e.g., Shipping/Freight, Handling, Implementation).
   - Do NOT omit line items simply because they lack explicit table borders or appear as multi-line text entries.
   - For each line item:
     * `line_type`: Classify as "PRODUCT", "SERVICE", or "FEE".
     * `product_id`: Extract the SKU, Part Number, Catalog Code, or Model Number. If no explicit identifier exists, assign a sequential ID (e.g., "ITEM-1", "ITEM-2").
     * `product_name`: Extract the concise commercial title or item name.
     * `description_and_specs`: Capture all accompanying specifications, configurations, hardware attributes, or loose descriptive notes printed either inside the row or immediately beneath it.
     * `quantity`: Parse as a clean decimal/float. Strip units of measure (e.g., convert "4 pcs", "1.00 Appliance" into 4.0 or 1.0). If unspecified, default to 1.0.
     * `unit_price`: Clean numeric rate per unit. Strip all currency signs ($, €, ₹, USD, INR) and comma formatting.
     * `discount_percent`: Percentage discount applied directly to this line if specified, otherwise 0.0.
     * `total_price`: The extended row total. If missing or misaligned, ensure it reflects quantity * unit_price.
     * `extra_attributes`: Store any vendor-specific metadata present in the columns (e.g., "HSN_SAC", "UOM", "Lead_Time", "Serial_Number", "Rev") as dynamic key-value pairs.

2. SUB-ITEMS & HIERARCHIES:
   - For nested sub-items (e.g., item 2.1 under item 2), extract each as an individual line item.
   - Maintain parent context in `product_name` or `description_and_specs` if necessary.

3. FINANCIAL TOTALS & TAXES:
   - `subtotal`: The pre-tax taxable base amount.
   - `taxes_and_surcharges`: Dynamically capture all taxes, GST, VAT, duties, or local surcharges as key-value pairs (e.g., {"CGST (9%)": 3330.0, "SGST (9%)": 3330.0} or {"GST (9.0%)": 132.03}). The keys must preserve the tax name and rate, and values must be clean numeric floats.
   - `grand_total`: The final payable invoice/quote total including all taxes, shipping, and fees.
   - `currency`: Identify the primary 3-letter currency code (e.g., "USD", "INR", "EUR", "SGD"). Default to null if indeterminate.

4. EXCLUSIONS & BOUNDARIES:
   - Do NOT treat summary rows (e.g., "Subtotal", "Balance Due", "Total Taxable Amount", "Round Off") as individual line items. Map them to the corresponding totals fields.
   - Discard all boilerplate legal text, warranty terms, bank payment details (IBAN, SWIFT, Account numbers), company registration IDs (GSTIN, CIF), and signature block metadata.
   - If description text has spilled into numeric columns due to layout OCR alignment, resolve the text into `description_and_specs` and normalize the numerical values.

5. OUTPUT FORMAT:
   - Output ONLY a valid JSON object matching the requested schema. 
   - Do not include explanatory introductions, markdown code fences (```json ... ```), or commentary.
""".strip()


def build_quote_extraction_user_prompt(page_numbers: List[int]) -> str:
    """
    Constructs the execution prompt for Stage 2 extraction.
    Informs the model of which physical pages are attached and requests extraction.
    """
    if len(page_numbers) == 1:
        return (
            f"Extract all commercial quotation items, tax details, and financial totals "
            f"from the attached image of Page {page_numbers[0]}."
        )

    pages_str = ", ".join(f"Page {p}" for p in page_numbers)
    return (
        f"Extract all commercial quotation items, tax details, and financial totals "
        f"spanning across the attached images ({pages_str}). "
        f"Consolidate all line items and resolve multi-page tables into a single unified record."
    )