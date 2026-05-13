"""
Minted — Inventory Log Web App.

Upload a Shopify inventory export CSV, click Build, download the Minted-branded
inventory log workbook.

Run locally:
    streamlit run app.py

Deploy publicly (free):
    Push this repo to GitHub, then create an app at
    https://streamlit.io/cloud pointing at app.py.
"""

from __future__ import annotations

import io
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

import streamlit as st

from build_inventory_log import (
    InvalidShopifyCsv,
    build_workbook,
    validate_shopify_csv,
)


# --- Page setup -----------------------------------------------------------

st.set_page_config(
    page_title="Minted — Inventory Log Generator",
    page_icon="🌿",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- Brand styling --------------------------------------------------------

MINT = "#6AB799"
DEEP_GREEN = "#0D271D"
NEON = "#44FFB7"
MINT_SOFT = "#E6F2EC"

st.markdown(
    f"""
    <style>
      .stApp {{
        background:
          radial-gradient(ellipse at 50% 0%, rgba(106,183,153,0.18) 0%, transparent 55%),
          #FFFFFF;
      }}

      .block-container {{
        max-width: 760px;
        padding-top: 2.5rem;
        padding-bottom: 4rem;
      }}

      .minted-header {{
        background: {DEEP_GREEN};
        color: white;
        padding: 28px 32px;
        border-radius: 14px;
        margin-bottom: 28px;
        border-bottom: 4px solid {NEON};
        box-shadow: 0 24px 50px -20px rgba(13,39,29,0.35);
      }}
      .minted-header h1 {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 2.0rem;
        font-weight: 800;
        margin: 0 0 6px;
        letter-spacing: -0.01em;
        color: #fff;
      }}
      .minted-header p {{
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.95rem;
        font-weight: 600;
        margin: 0;
        color: {NEON};
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }}

      .step-card {{
        background: white;
        border: 1px solid #D8E5DE;
        border-radius: 12px;
        padding: 22px 24px;
        margin-bottom: 18px;
        box-shadow: 0 2px 10px rgba(13,39,29,0.04);
      }}
      .step-card h3 {{
        font-family: 'Inter', system-ui, sans-serif;
        color: {DEEP_GREEN};
        font-size: 1.05rem;
        font-weight: 700;
        margin: 0 0 8px;
        letter-spacing: -0.01em;
      }}
      .step-card p {{
        font-family: 'DM Sans', system-ui, sans-serif;
        color: #1A1A1A;
        font-size: 0.92rem;
        margin: 0;
      }}

      div[data-testid="stFileUploader"] section {{
        background: {MINT_SOFT};
        border: 2px dashed {MINT};
        border-radius: 12px;
        padding: 20px;
      }}

      /* Primary button styling */
      div.stButton > button[kind="primary"],
      div.stDownloadButton > button {{
        background: {DEEP_GREEN};
        color: {NEON};
        border: 0;
        border-radius: 10px;
        padding: 12px 22px;
        font-family: 'Inter', system-ui, sans-serif;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: 0.02em;
        box-shadow: 0 12px 30px -10px rgba(13,39,29,0.35);
        transition: transform 120ms ease, box-shadow 120ms ease;
      }}
      div.stButton > button[kind="primary"]:hover,
      div.stDownloadButton > button:hover {{
        transform: translateY(-1px);
        background: {DEEP_GREEN};
        color: #fff;
        box-shadow: 0 18px 40px -12px rgba(13,39,29,0.45);
      }}

      .stat-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-top: 14px;
      }}
      .stat-tile {{
        background: {DEEP_GREEN};
        color: #fff;
        border-radius: 12px;
        padding: 14px 16px;
        text-align: center;
      }}
      .stat-tile .label {{
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: {NEON};
        margin-bottom: 6px;
      }}
      .stat-tile .value {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 1.7rem;
        font-weight: 800;
        line-height: 1;
      }}
      .stat-tile.alt {{
        background: {MINT};
        color: {DEEP_GREEN};
      }}
      .stat-tile.alt .label {{ color: {DEEP_GREEN}; }}

      .footer {{
        margin-top: 36px;
        text-align: center;
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.78rem;
        color: #6B7B73;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Header ---------------------------------------------------------------

st.markdown(
    """
    <div class="minted-header">
      <h1>Minted — Inventory Log Generator</h1>
      <p>Drop a Shopify export · Get a branded count workbook</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Step 1: Instructions -------------------------------------------------

st.markdown(
    """
    <div class="step-card">
      <h3>1. Export your inventory from Shopify</h3>
      <p>Shopify Admin → <b>Products → Inventory</b> → click <b>Export</b> →
         choose <i>CSV for Excel, Numbers or other spreadsheet programs</i>.
         Save the CSV anywhere on your computer.</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Step 2: Upload -------------------------------------------------------

st.markdown(
    """
    <div class="step-card">
      <h3>2. Upload the CSV below</h3>
      <p>You can drag it from Finder/Explorer right into the box.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Drop your inventory_export*.csv here",
    type=["csv"],
    label_visibility="collapsed",
)


# --- Step 3: Build --------------------------------------------------------

def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


if uploaded is not None:
    st.markdown(
        f"""
        <div class="step-card" style="border-left: 4px solid {MINT};">
          <h3>3. Build the inventory log</h3>
          <p><b>{uploaded.name}</b> · {_human_size(uploaded.size)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Build Inventory Log", type="primary", use_container_width=True):
        with st.spinner("Crunching SKUs and assembling the workbook…"):
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_csv = Path(tmpdir) / "input.csv"
                    tmp_xlsx = Path(tmpdir) / "Minted_Inventory_Log.xlsx"

                    tmp_csv.write_bytes(uploaded.getvalue())

                    # Validate up front so we can show a clear, friendly error
                    # instead of an openpyxl traceback.
                    validate_shopify_csv(tmp_csv)

                    summary = build_workbook(tmp_csv, tmp_xlsx)
                    xlsx_bytes = tmp_xlsx.read_bytes()

                st.session_state["xlsx_bytes"] = xlsx_bytes
                st.session_state["summary"] = summary
                st.session_state["built_at"] = datetime.now()
            except InvalidShopifyCsv as e:
                st.session_state.pop("xlsx_bytes", None)
                st.error("⚠️  Wrong file type")
                st.markdown(str(e).replace("\n", "  \n"))
            except Exception as e:  # noqa: BLE001 — surface anything else to the user
                st.session_state.pop("xlsx_bytes", None)
                st.error(f"Build failed: {e}")
                with st.expander("Technical details"):
                    st.code(traceback.format_exc(), language="text")


# --- Step 4: Download -----------------------------------------------------

if "xlsx_bytes" in st.session_state:
    summary = st.session_state.get("summary", {})
    total = summary.get("total", 0)
    singles = summary.get("singles_stocked", 0)
    sealed = summary.get("sealed_stocked", 0)
    built_at = st.session_state.get("built_at", datetime.now())

    st.markdown(
        f"""
        <div class="step-card" style="border-left: 4px solid {NEON};">
          <h3>4. Download &amp; share</h3>
          <p>Built {built_at:%b %d, %Y · %I:%M %p}</p>
          <div class="stat-grid">
            <div class="stat-tile"><div class="label">Total SKUs</div><div class="value">{total:,}</div></div>
            <div class="stat-tile alt"><div class="label">Singles Stocked</div><div class="value">{singles:,}</div></div>
            <div class="stat-tile alt"><div class="label">Sealed Stocked</div><div class="value">{sealed:,}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    filename = f"Minted_Inventory_Log_{built_at:%Y-%m-%d}.xlsx"
    st.download_button(
        label="⬇  Download Minted Inventory Log",
        data=st.session_state["xlsx_bytes"],
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# --- Footer ---------------------------------------------------------------

st.markdown(
    f"""
    <div class="footer">
      Minted TCG · Internal tool · Built on {datetime.now():%B %Y}
    </div>
    """,
    unsafe_allow_html=True,
)
