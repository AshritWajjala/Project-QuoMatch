from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Generic Key-Value Models to avoid `additionalProperties` in Gemini API
# --------------------------------------------------------------------------
class KeyValueAttribute(BaseModel):
  """Dynamic key-value pair for custom table columns."""

  key: str = Field(..., description="Column or spec name (e.g., 'Lead_Time')")
  value: str = Field(..., description="Value associated with the key")


class TaxOrFeeItem(BaseModel):
  """Individual statutory tax, surcharge, or freight fee."""

  name: str = Field(
      ..., description="Tax or fee label (e.g., 'CGST (9.0%)', 'Freight')"
  )
  amount: float = Field(..., description="Numeric value of the tax or fee")

class ClientBOMItem(BaseModel):
  line_number: Optional[int] = Field(
      default=None, description="Row index if numbered"
  )
  sku: Optional[str] = Field(
      default=None,
      description=(
          "Explicit part number or model code ONLY if clearly isolated as an"
          " alphanumeric code. If it is a sentence or description, leave null."
      ),
  )
  description: str = Field(
      ...,
      description=(
          "Full item text, name, and technical specifications requested by the"
          " client."
      ),
  )
  quantity: float = Field(
      default=1.0,
      description="Quantity required. Defaults to 1.0 if not specified.",
  )
  unit_of_measure: Optional[str] = Field(
      default="pcs",
      description="Unit of measure (e.g., pcs, units, meters, lot)",
  )


class ClientBOMPayload(BaseModel):
  """Schema specifically for client requisitions, BOMs, RFQs, and purchase inquiries."""

  project_or_client_name: Optional[str] = Field(
      default=None, description="Client name or project title if present"
  )
  items: List[ClientBOMItem] = Field(
      ..., description="All line items requested in the BOM"
  )

# --------------------------------------------------------------------------
# TIER 1: EXTRACTION SCHEMAS (What the VLM populates directly)
# --------------------------------------------------------------------------
class RawExtractedItem(BaseModel):
  page_number: int = Field(
      default=1,
      description="1-based physical page number where this row was spotted.",
  )
  raw_text: Optional[str] = Field(
      default=None,
      description="Verbatim text of the line/block as printed on the document.",
  )
  line_type: Literal["PRODUCT", "SERVICE", "FEE", "DISCOUNT"] = Field(
      default="PRODUCT",
      description="Classification of the line item based on context.",
  )
  product_name: Optional[str] = Field(
      default=None,
      description="Concise commercial title or name of the product/service.",
  )
  product_id: Optional[str] = Field(
      default=None,
      description=(
          "Alphanumeric SKU, Part Number, Catalog Code, or Model Number."
      ),
  )
  description_and_specs: Optional[str] = Field(
      default=None,
      description="Technical specifications, port configurations, and notes.",
  )
  quantity: float = Field(
      default=1.0,
      description="Clean numeric quantity with units stripped.",
  )
  unit_of_measure: Optional[str] = Field(
      default=None,
      description="Unit label if explicitly stated (e.g., 'EA', 'PCS').",
  )
  unit_price: float = Field(
      default=0.0,
      description="Base unit rate stripped of currency signs and commas.",
  )
  discount_percent: Optional[float] = Field(
      default=0.0,
      description="Discount percentage applied specifically to this item.",
  )
  total_price: float = Field(
      default=0.0,
      description="Extended line total printed on the physical document.",
  )

  # Replaced Dict[str, str] with List[KeyValueAttribute]
  attributes: List[KeyValueAttribute] = Field(
      default_factory=list,
      description="Any non-standard vendor table columns as key-value pairs.",
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
      ...,
      description="All commercial items detected across the supplied pages.",
  )

  reported_subtotal: Optional[float] = Field(
      default=None,
      description="Pre-tax subtotal printed explicitly on the document.",
  )

  # Replaced Dict[str, float] with List[TaxOrFeeItem]
  taxes_and_fees: List[TaxOrFeeItem] = Field(
      default_factory=list,
      description=(
          "All statutory taxes, freight, or handling fees with their visual"
          " labels preserved."
      ),
  )

  reported_grand_total: float = Field(
      ...,
      description="The final payable total printed explicitly on the document.",
  )


# --------------------------------------------------------------------------
# TIER 2: RECONCILIATION SCHEMAS
# --------------------------------------------------------------------------
class CanonicalItem(RawExtractedItem):
  """Extends RawExtractedItem with deterministic mathematical audit fields."""

  math_verified: bool = Field(
      default=False,
      description=(
          "True if quantity * unit_price (with discount) matches total_price."
      ),
  )
  row_delta: float = Field(
      default=0.0,
      description=(
          "Absolute variance between computed row total and reported row total."
      ),
  )
  discrepancy_note: Optional[str] = Field(
      default=None,
      description="Human-readable warning if the line item math does not reconcile.",
  )


class DocumentReconciliation(BaseModel):
  """Final domain object representing verified quote data."""

  doc_id: Optional[str] = None
  quote_number: Optional[str] = None
  vendor_name: Optional[str] = None
  currency: Optional[str] = None

  total_rows_extracted: int
  items: List[CanonicalItem]

  calculated_subtotal: float
  reported_subtotal: Optional[float] = None
  total_taxes_and_fees: float
  taxes_and_fees_breakdown: Dict[str, float] = Field(default_factory=dict)

  reported_grand_total: float
  calculated_grand_total: float
  reconciliation_delta: float
  is_reconciled: bool