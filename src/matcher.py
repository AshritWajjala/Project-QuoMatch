# matcher.py
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel
from rapidfuzz import fuzz
from extractor import CanonicalItem


class MatchStatus(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    FUZZY_MATCH = "FUZZY_MATCH"
    QTY_MISMATCH = "QTY_MISMATCH"
    MISSING = "MISSING"
    EXTRA = "EXTRA"


class DiffItem(BaseModel):
    item_id: Optional[str] = None
    description: str
    requested_qty: Optional[float] = None
    quoted_qty: Optional[float] = None
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    status: MatchStatus
    notes: Optional[str] = None


def resolve_display_description(item: CanonicalItem) -> str:
    if item.description_and_specs and len(item.description_and_specs.strip()) > 0:
        return item.description_and_specs.strip()
    if item.product_name and len(item.product_name.strip()) > 0:
        return item.product_name.strip()
    return item.product_id or "No description provided"


def reconcile_quotes(
    client_items: List[CanonicalItem],
    vendor_items: List[CanonicalItem],
    fuzzy_threshold: float = 70.0,
) -> List[DiffItem]:
    results: List[DiffItem] = []
    unmatched_vendor_indices = set(range(len(vendor_items)))

    for c_item in client_items:
        best_v_idx = None
        exact_sku = False
        best_score = 0.0

        if c_item.product_id:
            for v_idx in unmatched_vendor_indices:
                v_cand = vendor_items[v_idx]
                if v_cand.product_id and c_item.product_id.upper() == v_cand.product_id.upper():
                    best_v_idx = v_idx
                    exact_sku = True
                    best_score = 100.0
                    break

        if best_v_idx is None:
            c_text = c_item.description_and_specs or c_item.product_name or ""
            for v_idx in unmatched_vendor_indices:
                v_text = vendor_items[v_idx].description_and_specs or vendor_items[v_idx].product_name or ""
                score = fuzz.token_sort_ratio(c_text, v_text)
                if score >= fuzzy_threshold and score > best_score:
                    best_score = score
                    best_v_idx = v_idx

        if best_v_idx is not None:
            v_item = vendor_items[best_v_idx]
            unmatched_vendor_indices.remove(best_v_idx)

            disp_desc = resolve_display_description(c_item)
            if disp_desc == (c_item.product_id or ""):
                disp_desc = resolve_display_description(v_item)

            if abs((c_item.quantity or 0) - (v_item.quantity or 0)) > 0.001:
                status = MatchStatus.QTY_MISMATCH
                note = f"Qty Mismatch: Wanted {c_item.quantity}, got {v_item.quantity}"
            else:
                status = MatchStatus.EXACT_MATCH if exact_sku else MatchStatus.FUZZY_MATCH
                note = "Exact SKU match" if exact_sku else f"Fuzzy description match ({int(best_score)}% similarity)"

            results.append(
                DiffItem(
                    item_id=c_item.product_id or v_item.product_id,
                    description=disp_desc,
                    requested_qty=c_item.quantity,
                    quoted_qty=v_item.quantity,
                    unit_price=v_item.unit_price,
                    total_price=v_item.total_price,
                    status=status,
                    notes=note,
                )
            )
        else:
            results.append(
                DiffItem(
                    item_id=c_item.product_id,
                    description=resolve_display_description(c_item),
                    requested_qty=c_item.quantity,
                    status=MatchStatus.MISSING,
                    notes="Not found in vendor quotation",
                )
            )

    for v_idx in unmatched_vendor_indices:
        v_item = vendor_items[v_idx]
        results.append(
            DiffItem(
                item_id=v_item.product_id,
                description=resolve_display_description(v_item),
                quoted_qty=v_item.quantity,
                unit_price=v_item.unit_price,
                total_price=v_item.total_price,
                status=MatchStatus.EXTRA,
                notes="Unsolicited item or fee",
            )
        )

    return results