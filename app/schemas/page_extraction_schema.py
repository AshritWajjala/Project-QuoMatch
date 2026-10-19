from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# TIER 1: EXTRACTION SCHEMAS (What the VLM populates directly)
# --------------------------------------------------------------------------
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


class RawExtractedItem(BaseModel):
  page_number: int = Field(
      default=1,
      description="1-based physical page number where this row was spotted.",
  )
  raw_text: Optional[str] = Field(
      default=None,
      description="Verbatim text of the line/block if easily transcribable.",
  )
  line_type: Literal["PRODUCT", "SERVICE", "FEE", "DISCOUNT"] = Field(
      default="PRODUCT",
      description="Classification of the line item based on context.",
  )
  product_name: str = Field(
      ...,
      description=(
          "Concise commercial title or name of the product/service. Do NOT put"
          " pure catalog part numbers here if they can be placed in product_id."
      ),
  )
  product_id: Optional[str] = Field(
      default=None,
      description=(
          "The distinct alphanumeric SKU, Part Number, Catalog Code, or Model"
          " Number (e.g., 'EQP-WR-Z16-LJ-01', 'CM8148', 'OG-FNTS-CM8100-5YR')."
          " Check dedicated code columns (Code, Part #, Item Code) or standalone"
          " codes in the description block. If an identifier exists anywhere in"
          " the row, extract it here rather than leaving this null."
      ),
  )  
  description_and_specs: Optional[str] = Field(
      default=None,
      description=(
          "Technical specifications, feature bullets, port configurations, or"
          " explanatory notes located inside or beneath the table row. Do NOT"
          " isolate or duplicate standalone Part Numbers/SKUs here if they"
          " belong in product_id."
      ),
  )

  quantity: float = Field(
      default=1.0,
      description="Clean numeric quantity with units stripped (e.g., '4 units' -> 4.0).",
  )
  unit_of_measure: Optional[str] = Field(
      default=None,
      description="Unit label if explicitly stated (e.g., 'EA', 'PCS', 'Months').",
  )
  unit_price: float = Field(
      default=0.0,
      description="Base unit rate stripped of currency symbols and thousands separators.",
  )
  discount_percent: Optional[float] = Field(
      default=0.0,
      description="Discount percentage applied specifically to this item.",
  )
  total_price: float = Field(
      default=0.0,
      description="Extended line total printed on the physical document.",
  )

  attributes: Dict[str, str] = Field(
      default_factory=dict,
      description=(
          "Any non-standard vendor table columns (e.g., {'HSN': '8517',"
          " 'Lead_Time': '4 Weeks'})."
      ),
  )

class QuoteExtractionPayload(BaseModel):
  """Top-level container targeted by the VLM structured output."""

  quote_number: Optional[str] = Field(
      default=None,
      description="Quotation, Reference, Estimate, or Proforma number.",
  )
  quote_date: Optional[str] = Field(
      default=None, description="Document issue date in YYYY-MM-DD if available."
  )
  currency: Optional[str] = Field(
      default=None,
      description="Standard 3-letter currency code (e.g., 'USD', 'INR', 'EUR').",
  )
  vendor_name: Optional[str] = Field(
      default=None, description="Legal business entity issuing the quote."
  )

  items: List[RawExtractedItem] = Field(
      default_factory=list,
      description="All commercial items detected across the supplied pages.",
  )

  reported_subtotal: Optional[float] = Field(
      default=None,
      description="Pre-tax subtotal printed explicitly on the document.",
  )
  taxes_and_fees: Dict[str, float] = Field(
      default_factory=dict,
      description=(
          "All statutory taxes, freight, or handling fees with their visual"
          " labels preserved (e.g., {'CGST (9%)': 3330.0, 'Freight': 250.0})."
      ),
  )
  reported_grand_total: float = Field(
      ...,
      description="The final payable total printed explicitly on the document.",
  )


# --------------------------------------------------------------------------
# TIER 2: RECONCILIATION SCHEMAS (Enriched via Python logic)
# --------------------------------------------------------------------------


class CanonicalItem(RawExtractedItem):
  """Extends RawExtractedItem with deterministic mathematical audit fields."""

  math_verified: bool = Field(
      default=False,
      description="True if quantity * unit_price (with discount) matches total_price within tolerance.",
  )
  row_delta: float = Field(
      default=0.0,
      description="Absolute variance between computed row total and reported row total.",
  )
  discrepancy_note: Optional[str] = Field(
      default=None,
      description="Human-readable warning if the line item math does not reconcile.",
  )


class DocumentReconciliation(BaseModel):
  """Final domain object representing the fully extracted and mathematically verified quote."""

  quote_number: Optional[str] = None
  vendor_name: Optional[str] = None
  currency: Optional[str] = None

  total_rows_extracted: int
  items: List[CanonicalItem]

  calculated_subtotal: float
  reported_subtotal: Optional[float] = None
  total_taxes_and_fees: float
  taxes_and_fees_breakdown: Dict[str, float]

  reported_grand_total: float
  calculated_grand_total: float
  reconciliation_delta: float
  is_reconciled: bool