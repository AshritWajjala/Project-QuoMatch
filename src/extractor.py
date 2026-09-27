import os
import re
import warnings
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

os.environ["ORT_DISABLE_TELEMETRY"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")

from docling.document_converter import DocumentConverter


class CanonicalItem(BaseModel):
    source_table_ref: str
    row_idx: int
    raw_text: str = Field(description="The exact verbatim text string as it appears in the row/block.")
    line_type: Literal["PRODUCT", "FEE", "DISCOUNT"] = "PRODUCT"

    product_id: Optional[str] = None
    product_name: Optional[str] = None
    description_and_specs: Optional[str] = None

    quantity: float = 1.0
    unit_of_measure: Optional[str] = "pcs"
    unit_price: float = 0.0
    discount_percent: float = 0.0
    total_price: float = 0.0

    math_verified: bool = False
    discrepancy_note: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class DocumentReconciliation(BaseModel):
    total_rows_extracted: int
    reported_grand_total: Optional[float] = None
    calculated_subtotal: float
    taxes_and_fees: float = 0.0
    reconciliation_delta: float = 0.0
    is_reconciled: bool = True
    items: List[CanonicalItem]


def clean_numeric(val: Any) -> float:
    if val is None:
        return 0.0
    cleaned = re.sub(r"[^\d.-]", "", str(val).replace(",", "").strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def normalize_header(text: str) -> str:
    cleaned = text.strip().upper()
    return re.sub(r"(?<=\b[A-Za-z0-9])\s+(?=[A-Za-z0-9]\b)", "", cleaned)


def extract_embedded_quantity(text: str) -> float:
    m1 = re.search(r"Quantity(?:\s+Ordered)?[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m1:
        return float(m1.group(1))
    m2 = re.search(r"\bCount[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m2:
        return float(m2.group(1))
    m3 = re.search(r"\b(?:Pack\s+)?Qty[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if m3:
        return float(m3.group(1))
    return 1.0


def extract_embedded_sku(desc_text: str) -> Optional[str]:
    m_bracket = re.search(r"\[?(SKU-[A-Za-z0-9-]+)\]?", desc_text)
    if m_bracket:
        return m_bracket.group(1).strip("[]")
    matches = re.findall(r"\b[A-Z0-9]+(?:-[A-Z0-9]+){2,}\b", desc_text)
    if matches:
        return max(matches, key=len)
    model_match = re.search(r"\bModel\s+([A-Z0-9]{3,})\b", desc_text, re.IGNORECASE)
    if model_match:
        return model_match.group(1).upper()
    lines = [line.strip() for line in desc_text.split("\n") if line.strip()]
    for candidate in reversed(lines):
        if re.match(r"^[A-Z0-9]+(-[A-Z0-9]+)+$", candidate):
            return candidate
        if re.match(r"^[A-Z]{2,}\d{2,}[A-Z0-9]*$", candidate) and len(candidate) <= 15:
            return candidate
    return None


def transform_docling_dict(docling_data: Dict[str, Any]) -> DocumentReconciliation:
    extracted_items: List[CanonicalItem] = []
    reported_grand_total: Optional[float] = None
    reported_subtotal: Optional[float] = None
    detected_tax_fee_total: float = 0.0

    for table in docling_data.get("tables", []):
        table_ref = table.get("self_ref", "unknown_table")
        grid = table.get("data", {}).get("grid", [])

        if not grid or len(grid) < 2:
            continue

        raw_header = [cell.get("text", "") for cell in grid[0]]
        header_row = [normalize_header(h) for h in raw_header]
        col_map: Dict[str, int] = {}

        for idx, text in enumerate(header_row):
            if any(k in text for k in ["PRODUCT", "DESC", "SPEC"]):
                col_map["desc"] = idx
            elif re.search(r"\b(PART\s*NO\.?|SKU|PRODUCT\s*CODE|PRODUCT\s*ID)\b", text):
                col_map["sku"] = idx
            elif re.search(r"\b(ITEM|NO\.?|SR|S\.NO|#|LINE)\b", text) and "sku" not in col_map:
                col_map["item_seq"] = idx
            elif re.search(r"\b(QTY|QUANTITY|UNITS)\b", text):
                col_map["qty"] = idx
            elif re.search(r"\b(UNIT\s*PRICE|PRICE|RATE)\b", text):
                col_map["unit_price"] = idx
            elif re.search(r"\b(DISCOUNT|DISC)\b", text):
                col_map["discount"] = idx
            elif re.search(r"\b(AMOUNT|TOTAL|EXTENDED|LINE\s*TOTAL)\b", text):
                col_map["total_price"] = idx

        all_table_text = " ".join(cell.get("text", "").upper() for row in grid for cell in row)
        is_summary_table = any(k in all_table_text for k in ["SUBTOTAL", "CGST", "SGST", "IGST", "TOTAL", "TAX"])

        if is_summary_table and "total_price" not in col_map:
            for row in grid:
                row_texts = [cell.get("text", "").strip() for cell in row]
                joined = " ".join(row_texts).upper()
                num = clean_numeric(row_texts[-1]) if row_texts else clean_numeric(row_texts[0])

                if "SUBTOTAL" in joined and num > 0:
                    reported_subtotal = num
                elif any(t in joined for t in ["CGST", "SGST", "IGST", "TAX"]) and num > 0:
                    detected_tax_fee_total += num
                elif "TOTAL" in joined and "SUBTOTAL" not in joined and num > 0 and reported_grand_total is None:
                    reported_grand_total = num
            continue

        if "total_price" not in col_map or "desc" not in col_map:
            continue

        for r_idx, row in enumerate(grid[1:], start=1):
            row_texts = [cell.get("text", "").strip() for cell in row]
            joined_row_text = " ".join(t for t in row_texts if t).strip()

            if not joined_row_text:
                continue

            upper_joined = joined_row_text.upper()

            if re.search(r"\b(GRAND\s*TOTAL|TOTAL|BALANCE)\b", upper_joined) and "SUBTOTAL" not in upper_joined:
                for val_str in reversed(row_texts):
                    num = clean_numeric(val_str)
                    if num > 0:
                        reported_grand_total = num
                        break
                continue

            if re.search(r"\b(SUBTOTAL|TAXES?|VAT|S&H|SHIPPING\s*&\s*HANDLING)\b", upper_joined):
                fee_val = (
                    clean_numeric(row_texts[col_map["total_price"]])
                    if "total_price" in col_map and col_map["total_price"] < len(row_texts)
                    else 0.0
                )
                if any(k in upper_joined for k in ["S&H", "SHIPPING", "FREIGHT", "HANDLING"]):
                    extracted_items.append(
                        CanonicalItem(
                            source_table_ref=table_ref,
                            row_idx=r_idx,
                            raw_text=joined_row_text,
                            line_type="FEE",
                            product_id="FEE-SH",
                            product_name="Shipping & Handling",
                            description_and_specs=joined_row_text,
                            quantity=1.0,
                            unit_price=fee_val,
                            total_price=fee_val,
                            math_verified=True,
                        )
                    )
                elif any(k in upper_joined for k in ["TAX", "VAT"]):
                    detected_tax_fee_total += fee_val
                continue

            desc = row_texts[col_map["desc"]] if col_map["desc"] < len(row_texts) else ""
            tprice = clean_numeric(row_texts[col_map["total_price"]]) if col_map["total_price"] < len(row_texts) else 0.0
            uprice_val = clean_numeric(row_texts[col_map["unit_price"]]) if "unit_price" in col_map and col_map["unit_price"] < len(row_texts) else 0.0

            if tprice == 0.0 and uprice_val == 0.0:
                continuation_text = " ".join([t for t in row_texts if t]).strip()
                if continuation_text and extracted_items:
                    last_item = extracted_items[-1]
                    if last_item.description_and_specs:
                        last_item.description_and_specs = f"{last_item.description_and_specs} | {continuation_text}"
                    else:
                        last_item.description_and_specs = continuation_text
                continue

            if "qty" in col_map and col_map["qty"] < len(row_texts):
                qty_val = clean_numeric(row_texts[col_map["qty"]])
            else:
                qty_val = extract_embedded_quantity(desc)

            discount_val = clean_numeric(row_texts[col_map["discount"]]) if "discount" in col_map and col_map["discount"] < len(row_texts) else 0.0

            if not desc or (tprice == 0.0 and uprice_val == 0.0):
                continue

            sku = row_texts[col_map["sku"]] if "sku" in col_map and col_map["sku"] < len(row_texts) else None
            if not sku:
                sku = extract_embedded_sku(desc)

            seq_id = row_texts[col_map["item_seq"]] if "item_seq" in col_map and col_map["item_seq"] < len(row_texts) else f"{r_idx}"
            product_id = sku if sku else f"ITEM-{seq_id}"

            desc_lines = [l.strip() for l in desc.split("\n") if l.strip()]
            product_name = desc_lines[0] if desc_lines else desc

            is_fee = bool(re.search(r"\b(SHIPPING|FREIGHT|HANDLING|DUTY|TAX|PACKING)\b", desc.upper()))
            line_type: Literal["PRODUCT", "FEE", "DISCOUNT"] = "FEE" if is_fee else "PRODUCT"

            if line_type == "PRODUCT" and qty_val > 0 and uprice_val > 0:
                base = qty_val * uprice_val
                expected = round(base * (1.0 - (discount_val / 100.0)), 2) if discount_val > 0 else round(base, 2)
                math_passed = abs(expected - tprice) <= 1.0
                note = None if math_passed else f"Discrepancy: Expected {expected} (Discount: {discount_val}%), got {tprice}"
            else:
                math_passed = True
                note = None

            extracted_items.append(
                CanonicalItem(
                    source_table_ref=table_ref,
                    row_idx=r_idx,
                    raw_text=joined_row_text,
                    line_type=line_type,
                    product_id=product_id,
                    product_name=product_name,
                    description_and_specs=desc,
                    quantity=qty_val if qty_val > 0 else 1.0,
                    unit_price=uprice_val if uprice_val > 0 else tprice,
                    discount_percent=discount_val,
                    total_price=tprice,
                    math_verified=math_passed,
                    discrepancy_note=note,
                )
            )

    calculated_subtotal = round(sum(item.total_price for item in extracted_items), 2)
    is_reconciled = False
    delta = 0.0

    if reported_grand_total is not None:
        expected_grand = round(calculated_subtotal + detected_tax_fee_total, 2)
        delta = round(abs(reported_grand_total - expected_grand), 2)
        is_reconciled = delta <= 1.0
    elif reported_subtotal is not None:
        delta = round(abs(reported_subtotal - calculated_subtotal), 2)
        is_reconciled = delta <= 1.0

    return DocumentReconciliation(
        total_rows_extracted=len(extracted_items),
        reported_grand_total=reported_grand_total,
        calculated_subtotal=calculated_subtotal,
        taxes_and_fees=round(detected_tax_fee_total, 2),
        reconciliation_delta=delta,
        is_reconciled=is_reconciled,
        items=extracted_items,
    )


def extract_from_pdf(pdf_path: str) -> DocumentReconciliation:
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    return transform_docling_dict(result.document.export_to_dict())