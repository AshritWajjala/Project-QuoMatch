from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class MatchStage(str, Enum):
    """Identifies which waterfall layer resolved the line-item match."""
    EXACT_SKU = "EXACT_SKU"            # Stage 1: Deterministic normalized string match
    TOKEN_REGEX = "TOKEN_REGEX"        # Stage 2: Target SKU discovered inside description/name
    SEMANTIC_BLOB = "SEMANTIC_BLOB"    # Stage 3: Hybrid keyword/dense vector similarity
    LLM_JUDGE = "LLM_JUDGE"            # Stage 4: Small LLM evaluated ambiguous specs
    NO_MATCH = "NO_MATCH"              # No credible candidate identified


class MatchVerdict(str, Enum):
    """The functional compatibility assessment between target item and vendor item."""
    IDENTICAL = "IDENTICAL"                            # 1:1 identical product match
    COMPATIBLE_SUBSTITUTE = "COMPATIBLE_SUBSTITUTE"    # Equivalent alternate (equal specs)
    DIFFERENT_SPEC = "DIFFERENT_SPEC"                  # Same category, but spec mismatch
    MISMATCH = "MISMATCH"                              # Completely unrelated item


class VendorItemOffer(BaseModel):
    """Represents a single vendor's matched offering against a requested client item."""
    vendor_name: str = Field(..., description="Name of the vendor providing the quote")
    quote_number: Optional[str] = Field(default=None, description="Identifier of the source quotation")
    matched_product_id: Optional[str] = Field(default=None, description="Part number quoted by vendor")
    matched_product_name: Optional[str] = Field(default=None, description="Product title extracted from quote")
    matched_description: Optional[str] = Field(default=None, description="Full specs as quoted by vendor")
    
    # Financial data
    unit_price: float = Field(..., ge=0.0, description="Pre-tax rate per single unit")
    discount_percent: float = Field(default=0.0, ge=0.0, description="Item-level discount percent")
    total_price: float = Field(..., ge=0.0, description="Extended price for the full required quantity")
    currency: Optional[str] = Field(default="USD", description="3-letter currency code")
    
    # Matching metadata & audit trail
    match_stage: MatchStage = Field(..., description="Which waterfall tier made the decision")
    verdict: MatchVerdict = Field(default=MatchVerdict.IDENTICAL, description="Compatibility classification")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Match confidence score between 0.0 and 1.0")
    spec_discrepancies: List[str] = Field(default_factory=list, description="List of observed spec or warranty variances")
    audit_notes: Optional[str] = Field(default=None, description="Human or LLM rationale explaining this match")


class UnsolicitedVendorItem(BaseModel):
    """An extra item quoted by a vendor that has no corresponding match in the Client BOM."""
    vendor_name: str = Field(..., description="Vendor that added this unrequested item")
    quote_number: Optional[str] = Field(default=None, description="Source quote ID")
    product_id: Optional[str] = Field(default=None, description="Part number quoted by vendor")
    product_name: Optional[str] = Field(default=None, description="Product title")
    description_and_specs: Optional[str] = Field(default=None, description="Item description")
    quantity: float = Field(..., ge=0.0, description="Quantity quoted by vendor")
    unit_price: float = Field(..., ge=0.0, description="Unit price quoted by vendor")
    total_price: float = Field(..., ge=0.0, description="Total extended price of the extra item")
    flag_reason: str = Field(
        default="Item present in vendor quote but absent from Client BOM (Potential Scope Creep)",
        description="Explanation for why this item was flagged"
    )


class ClientBOMComparisonRow(BaseModel):
    """A single target row in the Master Comparison Matrix (1 Client Requirement vs N Vendor Bids)."""
    line_number: int = Field(..., description="Sequential index matching client BOM order")
    requested_sku: Optional[str] = Field(default=None, description="SKU or MPN specified by client BOM")
    requested_description: str = Field(..., description="Full spec requirement from client BOM")
    requested_quantity: float = Field(..., gt=0.0, description="Quantity client intends to purchase")
    unit_of_measure: Optional[str] = Field(default=None, description="Packaging unit (e.g. PCS, BOX, EA)")
    
    # Dictionary mapping Vendor Name -> Their specific matched offer (None = Missing/Unquoted)
    vendor_offers: Dict[str, Optional[VendorItemOffer]] = Field(
        default_factory=dict,
        description="Keyed by vendor name. Contains offer details or None if vendor didn't quote"
    )
    
    # Discrepancy flags for this specific BOM line
    missing_from_vendors: List[str] = Field(
        default_factory=list,
        description="List of vendor names that completely omitted this required item"
    )
    
    # Price arbitration metrics
    lowest_unit_price: Optional[float] = Field(default=None, description="Lowest verified unit price among all vendors")
    recommended_vendor: Optional[str] = Field(default=None, description="Vendor offering the lowest verified price")
    potential_unit_savings: Optional[float] = Field(default=None, description="Price spread between recommended and next best offer")
    potential_total_savings: Optional[float] = Field(default=None, description="Unit savings multiplied by requested quantity")


class MultiVendorComparisonReport(BaseModel):
    """Executive-level procurement report aggregating all rows, metrics, and global recommendations."""
    client_name: Optional[str] = Field(default="Client Requisition", description="Name of company or requisition project")
    participating_vendors: List[str] = Field(default_factory=list, description="List of vendor names evaluated")
    currency: str = Field(default="USD", description="Target normalized currency across all comparisons")
    
    # Primary Matrix Rows (Aligned to Client BOM)
    rows: List[ClientBOMComparisonRow] = Field(default_factory=list, description="Row-by-row matrix lines")
    
    # Extra / Unsolicited Items (Items vendors quoted that were NOT in the Client BOM)
    unsolicited_items_by_vendor: Dict[str, List[UnsolicitedVendorItem]] = Field(
        default_factory=dict,
        description="Extra items per vendor that have no counterpart in the Client BOM"
    )
    
    # Executive KPI Rollups
    total_requested_items: int = Field(default=0, description="Total distinct line items in client BOM")
    fully_matched_items: int = Field(default=0, description="Items quoted by 100% of participating vendors")
    partially_matched_items: int = Field(default=0, description="Items quoted by at least one but not all vendors")
    unmatched_items: int = Field(default=0, description="Items missing from all vendor quotes")
    
    # Scope Compliance Metrics
    vendor_compliance_rates: Dict[str, float] = Field(
        default_factory=dict,
        description="Percentage of BOM items covered by vendor (e.g. {'Vendor A': 100.0, 'Vendor B': 80.0})"
    )
    
    # Global Spend Analysis
    total_spend_by_vendor: Dict[str, float] = Field(
        default_factory=dict, 
        description="Total cost if purchasing 100% of covered items from Vendor X"
    )
    unsolicited_spend_by_vendor: Dict[str, float] = Field(
        default_factory=dict,
        description="Total cost of extra items added by each vendor"
    )
    optimal_hybrid_spend: float = Field(
        default=0.0, 
        description="Total spend if 'cherry-picking' the cheapest vendor for every individual row"
    )
    max_potential_savings: float = Field(
        default=0.0, 
        description="Difference between highest vendor total and optimal hybrid spend"
    )
    overall_recommended_vendor: Optional[str] = Field(
        default=None, 
        description="Best single-source vendor by price and catalog coverage"
    )