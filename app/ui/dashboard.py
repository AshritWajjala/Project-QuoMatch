"""Minimalist Executive Procurement & Quote Comparison Dashboard."""

from pathlib import Path
import sys
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import streamlit as st
import tempfile

from app.clients.gemini_client import GeminiClient
from app.clients.ollama_client import OllamaClient
from app.schemas.comparison_schema import MatchVerdict, MultiVendorComparisonReport
from app.src.classifier import Classification
from app.src.comparator import QuoteComparator
from app.src.extractor import Extraction
from app.ingestion.pdf_parser import PDFIngestion
from app.ingestion.excel_parser import ExcelIngestion
from app.core.config import get_settings

settings = get_settings()

# --------------------------------------------------------------------------
# PAGE CONFIGURATION & MINIMALIST STYLING
# --------------------------------------------------------------------------
st.set_page_config(
    page_title="QuoMatch | Procurement Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-title { font-size: 1.75rem; font-weight: 700; color: #0F172A; margin-bottom: 0rem; }
    .sub-title { font-size: 0.9rem; color: #64748B; margin-bottom: 1.5rem; }
    .legend-box { display: flex; gap: 20px; margin-bottom: 12px; font-size: 0.82rem; font-weight: 600; color: #334155; }
    .legend-item { display: flex; align-items: center; gap: 6px; }
    .legend-dot { width: 12px; height: 12px; border-radius: 3px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# INITIALIZE LLM & PIPELINE SERVICES
# --------------------------------------------------------------------------
@st.cache_resource
def get_services():
    llm = OllamaClient(model=settings.CLASSIFIER_MODEL)
    classifier = Classification(llm_client=llm)
    extractor = Extraction(llm_client=llm)
    return classifier, extractor


classifier, extractor = get_services()


# --------------------------------------------------------------------------
# SIDEBAR: DOCUMENT INGESTION
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Document Ingestion")
    st.caption("Upload Client BOM and Vendor Quote files.")
    st.divider()

    client_file = st.file_uploader(
        "Client BOM (PDF, Excel, or Image)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"]
    )
    vendor_files = st.file_uploader(
        "Vendor Quotations (PDF, Excel, or Image)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"], accept_multiple_files=True
    )

    st.divider()
    run_btn = st.button("Run Comparison Pipeline", type="primary", use_container_width=True)

# --------------------------------------------------------------------------
# MAIN DASHBOARD AREA
# --------------------------------------------------------------------------
st.markdown('<div class="main-title">QuoMatch Intelligence Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Automated VLM Extraction & Multi-Vendor Price Arbitration</div>', unsafe_allow_html=True)


def format_currency(amount: float | None, currency: str | None = "USD") -> str:
    if amount is None:
        return "N/A"
    curr_str = (currency or "USD").upper()
    symbol = "₹" if curr_str == "INR" else "$"
    return f"{symbol}{amount:,.2f}"


if not run_btn:
    st.info("Upload your Client BOM and Vendor Quote files in the sidebar, then click Run Comparison Pipeline.")
else:
    if not client_file or not vendor_files:
        st.error("Please provide both a Client BOM file and at least one Vendor Quote file.")
        st.stop()

    with st.spinner("Processing documents through VLM extraction & reconciliation..."):
        try:
            # 1. Parse Client BOM
            client_bom: List[Dict[str, Any]] = []
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(client_file.name).suffix) as tmp_client:
                tmp_client.write(client_file.getbuffer())
                client_tmp_path = tmp_client.name

            try:
                file_ext = Path(client_file.name).suffix.lower()
                if file_ext == ".pdf":
                    client_images = PDFIngestion.pdf_to_pil_images(client_tmp_path)
                    client_payload = extractor.initiate_pdf_extraction(client_images)
                    for item in client_payload.items:
                        client_bom.append({
                            "product_id": item.product_id,
                            "description": item.description_and_specs or item.raw_text,
                            "quantity": item.quantity,
                            "unit_of_measure": item.unit_of_measure,
                        })
                elif file_ext in [".png", ".jpg", ".jpeg"]:
                    from PIL import Image as PILImage
                    img = PILImage.open(client_tmp_path)
                    client_payload = extractor.initiate_pdf_extraction(images=[img])
                    for item in client_payload.items:
                        client_bom.append({
                            "product_id": item.product_id,
                            "description": item.description_and_specs or item.raw_text,
                            "quantity": item.quantity,
                            "unit_of_measure": item.unit_of_measure,
                        })
                else:
                    excel_payload = extractor.initiate_excel_extraction(client_tmp_path)
                    for item in excel_payload.items:
                        client_bom.append({
                            "product_id": item.product_id,
                            "description": item.description_and_specs or item.raw_text,
                            "quantity": item.quantity,
                            "unit_of_measure": item.unit_of_measure,
                        })
            finally:
                Path(client_tmp_path).unlink(missing_ok=True)

            # 2. Parse Vendor Quote Files (PDF, Excel, or Image)
            vendor_reconciliations = []
            for idx, v_file in enumerate(vendor_files, start=1):
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(v_file.name).suffix) as tmp_v:
                    tmp_v.write(v_file.getbuffer())
                    v_tmp_path = tmp_v.name

                try:
                    v_ext = Path(v_file.name).suffix.lower()
                    if v_ext == ".pdf":
                        v_images = PDFIngestion.pdf_to_pil_images(v_tmp_path)
                        filtered_images = classifier.start_classification(v_images)
                        raw_payload = extractor.initiate_pdf_extraction(filtered_images)
                    elif v_ext in [".png", ".jpg", ".jpeg"]:
                        from PIL import Image as PILImage
                        img = PILImage.open(v_tmp_path)
                        raw_payload = extractor.initiate_pdf_extraction(images=[img])
                    else:
                        raw_payload = extractor.initiate_excel_extraction(v_tmp_path)

                    reconciled_doc = extractor._reconcile(raw_payload)
                    reconciled_doc.doc_id = f"doc_{idx}"
                    if not reconciled_doc.vendor_name:
                        reconciled_doc.vendor_name = v_file.name.rsplit(".", 1)[0]
                    vendor_reconciliations.append(reconciled_doc)
                finally:
                    Path(v_tmp_path).unlink(missing_ok=True)

            # 3. Run Comparison Engine
            target_curr = vendor_reconciliations[0].currency or "USD"
            report: MultiVendorComparisonReport = QuoteComparator.compare(
                client_bom=client_bom,
                vendor_quotes=vendor_reconciliations,
                target_currency=target_curr,
                client_name="Client Requisition",
            )

        except Exception as e:
            st.error(f"Pipeline execution failed: {e}")
            st.exception(e)
            st.stop()

    # --------------------------------------------------------------------------
    # EXECUTIVE SUMMARY METRICS
    # --------------------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Optimal Best Spend", format_currency(report.optimal_hybrid_spend, report.currency))
    c2.metric("Total Potential Savings", format_currency(report.max_potential_savings, report.currency))
    c3.metric("Top Recommended Vendor", report.overall_recommended_vendor_name or "N/A")
    c4.metric("Extra Charges (Scope Creep)", format_currency(sum(report.unsolicited_spend_by_doc_id.values()), report.currency))

    st.divider()

    # --------------------------------------------------------------------------
    # MASTER MATRIX TABS
    # --------------------------------------------------------------------------
    tab_matrix, tab_audit, tab_json = st.tabs(["Comparison Matrix", "Vendor Breakdown", "Raw JSON Data"])

    with tab_matrix:
        st.markdown("#### Master Comparison Matrix")
        st.caption("Side-by-side vendor evaluation aligned against client bill of materials.")

        # Legend
        st.markdown(
            """
            <div class="legend-box">
                <div class="legend-item"><div class="legend-dot" style="background: #F0FDF4; border: 1px solid #22C55E;"></div> Best Match / Exact Item</div>
                <div class="legend-item"><div class="legend-dot" style="background: #FEF3C7; border: 1px solid #D97706;"></div> Alternative Option</div>
                <div class="legend-item"><div class="legend-dot" style="background: #FEF2F2; border: 1px solid #EF4444;"></div> Missing / Extra Item Not Quoted</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        matrix_rows = []
        row_styles = []

        for row in report.rows:
            sku_display = row.requested_sku if row.requested_sku else "Description Only"
            row_data = {
                "Line": row.line_number,
                "BOM Item": sku_display,
                "Requirement Description": row.requested_description,
                "Quantity": f"{row.requested_quantity:g} {row.unit_of_measure or ''}",
            }

            row_status = "identical"
            for doc_id, v_name in report.doc_metadata.items():
                offer = row.vendor_offers.get(doc_id)
                is_winner = (doc_id == row.recommended_doc_id) and (offer is not None)

                if offer:
                    best_label = "[Best Choice] " if is_winner else ""
                    status_tag = "Exact Match" if offer.verdict == MatchVerdict.IDENTICAL else "Alternative"
                    row_data[f"{v_name}"] = f"{best_label}{format_currency(offer.total_price, offer.currency)} ({status_tag} @ {format_currency(offer.unit_price, offer.currency)}/ea)"
                    if offer.verdict != MatchVerdict.IDENTICAL:
                        row_status = "substitute"
                else:
                    row_data[f"{v_name}"] = "Not Quoted (Missing)"
                    row_status = "missing"

            row_data["Recommended Winner"] = f"{row.recommended_vendor_name or 'None'} (Savings: {format_currency(row.potential_total_savings, report.currency)})"
            matrix_rows.append(row_data)
            row_styles.append(row_status)

        matrix_df = pd.DataFrame(matrix_rows)

        def color_entire_row(s):
            status = row_styles[s.name]
            if status == "identical":
                return ["background-color: #F0FDF4; color: #0F172A;"] * len(s)
            elif status == "substitute":
                return ["background-color: #FEF3C7; color: #0F172A;"] * len(s)
            else:
                return ["background-color: #FEF2F2; color: #991B1B;"] * len(s)

        styled_df = matrix_df.style.apply(color_entire_row, axis=1)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # Extra / Scope Creep Section
        st.markdown("#### Extra Unrequested Items (Scope Creep)")
        creep_found = False
        for doc_id, extras in report.unsolicited_items_by_doc_id.items():
            v_name = report.doc_metadata.get(doc_id, doc_id)
            if extras:
                creep_found = True
                st.warning(f"{v_name} added {len(extras)} extra unrequested item(s) totaling {format_currency(report.unsolicited_spend_by_doc_id[doc_id], report.currency)}.")
                extra_items_df = pd.DataFrame([
                    {"SKU": ex.product_id or "—", "Title": ex.product_name or ex.description_and_specs, "Qty": ex.quantity, "Total": format_currency(ex.total_price, report.currency)}
                    for ex in extras
                ])
                st.dataframe(extra_items_df, use_container_width=True, hide_index=True)
        if not creep_found:
            st.success("All vendor quotes match the required list with zero extra unrequested charges.")

    with tab_audit:
        st.markdown("#### Vendor Quote Audit & Totals")
        sel_doc = st.selectbox("Select Vendor Quote:", options=list(report.doc_metadata.keys()), format_func=lambda d: report.doc_metadata[d])
        target_quote = next(q for q in vendor_reconciliations if q.doc_id == sel_doc)

        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Reported Grand Total", format_currency(target_quote.reported_grand_total, target_quote.currency))
        with col_b:
            st.metric("Math Status", "Verified" if target_quote.is_reconciled else "Variance Detected")

        items_df = pd.DataFrame([
            {
                "SKU": i.product_id or "—",
                "Name": i.product_name or "—",
                "Quantity": i.quantity,
                "Unit Price": format_currency(i.unit_price, target_quote.currency),
                "Total Price": format_currency(i.total_price, target_quote.currency),
            }
            for i in target_quote.items
        ])
        st.dataframe(items_df, use_container_width=True, hide_index=True)

    with tab_json:
        st.json(report.model_dump())