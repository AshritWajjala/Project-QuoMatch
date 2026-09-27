# app.py
import tempfile
import pandas as pd
import streamlit as st
from src.extractor import extract_from_pdf
from src.matcher import MatchStatus, reconcile_quotes

st.set_page_config(page_title="QuoMatch - Discrepancy Engine", layout="wide")

st.title("📦 QuoMatch: Quotation Discrepancy Engine")
st.write("Upload a Client RFQ PDF and a Vendor Quotation PDF to detect quantity variances, missing items, or pricing discrepancies.")

col1, col2 = st.columns(2)

with col1:
    client_file = st.file_uploader("Upload Client RFQ (PDF)", type=["pdf"], key="rfq")

with col2:
    vendor_file = st.file_uploader("Upload Vendor Quotation (PDF)", type=["pdf"], key="quote")

if client_file and vendor_file:
    if st.button("Run Discrepancy Analysis", type="primary"):
        with st.spinner("Extracting layouts and running mathematical verification..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp1:
                tmp1.write(client_file.read())
                c_recon = extract_from_pdf(tmp1.name)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp2:
                tmp2.write(vendor_file.read())
                v_recon = extract_from_pdf(tmp2.name)

            diff_items = reconcile_quotes(c_recon.items, v_recon.items)

        st.success("Reconciliation Complete!")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Requested Lines", len(c_recon.items))
        m2.metric("Quoted Lines", len(v_recon.items))
        m3.metric("Vendor Subtotal", f"{v_recon.calculated_subtotal:,.2f}")
        m4.metric("Taxes / Surcharges", f"{v_recon.taxes_and_fees:,.2f}")

        df = pd.DataFrame([item.model_dump() for item in diff_items])

        def highlight_status(row):
            if row["status"] == MatchStatus.EXACT_MATCH:
                return ["background-color: #d4edda; color: #155724"] * len(row)
            elif row["status"] == MatchStatus.QTY_MISMATCH:
                return ["background-color: #fff3cd; color: #856404"] * len(row)
            elif row["status"] == MatchStatus.MISSING:
                return ["background-color: #f8d7da; color: #721c24"] * len(row)
            elif row["status"] == MatchStatus.EXTRA:
                return ["background-color: #d1ecf1; color: #0c5460"] * len(row)
            return [""] * len(row)

        styled_df = df.style.apply(highlight_status, axis=1)
        st.subheader("Comparison & Discrepancy Breakdown")
        st.dataframe(styled_df, use_container_width=True)