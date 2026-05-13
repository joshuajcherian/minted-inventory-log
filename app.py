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
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Brand styling (primary green #1B733D · deep #0E1B14 · gold #E8C547) ---

BRAND_PRIMARY = "#1B733D"
DEEP_GREEN = "#0E1B14"
ACCENT_GOLD = "#E8C547"
MINT_SOFT = "#EEF4F0"
SAGE_BORDER = "#B8C9C0"
CARD_MINT = "#F4F9F6"

st.markdown(
    f"""
    <style>
      .stApp {{
        background:
          radial-gradient(ellipse 80% 50% at 50% -10%, rgba(27, 115, 61, 0.08) 0%, transparent 55%),
          linear-gradient(180deg, #FAFBFA 0%, #FFFFFF 35%);
      }}

      .block-container {{
        max-width: 820px;
        padding-top: 1.75rem;
        padding-bottom: 3rem;
        margin: 0 auto;
      }}

      header[data-testid="stHeader"] {{ background: transparent; }}

      .minted-header {{
        background: linear-gradient(145deg, {DEEP_GREEN} 0%, #122018 55%, #0d1812 100%);
        color: white;
        padding: 22px 26px;
        border-radius: 16px;
        margin-bottom: 24px;
        border: 1px solid rgba(232, 197, 71, 0.35);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.06) inset,
          0 20px 50px -24px rgba(0, 0, 0, 0.5);
      }}
      .minted-header-inner {{
        display: flex;
        align-items: center;
        gap: 22px;
        flex-wrap: wrap;
      }}
      .minted-header-logo {{
        display: block;
        max-height: 48px;
        width: auto;
        flex-shrink: 0;
      }}
      .minted-header-text {{ flex: 1 1 240px; min-width: 0; }}
      .minted-header h1 {{
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
        font-size: 1.5rem;
        font-weight: 800;
        margin: 0 0 6px;
        letter-spacing: -0.03em;
        line-height: 1.2;
        color: #fff;
      }}
      .minted-header p {{
        font-family: 'DM Sans', 'Segoe UI', system-ui, sans-serif;
        font-size: 0.95rem;
        font-weight: 500;
        margin: 0;
        color: rgba(255, 255, 255, 0.82);
        line-height: 1.45;
      }}
      .minted-header p span {{
        color: {ACCENT_GOLD};
        font-weight: 600;
      }}

      .lede {{
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 1rem;
        color: {DEEP_GREEN};
        margin: 0 0 6px;
        font-weight: 600;
      }}
      .sublede {{
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.9rem;
        color: #4a5c54;
        margin: 0 0 18px;
        line-height: 1.5;
      }}

      .panel {{
        background: linear-gradient(180deg, {CARD_MINT} 0%, #FFFFFF 100%);
        border: 1px solid {SAGE_BORDER};
        border-radius: 16px;
        padding: 22px 24px 24px;
        margin-bottom: 20px;
        box-shadow: 0 4px 24px -8px rgba(14, 27, 20, 0.12);
      }}
      .panel-topline {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
      }}
      .panel-badge {{
        background: {BRAND_PRIMARY};
        color: #fff;
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.06em;
        padding: 5px 10px;
        border-radius: 6px;
      }}
      .panel h2 {{
        font-family: 'Inter', system-ui, sans-serif;
        font-size: 1.15rem;
        font-weight: 700;
        color: {DEEP_GREEN};
        margin: 0;
        letter-spacing: -0.02em;
      }}
      .panel p {{
        font-family: 'DM Sans', system-ui, sans-serif;
        color: #2d3d35;
        font-size: 0.92rem;
        margin: 0 0 12px;
        line-height: 1.55;
      }}

      .step-card {{
        background: #FFFFFF;
        border: 1px solid {SAGE_BORDER};
        border-radius: 12px;
        padding: 18px 20px;
        margin-bottom: 16px;
        box-shadow: 0 2px 8px rgba(14, 27, 20, 0.04);
      }}
      .step-card h3 {{
        font-family: 'Inter', system-ui, sans-serif;
        color: {DEEP_GREEN};
        font-size: 1rem;
        font-weight: 700;
        margin: 0 0 8px;
      }}
      .step-card p, .step-card li {{
        font-family: 'DM Sans', system-ui, sans-serif;
        color: #1A1A1A;
        font-size: 0.9rem;
        line-height: 1.6;
        margin: 0;
      }}

      div[data-testid="stFileUploader"] {{
        margin-top: 4px;
      }}
      div[data-testid="stFileUploader"] section {{
        background: #FFFFFF !important;
        border: 2px dashed {BRAND_PRIMARY} !important;
        border-radius: 12px !important;
        padding: 28px 20px !important;
        min-height: 120px;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
      }}
      div[data-testid="stFileUploader"] section:hover {{
        border-color: {ACCENT_GOLD} !important;
        box-shadow: 0 0 0 3px rgba(232, 197, 71, 0.15);
      }}

      div[data-testid="stExpander"] {{
        background: #FFFFFF;
        border: 1px solid {SAGE_BORDER};
        border-radius: 14px;
        margin-bottom: 18px;
        box-shadow: 0 2px 10px rgba(14, 27, 20, 0.04);
        overflow: hidden;
      }}
      div[data-testid="stExpander"] details {{
        border: none !important;
      }}
      div[data-testid="stExpander"] summary {{
        font-family: 'Inter', system-ui, sans-serif !important;
        font-weight: 600 !important;
        color: {DEEP_GREEN} !important;
        padding: 14px 18px !important;
      }}
      div[data-testid="stExpander"] summary:hover {{
        background: {MINT_SOFT} !important;
      }}

      div.stButton > button[kind="primary"],
      div.stDownloadButton > button {{
        background: {BRAND_PRIMARY} !important;
        color: #FFFFFF !important;
        border: 0 !important;
        border-radius: 12px !important;
        padding: 14px 22px !important;
        font-family: 'Inter', system-ui, sans-serif !important;
        font-weight: 700 !important;
        font-size: 1.02rem !important;
        box-shadow: 0 10px 28px -12px rgba(27, 115, 61, 0.55) !important;
        transition: transform 0.15s ease, box-shadow 0.15s ease !important;
      }}
      div.stButton > button[kind="primary"]:hover,
      div.stDownloadButton > button:hover {{
        transform: translateY(-2px);
        background: #156b3a !important;
        color: #fff !important;
        box-shadow: 0 16px 36px -14px rgba(14, 27, 20, 0.35) !important;
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
        font-size: 1.65rem;
        font-weight: 800;
        line-height: 1;
      }}
      .stat-tile.alt {{
        background: {BRAND_PRIMARY};
        color: #FFFFFF;
      }}
      .stat-tile.alt .label {{ color: {ACCENT_GOLD}; }}

      div[data-testid="stProgressBar"] > div > div > div {{
        background-color: {BRAND_PRIMARY} !important;
      }}

      .footer {{
        margin-top: 32px;
        text-align: center;
        font-family: 'DM Sans', system-ui, sans-serif;
        font-size: 0.76rem;
        color: #6B7B73;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Header ---------------------------------------------------------------

_logo_uri = _header_logo_data_uri()
_logo_html = (
    f'<img src="{_logo_uri}" class="minted-header-logo" alt="" />'
    if _logo_uri
    else ""
)
st.markdown(
    f"""
    <div class="minted-header">
      <div class="minted-header-inner">
        {_logo_html}
        <div class="minted-header-text">
          <h1>Inventory Log Generator</h1>
          <p>Your Shopify export becomes a <span>Minted</span> workbook for counting singles, sealed, and discrepancies.</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <p class="lede">Ready when your CSV arrives from Shopify</p>
    <p class="sublede">Upload the file below, set your store name and date, then build. Full export steps stay in the collapsible section if anyone needs them.</p>
    """,
    unsafe_allow_html=True,
)


# --- Shopify steps (collapsed so upload isn’t buried) ---------------------

with st.expander("How to export from Shopify (email usually arrives in ~5 minutes)", expanded=False):
    st.markdown(
        """
1. **Shopify Admin** → **Products** → **Inventory**.
2. Top left, next to **Inventory**, open the **location** dropdown and pick the store.
3. Click **Export**.
4. In the options, choose **All states** or **Export inventory from your location** — whichever matches that location.
5. **Inventory state shown** → **All states**.
6. Enable **Export all variants**.
7. Format → **CSV for Excel, Numbers, or other spreadsheet programs**.
8. **Export** again. When the email arrives, download the CSV and use it here.
        """
    )


# --- Main action panel: upload ------------------------------------------

st.markdown(
    """
    <div class="panel">
      <div class="panel-topline">
        <span class="panel-badge">STEP 1</span>
        <h2>Upload your inventory CSV</h2>
      </div>
      <p>Drag and drop here, or browse. This should be the file from Shopify’s email (often named <code style="background:#EEF4F0;padding:2px 6px;border-radius:4px;font-size:0.88em;">inventory_export…</code>).</p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "CSV from Shopify",
    type=["csv"],
    label_visibility="collapsed",
)


# Defaults for download file naming
if "inv_export_location" not in st.session_state:
    st.session_state["inv_export_location"] = ""
if "inv_export_date" not in st.session_state:
    st.session_state["inv_export_date"] = date.today()

show_naming = uploaded is not None or "xlsx_bytes" in st.session_state

if show_naming:
    st.markdown(
        f"""
        <div class="panel" style="margin-top: -8px;">
          <div class="panel-topline">
            <span class="panel-badge">STEP 2</span>
            <h2>Name your download</h2>
          </div>
          <p>File name pattern:
            <code style="background:{MINT_SOFT};padding:2px 8px;border-radius:4px;font-size:0.88em;">StoreName_YYYY-MM-DD_Daily_Inventory_Log.xlsx</code>
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input(
        "Store / location name",
        placeholder="e.g. Dacula · Lawrenceville",
        key="inv_export_location",
        help="Required before building. Special characters become underscores.",
    )
    st.date_input(
        "Date on the file",
        key="inv_export_date",
        help="Usually today, or the day of the count.",
    )


# --- Build ----------------------------------------------------------------

def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


if uploaded is not None:
    st.markdown(
        f"""
        <div class="panel" style="border-left: 4px solid {BRAND_PRIMARY};">
          <div class="panel-topline">
            <span class="panel-badge">STEP 3</span>
            <h2>Build workbook</h2>
          </div>
          <p><strong>{uploaded.name}</strong> · {_human_size(uploaded.size)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Build inventory workbook", type="primary", use_container_width=True):
        if not st.session_state.get("inv_export_location", "").strip():
            st.warning("Add your **store / location name** (Step 2) before building.")
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
                status_el.caption("Done — download below.")
            except InvalidShopifyCsv as e:
                progress_bar.empty()
                status_el.empty()
                st.session_state.pop("xlsx_bytes", None)
                st.error("That file doesn’t look like a Shopify inventory export.")
                st.markdown(str(e).replace("\n", "  \n"))
            except Exception as e:  # noqa: BLE001
                progress_bar.empty()
                status_el.empty()
                st.session_state.pop("xlsx_bytes", None)
                st.error(f"Build failed: {e}")
                with st.expander("Technical details"):
                    st.code(traceback.format_exc(), language="text")


# --- Download -------------------------------------------------------------

if "xlsx_bytes" in st.session_state:
    summary = st.session_state.get("summary", {})
    total = summary.get("total", 0)
    singles = summary.get("singles_stocked", 0)
    sealed = summary.get("sealed_stocked", 0)
    built_at = st.session_state.get("built_at", datetime.now())

    st.markdown(
        f"""
        <div class="panel" style="border-left: 4px solid {ACCENT_GOLD};">
          <div class="panel-topline">
            <span class="panel-badge" style="background:{ACCENT_GOLD};color:{DEEP_GREEN};">DONE</span>
            <h2>Download</h2>
          </div>
          <p>Built {built_at:%b %d, %Y · %I:%M %p}</p>
          <div class="stat-grid">
            <div class="stat-tile"><div class="label">Total SKUs</div><div class="value">{total:,}</div></div>
            <div class="stat-tile alt"><div class="label">Singles stocked</div><div class="value">{singles:,}</div></div>
            <div class="stat-tile alt"><div class="label">Sealed stocked</div><div class="value">{sealed:,}</div></div>
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
    st.caption(f"File name: `{filename}`")
    st.download_button(
        label="Download workbook",
        data=st.session_state["xlsx_bytes"],
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# --- Footer ---------------------------------------------------------------

st.markdown(
    f"""
    <div class="footer">
      Minted TCG · Internal tool · {datetime.now():%B %Y}
    </div>
    """,
    unsafe_allow_html=True,
)
