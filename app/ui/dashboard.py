"""Executive Procurement Cross-Vendor Match & Coverage Dashboard."""

from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import streamlit as st
import tempfile

from app.clients.ollama_client import OllamaClient
from app.schemas.comparison_schema import MatchVerdict, MultiVendorComparisonReport
from app.src.classifier import Classification
from app.src.comparator import QuoteComparator
from app.src.extractor import Extraction
from app.ingestion.pdf_parser import PDFIngestion
from app.ingestion.excel_parser import ExcelIngestion
from app.core.config import get_settings
from app.core.prompts import (
    CLIENT_BOM_EXTRACTION_SYSTEM_PROMPT,
    CLIENT_BOM_EXTRACTION_USER_CONTENT,
)
from app.schemas.page_extraction_schema import ClientBOMPayload

settings = get_settings()

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


@st.cache_resource
def get_services():
    llm = OllamaClient(model=settings.CLASSIFIER_MODEL)
    classifier = Classification(llm_client=llm)
    extractor = Extraction(llm_client=llm)
    return classifier, extractor


classifier, extractor = get_services()


with st.sidebar:
    st.markdown("### Document Ingestion")
    st.caption("Upload Client BOM and Vendor Quote files.")
    st.divider()

    client_file = st.file_uploader(
        "Client BOM (PDF, Excel, or Image)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"]
    )
    vendor_files = st.file_uploader(
        "Vendor Quotations (PDF, Excel, or Image)",
        type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
    )

    st.divider()
    run_btn = st.button("Run Comparison Pipeline", type="primary", width="stretch")

st.markdown('<div class="main-title">QuoMatch Intelligence Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Cross-Vendor Requirement Verification & Specification Mapping</div>', unsafe_allow_html=True)


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

    with st.spinner("Processing documents through VLM extraction & multi-tier matching..."):
        try:
            # 1. Parse Client BOM
            client_bom: List[Dict[str, Any]] = []

            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(client_file.name).suffix) as tmp_client:
                tmp_client.write(client_file.getbuffer())
                client_tmp_path = tmp_client.name

            try:
                file_ext = Path(client_file.name).suffix.lower()
                user_content = CLIENT_BOM_EXTRACTION_USER_CONTENT
                images = None

                if file_ext == ".pdf":
                    raw_images = PDFIngestion.pdf_to_pil_images(client_tmp_path)
                    images = [PDFIngestion.compress_image_to_bytes(img) for img in raw_images]
                elif file_ext in [".png", ".jpg", ".jpeg"]:
                    from PIL import Image as PILImage
                    img = PILImage.open(client_tmp_path)
                    images = [PDFIngestion.compress_image_to_bytes(img)]
                else:
                    markdown_grid = ExcelIngestion.convert_excel_to_markdown(client_tmp_path)
                    user_content = f"{CLIENT_BOM_EXTRACTION_USER_CONTENT}\n\nClient BOM Table:\n{markdown_grid}"

                client_payload: ClientBOMPayload = classifier.llm_client.generate_response(
                    system_prompt=CLIENT_BOM_EXTRACTION_SYSTEM_PROMPT,
                    user_content=user_content,
                    response_schema=ClientBOMPayload,
                    images=images,
                )

                for item in client_payload.items:
                    raw_sku = (item.sku or "").strip()
                    raw_desc = (item.description or "").strip()
                    if " " in raw_sku or len(raw_sku) > 25:
                        if not raw_desc:
                            raw_desc = raw_sku
                        raw_sku = None

                    client_bom.append({
                        "product_id": raw_sku if raw_sku else None,
                        "description": raw_desc,
                        "quantity": item.quantity,
                        "unit_of_measure": item.unit_of_measure,
                    })
            finally:
                Path(client_tmp_path).unlink(missing_ok=True)

            # 2. Parse Vendor Quote Files
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
                llm_client=classifier.llm_client,
            )

        except Exception as e:
            st.error(f"Pipeline execution failed: {e}")
            st.exception(e)
            st.stop()

    # --- TOP KPIS: REQUIREMENT FULFILLMENT AUDIT ---
    total_reqs = report.total_requested_items
    covered_reqs = sum(1 for r in report.rows if any(o is not None for o in r.vendor_offers.values()))
    uncovered_reqs = total_reqs - covered_reqs
    coverage_pct = (covered_reqs / total_reqs * 100) if total_reqs else 0.0

    total_extra_spend = sum(report.unsolicited_spend_by_doc_id.values())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Client Requirements", f"{total_reqs} Items")
    c2.metric("Requirements Covered", f"{covered_reqs} / {total_reqs}", f"{coverage_pct:.0f}%")
    c3.metric("Uncovered Items", f"{uncovered_reqs} Items", delta="-Missing" if uncovered_reqs > 0 else "Complete", delta_color="inverse")
    c4.metric("Scope Creep Charges", format_currency(total_extra_spend, report.currency))

    st.divider()

    tab_matrix, tab_audit, tab_json = st.tabs(["Comparison Matrix", "Vendor Breakdown", "Raw JSON Data"])

    with tab_matrix:
        st.markdown("#### Requirement Match & Availability Matrix")
        st.caption("Direct cross-vendor line item verification against client requirements.")

        st.markdown(
            """
            <div class="legend-box">
                <div class="legend-item"><div class="legend-dot" style="background: #F0FDF4; border: 1px solid #22C55E;"></div> Item Covered (Exact or Compatible Match)</div>
                <div class="legend-item"><div class="legend-dot" style="background: #FEF2F2; border: 1px solid #EF4444;"></div> Item Missing Across All Quotes</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        matrix_rows = []
        row_status_list = []

        for row in report.rows:
            row_data = {
                "Line": row.line_number,
                "Client Requirement": row.requested_description,
                "Required Qty": f"{row.requested_quantity:g} {row.unit_of_measure or ''}".strip(),
            }

            matched_vendors = []
            has_match = False

            for doc_id, v_name in report.doc_metadata.items():
                offer = row.vendor_offers.get(doc_id)
                if offer:
                    has_match = True
                    matched_vendors.append(v_name)
                    tag = "Exact" if offer.verdict == MatchVerdict.IDENTICAL else "Compatible"
                    sku_prefix = f"[{offer.matched_product_id}] " if offer.matched_product_id else ""
                    row_data[v_name] = f"Matched ({tag}) | {sku_prefix}{format_currency(offer.total_price, offer.currency)} (@ {format_currency(offer.unit_price, offer.currency)}/ea)"
                else:
                    row_data[v_name] = "— Not Quoted —"

            row_data["Matched Vendor(s)"] = ", ".join(matched_vendors) if matched_vendors else "None (Unquoted)"
            matrix_rows.append(row_data)
            row_status_list.append("covered" if has_match else "uncovered")

        matrix_df = pd.DataFrame(matrix_rows)

        def style_rows(s):
            status = row_status_list[s.name]
            if status == "covered":
                return ["background-color: #F0FDF4; color: #0F172A;"] * len(s)
            else:
                return ["background-color: #FEF2F2; color: #991B1B;"] * len(s)

        styled_df = matrix_df.style.apply(style_rows, axis=1)
        st.dataframe(styled_df, width="stretch", hide_index=True)

        st.markdown("#### Extra Unrequested Items (Scope Creep)")
        creep_found = False
        for doc_id, extras in report.unsolicited_items_by_doc_id.items():
            v_name = report.doc_metadata.get(doc_id, doc_id)
            if extras:
                creep_found = True
                st.warning(f"{v_name} added {len(extras)} extra unrequested item(s) totaling {format_currency(report.unsolicited_spend_by_doc_id[doc_id], report.currency)}.")
                extra_items_df = pd.DataFrame([
                    {
                        "SKU": ex.product_id or "—",
                        "Title": ex.product_name or ex.description_and_specs,
                        "Qty": ex.quantity,
                        "Total": format_currency(ex.total_price, report.currency),
                    }
                    for ex in extras
                ])
                st.dataframe(extra_items_df, width="stretch", hide_index=True)
        if not creep_found:
            st.success("All vendor quotes match the required list with zero extra unrequested charges.")

    with tab_audit:
        st.markdown("#### Vendor Quote Audit & Totals")
        sel_doc = st.selectbox(
            "Select Vendor Quote:",
            options=list(report.doc_metadata.keys()),
            format_func=lambda d: report.doc_metadata[d],
        )
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
        st.dataframe(items_df, width="stretch", hide_index=True)

    with tab_json:
        st.json(report.model_dump())