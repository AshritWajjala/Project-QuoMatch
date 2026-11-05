"""Test harness verifying QuoteComparator across all matching and arbitration scenarios."""

from app.schemas.page_extraction_schema import CanonicalItem, DocumentReconciliation
from app.src.comparator import QuoteComparator

# ---------------------------------------------------------
# 1. Target Client BOM (from your RFP / photo)
# ---------------------------------------------------------
client_bom = [
    {
        "sku": "DCS-7280CR3-32D4-R",
        "description": "Arista 7280R3 32x100GbE switch router",
        "quantity": 2.0,
    },
    {
        "sku": None,  # Pure description: Cisco 10G SFP+ Cable
        "description": "Cisco 10GBASE-CU SFP+ Cable 3 Meter",
        "quantity": 10.0,
    },
    {
        "sku": None,  # Pure description: Cat6 Slim Patch Cable
        "description": "10ft (3m) Cat6 28AWG Snagless Ethernet Network Patch Cable, Blue",
        "quantity": 3.0,
    },
    {
        "sku": "CAB-PWR-C13",
        "description": "Standard C13 Power Cord 2M",
        "quantity": 4.0,
    },
]

# ---------------------------------------------------------
# 2. Quote A: Verscale Quote (Cisco & FS)
# ---------------------------------------------------------
doc_a_items = [
    CanonicalItem(
        product_id="DCS-7280CR3-32D4-R",
        product_name="Arista Switch",
        description_and_specs="Arista 7280R3 32x100GbE switch router",
        quantity=2.0,
        unit_price=4100.0,
        total_price=8200.0,
    ),
    CanonicalItem(
        product_id="SFP-H10GB-CU3M",
        product_name="Cisco 10G Twinax",
        description_and_specs="Cisco 10GBASE-CU SFP+ Cable 3 Meter passive",
        quantity=10.0,
        unit_price=45.0,
        total_price=450.0,
    ),
    CanonicalItem(
        product_id="FS-CAT6-3M",
        product_name="FS Slim Patch Cable",
        description_and_specs="10ft (3m) Cat6 28AWG Snagless Ethernet Network Patch Cable Blue",
        quantity=3.0,
        unit_price=5.50,
        total_price=16.50,
    ),
    CanonicalItem(
        product_id="EXTRA-SUPPORT",
        product_name="Premium 24/7 SLA Support",
        description_and_specs="Yearly support fee for Arista infrastructure",
        quantity=1.0,
        unit_price=1500.0,
        total_price=1500.0,  # Unsolicited Scope Creep!
        line_type="SERVICE",
    ),
]

doc_a = DocumentReconciliation(
    doc_id="quote_verscale_01",
    vendor_name="Verscale Pte Ltd",
    quote_number="VER-2026-991",
    currency="USD",
    total_rows_extracted=len(doc_a_items),
    items=doc_a_items,
    calculated_subtotal=10166.50,
    reported_subtotal=10166.50,
    total_taxes_and_fees=0.0,
    taxes_and_fees_breakdown={},
    reported_grand_total=10166.50,
    calculated_grand_total=10166.50,
    reconciliation_delta=0.0,
    is_reconciled=True,
)

# ---------------------------------------------------------
# 3. Quote B: SP Sysnet Quote (Alternative Bidder)
# ---------------------------------------------------------
doc_b_items = [
    CanonicalItem(
        product_id="DCS7280CR332D4R",  # Normalized match: no hyphens
        product_name="Arista 7280R3 Switch",
        description_and_specs="Arista 7280R3 32x100G switch router",
        quantity=2.0,
        unit_price=3950.0,  # Cheaper switch!
        total_price=7900.0,
    ),
    CanonicalItem(
        product_id="SFP-H10GB-CU3M",
        product_name="10G SFP+ Cable",
        description_and_specs="Cisco 10GBASE-CU SFP+ Cable 3 Meter",
        quantity=10.0,
        unit_price=48.0,
        total_price=480.0,
    ),
    CanonicalItem(
        product_id=None,  # Embedded in text: CAB-PWR-C13
        product_name="Power Cord",
        description_and_specs="CAB-PWR-C13 C13 Power Cord 2M 250V 10A",
        quantity=4.0,
        unit_price=12.0,
        total_price=48.0,
    ),
]

doc_b = DocumentReconciliation(
    doc_id="quote_spsysnet_02",
    vendor_name="SP SYSNET",
    quote_number="SPS/JPT/2026-Q10",
    currency="USD",
    total_rows_extracted=len(doc_b_items),
    items=doc_b_items,
    calculated_subtotal=8428.00,
    reported_subtotal=8428.00,
    total_taxes_and_fees=0.0,
    taxes_and_fees_breakdown={},
    reported_grand_total=8428.00,
    calculated_grand_total=8428.00,
    reconciliation_delta=0.0,
    is_reconciled=True,
)

# ---------------------------------------------------------
# 4. Run the Comparison Engine
# ---------------------------------------------------------
report = QuoteComparator.compare(
    client_bom=client_bom,
    vendor_quotes=[doc_a, doc_b],
    target_currency="USD",
    client_name="Singapore Edge Network Expansion",
)

# ---------------------------------------------------------
# 5. Print Results
# ---------------------------------------------------------
print("\n" + "=" * 70)
print(f"EXECUTIVE REPORT: {report.client_name}")
print("=" * 70)
print(f"Total BOM Items:           {report.total_requested_items}")
print(f"Fully Quoted Items:        {report.fully_matched_items}")
print(f"Partially Quoted Items:    {report.partially_matched_items}")
print(f"Compliance Rates:          {report.doc_compliance_rates}")
print(f"Total Spend by Vendor:     {report.total_spend_by_doc_id}")
print(f"Optimal Hybrid Spend:      ${report.optimal_hybrid_spend:,.2f}")
print(f"Max Potential Savings:     ${report.max_potential_savings:,.2f}")
print(f"Recommended Single Vendor: {report.overall_recommended_vendor_name} ({report.overall_recommended_doc_id})")

print("\n" + "=" * 70)
print("LINE-ITEM COMPARISON MATRIX")
print("=" * 70)
for r in report.rows:
    sku_label = r.requested_sku or "[NO SKU - DESC ONLY]"
    print(f"\nLine {r.line_number}: {sku_label}")
    print(f"  Requirement: {r.requested_description}")
    print(f"  Quantity:    {r.requested_quantity}")

    for doc_id, offer in r.vendor_offers.items():
        vendor_name = report.doc_metadata[doc_id]
        if offer:
            print(
                f"  -> {vendor_name:<18}: ${offer.unit_price:>8.2f}/ea | "
                f"Total: ${offer.total_price:>8.2f} | Stage: {offer.match_stage.value:<13} | Verdict: {offer.verdict.value}"
            )
        else:
            print(f"  -> {vendor_name:<18}: [MISSING / UNQUOTED]")

    savings_str = f"${r.potential_total_savings:.2f}" if r.potential_total_savings else "$0.00"
    print(f"  ★ WINNER: {r.recommended_vendor_name} @ ${r.lowest_unit_price:.2f}/ea (Savings vs 2nd: {savings_str})")

print("\n" + "=" * 70)
print("UNSOLICITED / EXTRA ITEMS (SCOPE CREEP ALERTS)")
print("=" * 70)
for doc_id, extras in report.unsolicited_items_by_doc_id.items():
    vendor_name = report.doc_metadata[doc_id]
    if extras:
        print(f"\n{vendor_name} added {len(extras)} unrequested item(s):")
        for ex in extras:
            print(f"  - [{ex.product_id}] {ex.product_name}")
            print(f"    Quoted: {ex.quantity} @ ${ex.unit_price:.2f} = ${ex.total_price:.2f}")
            print(f"    Reason: {ex.flag_reason}")
    else:
        print(f"\n{vendor_name}: Zero unsolicited items (Clean Scope).")