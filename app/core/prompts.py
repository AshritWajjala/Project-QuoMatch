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
- `page_number`: The 1-based page number where this specific line item appears.
- `raw_text`: The exact, unedited text string of the row or block as printed on the document.
- `line_type`: Classify as "PRODUCT", "SERVICE", "FEE", or "DISCOUNT".
- `product_id`: Extract the primary alphanumeric SKU, Part Number, Model Code, or Item Code (e.g., "EQP-WR-Z16-LJ-01", "CM8148", "OG-FNTS-CM8100-5YR"). 
- Look for column headers like "Part #", "Code", "Item #", "Model", or "Catalog ID".
- If a short alphanumeric model code appears in the description cell, prioritize extracting it into `product_id`.
- Never place pure part codes or SKUs into `description_and_specs` while leaving `product_id` as null.
- `product_name`: Concise commercial title or name of the item/service.
- `description_and_specs`: Captures functional specs, dimensions, port counts, or license tier descriptions. Exclude standalone product part numbers extracted into `product_id`.
- `quantity`: Parse as a clean decimal/float. Strip units of measure (e.g., convert "4 pcs", "1.00 Appliance" into 4.0 or 1.0). If unspecified, default to 1.0.
- `unit_of_measure`: Capture unit strings if explicitly printed (e.g., "pcs", "ea", "months"), otherwise null.
- `unit_price`: Clean numeric rate per unit. Strip all currency signs ($, €, ₹, USD, INR) and comma formatting.
- `discount_percent`: Percentage discount applied directly to this line if specified, otherwise 0.0.
- `total_price`: The extended row total printed on the page. Strip all currency signs and formatting.
- `attributes`: Store any vendor-specific metadata or extra columns (e.g., "HSN_SAC", "UOM", "Lead_Time", "Serial_Number", "Rev") as dynamic string key-value pairs.

2. SUB-ITEMS & HIERARCHIES:
- For nested sub-items (e.g., item 2.1 under item 2), extract each as an individual line item.
- Maintain parent context in `product_name` or `description_and_specs` if necessary.

3. FINANCIAL TOTALS & TAXES:
- reported_subtotal: The pre-tax taxable amount printed explicitly on the document (null if not explicitly labeled).
- taxes_and_fees: Dynamically capture ONLY statutory taxes, freight, or surcharges that are EXPLICITLY printed on the document with non-zero or stated amounts.
- Use the exact label and rate printed on the document as the key, and the printed numeric value as a float.
- If the document has NO taxes listed, or if taxes are explicitly 0, not applicable, or excluded, return an EMPTY object: 
{}.
- NEVER invent or assume tax rates or copy example tax numbers.
- reported_grand_total: The final payable total printed explicitly on the document.

4. EXCLUSIONS & BOUNDARIES:
- Do NOT treat summary rows (e.g., "Subtotal", "Balance Due", "Total Taxable Amount", "Round Off") as individual line items. Map them to the corresponding totals fields.
- Discard all boilerplate legal text, warranty terms, bank payment details (IBAN, SWIFT, Account numbers), company registration IDs (GSTIN, CIF), and signature block metadata.
- If description text has spilled into numeric columns due to layout OCR alignment, resolve the text into `description_and_specs` and normalize the numerical values.

5. OUTPUT FORMAT:
- Output ONLY a valid JSON object matching the requested schema.
- Do not compute, recalculate, or alter printed numbers. Extract only what is visibly printed.
""".strip()


def build_quote_extraction_user_prompt(page_numbers: List[int]) -> str:
    pages_str = ", ".join(f"Page {p}" for p in page_numbers)
    return (
        f"Extract all commercial quotation items and totals from the attached image(s) ({pages_str}).\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. You MUST extract every individual row from the items table into the 'items' list.\n"
        "2. Do not return an empty 'items' list if there is a table of products/services visible on the page.\n"
        "3. Extract the pre-tax row totals, quantities, and unit rates for each item."
    )


# ==============================================================================
# STAGE 2 (EMAIL): EMAIL QUOTE & LINE ITEM EXTRACTION PROMPTS
# ==============================================================================

EMAIL_QUOTE_EXTRACTION_SYSTEM_PROMPT = """
You are an expert procurement and financial document extraction specialist analyzing an email quote.
Analyze the provided email content and extract quotation details into a strict JSON object conforming to the target schema.

Follow these operational invariants:

1. LINE ITEMS IDENTIFICATION:
- Identify every distinct commercial product, service, subscription, or explicit fee (e.g., Shipping/Freight, Handling, Implementation) in tables or structured text.
- Do NOT omit line items simply because they lack explicit table borders or appear as plain text entries.
- For each line item:
  - `page_number`: Default to 1 for email extractions.
  - `raw_text`: The exact, unedited text string of the row or block as written in the email.
  - `line_type`: Classify as "PRODUCT", "SERVICE", "FEE", or "DISCOUNT".
  - `product_id`: Extract the primary alphanumeric SKU, Part Number, Model Code, or Item Code (e.g., "EQP-WR-Z16-LJ-01", "CM8148", "OG-FNTS-CM8100-5YR").
    - If a short alphanumeric model code appears in the description, prioritize extracting it into `product_id`.
    - If no product ID / SKU exists, leave it null.
  - `product_name`: Concise commercial title or name of the item/service.
  - `description_and_specs`: Captures functional specs, dimensions, port counts, or license tier descriptions. Exclude standalone product part numbers extracted into `product_id`.
  - `quantity`: Parse as a clean decimal/float. Strip units of measure (e.g., convert "4 pcs", "1.00 Appliance" into 4.0 or 1.0). If unspecified, default to 1.0.
  - `unit_of_measure`: Capture unit strings if explicitly printed (e.g., "pcs", "ea", "months"), otherwise null.
  - `unit_price`: Clean numeric rate per unit. Strip all currency signs ($, €, ₹, USD, INR) and comma formatting.
  - `discount_percent`: Percentage discount applied directly to this line if specified, otherwise 0.0.
  - `total_price`: The extended row total written in the email. Strip all currency signs and formatting.
  - `attributes`: Store any vendor-specific metadata or extra details as dynamic string key-value pairs.

2. UNLABELED TRAILING SPECIFICATIONS & SCOPE RESOLUTION:
- Vendors frequently put minimal info in the pricing table (e.g., just "Item 1" or a short code) and place the full hardware specifications, part descriptions, port configurations, or SLA terms in paragraphs, bullet points, or footnotes DIRECTLY BELOW the table.
- You MUST link trailing descriptions to the relevant line item using:
  * MODEL / TOKEN CO-REFERENCE: If trailing text mentions a brand, SKU fragment, port count, or product family appearing in a table row, bind those specifications into that specific item's `description_and_specs`.
  * SEMANTIC MATCHING: If trailing text discusses an item by name or functional description (e.g., "The console server includes 48 serial ports..."), attach it to the matching row regardless of where it appears.
  * BLANKET / GLOBAL SPECIFICATIONS: If trailing text applies to all hardware (e.g., "All equipment includes 3-year 24x7 TAC support and dual power cables"), append that statement to the `description_and_specs` or `attributes` of EVERY applicable item.
- Do NOT treat descriptive notes as separate product line items. Merge them into `description_and_specs`.

3. FINANCIAL TOTALS & TAXES:
- reported_subtotal: The pre-tax taxable amount written explicitly in the email (null if not explicitly labeled).
- taxes_and_fees: Dynamically capture ONLY statutory taxes, freight, or surcharges that are EXPLICITLY written with non-zero or stated amounts.
  * Use the exact label and rate printed as the key, and the numeric value as a float.
  * If the email has NO taxes listed, or if taxes are explicitly 0, not applicable, or excluded, return an EMPTY object: {}.
  * NEVER invent or assume tax rates or copy example tax numbers.
- reported_grand_total: The final payable total printed explicitly in the email.
- currency: Extract the 3-letter currency code (e.g., INR, USD, EUR).

4. EXCLUSIONS & BOUNDARIES:
- Do NOT treat summary rows (e.g., "Subtotal", "Balance Due", "Total Taxable Amount", "Round Off") as individual line items. Map them to the corresponding totals fields.
- Discard all boilerplate email signatures, legal disclaimers, confidentiality notices, bank payment details, and phone numbers.

5. OUTPUT FORMAT:
- Output ONLY a valid JSON object matching the requested schema.
- Do not compute, recalculate, or alter written numbers. Extract only what is visibly present.
""".strip()