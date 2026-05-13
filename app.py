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

import base64
import tempfile
import traceback
from datetime import date, datetime
from pathlib import Path

import streamlit as st

from build_inventory_log import (
    InvalidShopifyCsv,
    build_inventory_download_filename,
    build_workbook,
)


APP_ROOT = Path(__file__).resolve().parent


def _header_logo_data_uri() -> str | None:
    """White + gold horizontal logo for the dark hero bar."""
    path = APP_ROOT / "assets" / "branding" / "logo_horizontal_white_yellow.png"
    if not path.exists():
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# --- Page setup -----------------------------------------------------------

st.set_page_config(
    page_title="Minted TCG — Inventory Log",
    page_icon="🎴",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- Brand styling (primary green #1B733D · deep #0E1B14 · gold #E8C547) ---

BRAND_PRIMARY = "#1B733D"
DEEP_GREEN = "#0E1B14"
ACCENT_GOLD = "#E8C547"
MINT_SOFT = "#EEF4F0"
SAGE_BORDER = "#B8C9C0"

st.markdown(
    f"""
    <style>
      .stApp {{
        background:
          radial-gradient(ellipse at 50% 0%, rgba(27, 115, 61, 0.12) 0%, transparent 52%),
          #FFFFFF;
      }}

      .block-container {{
        max-width: 760px;
        padding-top: 2.5rem;
        padding-bottom: 4rem;
      }}

      .minted-header {{
        background: linear-gradient(165deg, {DEEP_GREEN} 0%, #152922 100%);
        color: white;
        padding: 26px 28px 28px;
        border-radius: 14px;
        margin-bottom: 28px;
        border-bottom: 4px solid {ACCENT_GOLD};
        box-shadow: 0 24px 48px -18px rgba(14, 27, 20, 0.45);
      }}
      .minted-header-logo {{
        display: block;
        max-height: 52px;
        width: auto;
        margin-bottom: 16px;
      }}
      .minted-header h1 {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 1.45rem;
        font-weight: 800;
        margin: 0 0 8px;
        letter-spacing: -0.02em;
        color: #fff;
      }}
      .minted-header p {{
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.9rem;
        font-weight: 600;
        margin: 0;
        color: {ACCENT_GOLD};
        letter-spacing: 0.05em;
        text-transform: uppercase;
      }}

      .step-card {{
        background: white;
        border: 1px solid {SAGE_BORDER};
        border-radius: 12px;
        padding: 22px 24px;
        margin-bottom: 18px;
        box-shadow: 0 2px 10px rgba(14, 27, 20, 0.06);
      }}
      .step-card h3 {{
        font-family: 'Inter', system-ui, sans-serif;
        color: {DEEP_GREEN};
        font-size: 1.05rem;
        font-weight: 700;
        margin: 0 0 8px;
        letter-spacing: -0.01em;
      }}
      .step-card p, .step-card li {{
        font-family: 'DM Sans', system-ui, sans-serif;
        color: #1A1A1A;
        font-size: 0.92rem;
        margin: 0;
      }}

      div[data-testid="stFileUploader"] section {{
        background: {MINT_SOFT};
        border: 2px dashed {BRAND_PRIMARY};
        border-radius: 12px;
        padding: 20px;
      }}

      div.stButton > button[kind="primary"],
      div.stDownloadButton > button {{
        background: {BRAND_PRIMARY};
        color: #FFFFFF;
        border: 0;
        border-radius: 10px;
        padding: 12px 22px;
        font-family: 'Inter', system-ui, sans-serif;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: 0.02em;
        box-shadow: 0 12px 28px -10px rgba(27, 115, 61, 0.45);
        transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease;
      }}
      div.stButton > button[kind="primary"]:hover,
      div.stDownloadButton > button:hover {{
        transform: translateY(-1px);
        background: #155a31;
        color: {ACCENT_GOLD};
        box-shadow: 0 18px 40px -12px rgba(14, 27, 20, 0.35);
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
        color: {ACCENT_GOLD};
        margin-bottom: 6px;
      }}
      .stat-tile .value {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 1.7rem;
        font-weight: 800;
        line-height: 1;
      }}
      .stat-tile.alt {{
        background: {BRAND_PRIMARY};
        color: #FFFFFF;
      }}
      .stat-tile.alt .label {{ color: {ACCENT_GOLD}; }}

      div[data-testid="stProgressBar"] > div {{
        background-color: {BRAND_PRIMARY} !important;
      }}

      .footer {{
        margin-top: 36px;
        text-align: center;
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.78rem;
        color: #5A6B63;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Header ---------------------------------------------------------------

_logo_uri = _header_logo_data_uri()
_logo_html = (
    f'<img src="{_logo_uri}" class="minted-header-logo" alt="Minted TCG" />'
    if _logo_uri
    else ""
)
st.markdown(
    f"""
    <div class="minted-header">
      {_logo_html}
      <h1>Inventory Log Generator</h1>
      <p>Shopify inventory export → Minted count workbook</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Step 1: Instructions -------------------------------------------------

st.markdown(
    """
    <div class="step-card">
      <h3>1. Export inventory from Shopify</h3>
      <p style="margin-bottom:14px; color:#1A1A1A; font-size:0.95rem;">
        Follow these steps so the CSV matches what this tool expects.
      </p>
      <ol style="margin:0 0 0 1.1rem; padding:0; color:#1A1A1A; font-size:0.92rem; line-height:1.65;">
        <li style="margin-bottom:10px;">Open <b>Shopify Admin</b> → <b>Products</b> → <b>Inventory</b>.</li>
        <li style="margin-bottom:10px;">At the <b>top left</b>, next to <b>Inventory</b>, open the <b>location</b> dropdown and select the store you’re exporting for.</li>
        <li style="margin-bottom:10px;">Click <b>Export</b>.</li>
        <li style="margin-bottom:10px;">In the export options, choose the scope Shopify shows you — e.g. <b>All states</b> or <b>Export inventory from your location</b> — so it lines up with that location.</li>
        <li style="margin-bottom:10px;">For <b>Inventory state shown</b>, set it to <b>All states</b>.</li>
        <li style="margin-bottom:10px;">Choose <b>Export all variants</b>.</li>
        <li style="margin-bottom:10px;">Set the format to <b>CSV for Excel, Numbers, or other spreadsheet programs</b>.</li>
        <li style="margin-bottom:0;">Click <b>Export</b> again to start. Shopify <b>emails</b> you when the file is ready — usually within <b>about 5 minutes</b>. Download the CSV from that email, then upload it below.</li>
      </ol>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Step 2: Upload -------------------------------------------------------

st.markdown(
    """
    <div class="step-card">
      <h3>2. Upload the CSV below</h3>
      <p>You can drag the CSV from your desktop or Downloads — it’s usually the file Shopify emailed you.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Drop your inventory_export*.csv here",
    type=["csv"],
    label_visibility="collapsed",
)

# Defaults for download file naming (used once a file is uploaded or after a build).
if "inv_export_location" not in st.session_state:
    st.session_state["inv_export_location"] = ""
if "inv_export_date" not in st.session_state:
    st.session_state["inv_export_date"] = date.today()

show_naming = uploaded is not None or "xlsx_bytes" in st.session_state

if show_naming:
    st.markdown(
        f"""
        <div class="step-card" style="border-left: 3px solid {DEEP_GREEN};">
          <h3>Name your download</h3>
          <p>We’ll save the workbook as <b>Location</b> + <b>date</b> +
             <code style="font-size:0.85em;">_Daily_Inventory_Log.xlsx</code> — e.g.
             <code style="font-size:0.85em;">Dacula_2026-05-13_Daily_Inventory_Log.xlsx</code>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input(
        "Store / location name",
        placeholder="e.g. Dacula · Lawrenceville",
        key="inv_export_location",
        help="Required before building. Unsafe characters become underscores in the file name.",
    )
    st.date_input(
        "Date on the file",
        key="inv_export_date",
        help="Usually today, or the day of this count / export.",
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
        <div class="step-card" style="border-left: 4px solid {BRAND_PRIMARY};">
          <h3>3. Build the inventory log</h3>
          <p><b>{uploaded.name}</b> · {_human_size(uploaded.size)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Build Inventory Log", type="primary", use_container_width=True):
        if not st.session_state.get("inv_export_location", "").strip():
            st.warning("Enter a **store / location name** first — it’s part of the downloaded file name.")
        else:
            progress_bar = st.progress(0)
            status_el = st.empty()
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_csv = Path(tmpdir) / "input.csv"
                    tmp_xlsx = Path(tmpdir) / "Minted_Inventory_Log.xlsx"

                    tmp_csv.write_bytes(uploaded.getvalue())

                    def report(frac: float, msg: str) -> None:
                        progress_bar.progress(frac)
                        status_el.caption(msg)

                    summary = build_workbook(tmp_csv, tmp_xlsx, progress=report)
                    xlsx_bytes = tmp_xlsx.read_bytes()

                st.session_state["xlsx_bytes"] = xlsx_bytes
                st.session_state["summary"] = summary
                st.session_state["built_at"] = datetime.now()
                progress_bar.progress(1.0)
                status_el.caption("Done — scroll down to download your workbook.")
            except InvalidShopifyCsv as e:
                progress_bar.empty()
                status_el.empty()
                st.session_state.pop("xlsx_bytes", None)
                st.error("⚠️  Wrong file type")
                st.markdown(str(e).replace("\n", "  \n"))
            except Exception as e:  # noqa: BLE001 — surface anything else to the user
                progress_bar.empty()
                status_el.empty()
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
        <div class="step-card" style="border-left: 4px solid {ACCENT_GOLD};">
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

    loc_raw = st.session_state.get("inv_export_location", "").strip() or "Location_unknown"
    exp_date = st.session_state.get("inv_export_date", date.today())
    if isinstance(exp_date, datetime):
        exp_date = exp_date.date()
    if not isinstance(exp_date, date):
        exp_date = date.today()
    filename = build_inventory_download_filename(loc_raw, exp_date)
    st.caption(f"Download file: `{filename}`")
    st.download_button(
        label="⬇  Download workbook",
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
