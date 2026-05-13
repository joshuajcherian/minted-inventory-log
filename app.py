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


def _logo_data_uri(filename: str) -> str | None:
    path = APP_ROOT / "assets" / "branding" / filename
    if not path.exists():
        return None
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _deployed_branch() -> str:
    """Read the git branch from the checkout's .git/HEAD. Streamlit Cloud
    clones the repo at deploy time and leaves .git/ in place, so this is a
    reliable signal of whether we're on main, dev, or anything else."""
    try:
        head = APP_ROOT / ".git" / "HEAD"
        if head.exists():
            content = head.read_text().strip()
            if content.startswith("ref: refs/heads/"):
                return content[len("ref: refs/heads/"):]
            return content[:8]  # detached HEAD — show short SHA
    except Exception:
        pass
    return ""


def _is_dev_environment() -> tuple[bool, str]:
    """Returns (is_dev, label). Layered signals so this works whether or
    not Streamlit Cloud exposes the Host header reliably."""
    # 1. Explicit override via Streamlit secrets (user can set ENVIRONMENT="dev").
    try:
        env = str(st.secrets.get("environment", "")).strip().lower()
        if env in ("dev", "development", "staging"):
            return True, f"DEV · {env}"
        if env in ("prod", "production"):
            return False, ""
    except Exception:
        pass

    # 2. Git branch from the deployed checkout.
    branch = _deployed_branch()
    if branch and branch.lower() not in ("main", "master", "prod", "production"):
        return True, f"DEV · {branch}"

    # 3. Local dev / unknown host fallback.
    try:
        host = (st.context.headers.get("Host", "") or "").lower()
    except Exception:
        host = ""
    if host.startswith(("localhost", "127.", "0.0.0.0")):
        return True, "LOCAL"
    if "-dev." in host or "dev-" in host or ".dev." in host:
        return True, "DEV"

    return False, ""


# --- Page setup -----------------------------------------------------------

# Detect environment BEFORE set_page_config so the browser tab title and
# favicon can reflect dev vs prod. The result is reused for the banner.
_is_dev, _dev_label = _is_dev_environment()

st.set_page_config(
    page_title=("Minted TCG — Inventory Log · DEV" if _is_dev
                else "Minted TCG — Inventory Log"),
    page_icon=("🚧" if _is_dev else "🎴"),
    layout="centered",
    initial_sidebar_state="collapsed",
)

# --- Brand tokens (Minted TCG · Play the Game palette) --------------------
# Sampled from the official brand kit PNGs.

BRAND_GREEN  = "#157649"  # primary / logo green
DEEP_GREEN   = "#0C1F18"  # near-black forest — hero & section heads
GOLD         = "#FFCC08"  # accent — "PLAY" highlight
GOLD_SOFT    = "#FFE174"  # hover / glow
MINT_WASH    = "#F2F8F4"  # off-white wash for stripes
SAGE_BORDER  = "#C9DBD0"
INK          = "#0C1F18"
MUTED        = "#5A6B63"

# Headers use Neue Haas Grotesk Display Pro 95 Black (brand). Body uses Effra
# (brand). Both are licensed fonts, so we fall back through close free
# substitutes (Archivo 900 / Mulish) for viewers who don't have them locally.
DISPLAY_STACK = (
    "'Neue Haas Grotesk Display Pro', 'Neue Haas Grotesque', "
    "'NHaasGroteskDSPro-95Blk', 'Helvetica Neue', Archivo, Helvetica, sans-serif"
)
BODY_STACK = "Effra, Mulish, 'Inter', system-ui, sans-serif"

# Pre-compute the hero logo data URI so it can be baked into the hero's CSS
# background stack (one element, no nested img/div).
_HERO_LOGO_URI = _logo_data_uri("logo_horizontal_white_yellow.png") or ""

st.markdown(
    f"""
    <style>
      /* --- Webfont fallbacks (close free matches to brand fonts) ---- */
      @import url('https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800;900&family=Mulish:wght@400;500;600;700;800&display=swap');

      /* --- Page base ------------------------------------------------- */
      .stApp {{
        background:
          radial-gradient(ellipse at 0% -10%, rgba(21, 118, 73, 0.10) 0%, transparent 55%),
          radial-gradient(ellipse at 100% 110%, rgba(255, 204, 8, 0.08) 0%, transparent 55%),
          #FFFFFF;
      }}
      .block-container {{
        max-width: 780px;
        padding-top: 2.25rem;
        padding-bottom: 4rem;
      }}

      /* --- Hero ------------------------------------------------------ */
      /* The logo is layered as a CSS background on the hero itself — NOT
         an img, NOT a child div. One element, one composited background.
         Nothing for Streamlit's theme to paint between. */
      .minted-hero {{
        position: relative;
        background-color: {BRAND_GREEN};
        background-image:
          url("{_HERO_LOGO_URI}"),
          radial-gradient(circle at 88% 22%, rgba(255, 204, 8, 0.18) 0%, transparent 48%),
          linear-gradient(160deg, #0F5C39 0%, {BRAND_GREEN} 55%, #1A8554 100%);
        background-repeat: no-repeat, no-repeat, no-repeat;
        background-position: 36px 30px, top right, top left;
        background-size: 240px auto, 100% 100%, 100% 100%;
        color: #FFFFFF;
        padding: 132px 36px 30px;
        border-radius: 18px;
        margin-bottom: 28px;
        box-shadow: 0 22px 50px -22px rgba(12, 31, 24, 0.55);
        overflow: hidden;
      }}
      .minted-hero::after {{
        content: "";
        position: absolute;
        left: 0; right: 0; bottom: 0;
        height: 6px;
        background: {GOLD};
      }}
      .minted-hero h1 {{
        font-family: {DISPLAY_STACK};
        font-size: 1.65rem;
        font-weight: 900;
        margin: 0 0 6px;
        letter-spacing: -0.01em;
        color: #FFFFFF;
        text-transform: none;
      }}
      .minted-hero .eyebrow {{
        font-family: {BODY_STACK};
        font-size: 0.78rem;
        font-weight: 700;
        margin: 0 0 14px;
        color: {GOLD};
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }}
      .minted-hero p.lede {{
        font-family: {BODY_STACK};
        font-size: 0.96rem;
        font-weight: 500;
        margin: 0;
        max-width: 56ch;
        color: rgba(255, 255, 255, 0.86);
        line-height: 1.55;
      }}

      /* --- Section cards -------------------------------------------- */
      .step-card {{
        position: relative;
        background: #FFFFFF;
        border: 1px solid {SAGE_BORDER};
        border-left: 4px solid {BRAND_GREEN};
        border-radius: 12px;
        padding: 22px 24px 22px 26px;
        margin-bottom: 18px;
        box-shadow: 0 2px 10px rgba(12, 31, 24, 0.06);
      }}
      .step-card .step-num {{
        display: inline-block;
        background: {BRAND_GREEN};
        color: {GOLD};
        font-family: {DISPLAY_STACK};
        font-weight: 900;
        font-size: 0.72rem;
        letter-spacing: 0.12em;
        padding: 4px 10px;
        border-radius: 999px;
        text-transform: uppercase;
        margin-bottom: 10px;
      }}
      .step-card h3 {{
        font-family: {DISPLAY_STACK};
        color: {DEEP_GREEN};
        font-size: 1.12rem;
        font-weight: 900;
        margin: 0 0 8px;
        letter-spacing: -0.005em;
      }}
      .step-card p, .step-card li {{
        font-family: {BODY_STACK};
        color: #1A1A1A;
        font-size: 0.94rem;
        margin: 0;
      }}
      .step-card.naming  {{ border-left-color: {DEEP_GREEN}; }}
      .step-card.build   {{ border-left-color: {BRAND_GREEN}; }}
      .step-card.success {{ border-left-color: {GOLD}; }}

      /* --- File uploader -------------------------------------------- */
      div[data-testid="stFileUploader"] section {{
        background: {MINT_WASH};
        border: 2px dashed {BRAND_GREEN};
        border-radius: 12px;
        padding: 22px;
      }}

      /* --- Primary buttons / download ------------------------------- */
      div.stButton > button[kind="primary"],
      div.stDownloadButton > button {{
        background: {BRAND_GREEN};
        color: #FFFFFF;
        border: 0;
        border-radius: 10px;
        padding: 14px 24px;
        font-family: {DISPLAY_STACK};
        font-weight: 900;
        font-size: 1.02rem;
        letter-spacing: 0.02em;
        box-shadow: 0 14px 32px -12px rgba(21, 118, 73, 0.55);
        transition: transform 120ms ease, box-shadow 120ms ease,
                    background 120ms ease, color 120ms ease;
      }}
      div.stButton > button[kind="primary"]:hover,
      div.stDownloadButton > button:hover {{
        transform: translateY(-1px);
        background: {DEEP_GREEN};
        color: {GOLD};
        box-shadow: 0 18px 44px -14px rgba(12, 31, 24, 0.5);
      }}
      div.stButton > button[kind="primary"]:focus,
      div.stDownloadButton > button:focus {{
        outline: 3px solid {GOLD_SOFT};
        outline-offset: 2px;
      }}

      /* --- Stat tiles ------------------------------------------------ */
      .stat-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 12px;
        margin-top: 14px;
      }}
      .stat-tile {{
        background: {DEEP_GREEN};
        color: #FFFFFF;
        border-radius: 12px;
        padding: 16px 14px;
        text-align: center;
        position: relative;
        overflow: hidden;
      }}
      .stat-tile::after {{
        content: "";
        position: absolute;
        left: 0; right: 0; bottom: 0;
        height: 3px;
        background: {GOLD};
        opacity: 0.85;
      }}
      .stat-tile .label {{
        font-family: {BODY_STACK};
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: {GOLD};
        margin-bottom: 6px;
      }}
      .stat-tile .value {{
        font-family: {DISPLAY_STACK};
        font-size: 1.85rem;
        font-weight: 900;
        line-height: 1;
      }}
      .stat-tile.alt {{
        background: {BRAND_GREEN};
        color: #FFFFFF;
      }}
      .stat-tile.alt .label {{ color: {GOLD}; }}

      /* --- Progress bar --------------------------------------------- */
      div[data-testid="stProgressBar"] > div {{
        background-color: {BRAND_GREEN} !important;
      }}

      /* Apply Effra / Mulish to body text & form widgets. NOTE: we don't
         use a `*` wildcard inside the file uploader — Streamlit renders
         its upload icon with a Material Symbols icon font where the
         literal word "upload" is the ligature. Overriding that font
         makes the browser render the word as text. */
      .stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4,
      .stApp h5, .stApp h6, .stApp label, .stApp button, .stApp input,
      .stApp .stCaption, .stApp [data-testid="stMarkdownContainer"] p {{
        font-family: {BODY_STACK};
      }}

      .footer {{
        margin-top: 36px;
        text-align: center;
        font-family: {BODY_STACK};
        font-size: 0.78rem;
        color: {MUTED};
      }}
      .footer .dot {{ color: {GOLD}; padding: 0 6px; }}

      /* DEV-only banner — full-width strip across the top of the page.
         Auto-hides on prod via _is_dev_environment(). The Streamlit toolbar
         sits above us (40 px tall), so we offset the banner downward to
         clear it, and pad the page so the banner doesn't cover the hero. */
      .dev-banner {{
        position: fixed;
        top: 40px;
        left: 0;
        right: 0;
        z-index: 9998;
        background: repeating-linear-gradient(
          135deg,
          {GOLD} 0,
          {GOLD} 18px,
          #F0B800 18px,
          #F0B800 36px
        );
        color: {DEEP_GREEN};
        text-align: center;
        font-family: {DISPLAY_STACK};
        font-weight: 900;
        font-size: 0.85rem;
        letter-spacing: 0.22em;
        padding: 10px 16px;
        text-transform: uppercase;
        box-shadow: 0 4px 14px -4px rgba(12, 31, 24, 0.35);
        border-bottom: 2px solid {DEEP_GREEN};
      }}
      .dev-banner .pulse {{
        display: inline-block;
        width: 10px;
        height: 10px;
        margin-right: 10px;
        border-radius: 50%;
        background: {DEEP_GREEN};
        vertical-align: middle;
        animation: dev-pulse 1.6s ease-in-out infinite;
      }}
      @keyframes dev-pulse {{
        0%, 100% {{ opacity: 1; transform: scale(1); }}
        50%      {{ opacity: 0.35; transform: scale(0.7); }}
      }}
      /* Push the page content down so the fixed banner doesn't overlap. */
      body.has-dev-banner .stApp,
      .has-dev-banner .block-container {{
        padding-top: 56px !important;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- DEV banner (auto-hidden on prod) -------------------------------------

if _is_dev:
    st.markdown(
        f"""
        <script>
          document.body && document.body.classList.add('has-dev-banner');
          const root = window.parent && window.parent.document && window.parent.document.body;
          if (root) {{ root.classList.add('has-dev-banner'); }}
        </script>
        <div class="dev-banner">
          <span class="pulse"></span>{_dev_label} · NOT FOR PRODUCTION · CHANGES HERE WON'T AFFECT THE LIVE TEAM URL
        </div>
        """,
        unsafe_allow_html=True,
    )


# --- Hero -----------------------------------------------------------------

st.markdown(
    f"""
    <div class="minted-hero" role="banner" aria-label="Minted TCG — Play the Game">
      <p class="eyebrow">Internal Tool</p>
      <h1>Inventory Log Generator</h1>
      <p class="lede">
        Drop in a Shopify inventory export and get back a branded
        <b style="color:{GOLD};">Daily Inventory Log</b> workbook —
        ready for counts, audits, and discrepancy tracking.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --- Step 1: Instructions -------------------------------------------------

st.markdown(
    """
    <div class="step-card">
      <span class="step-num">Step 1</span>
      <h3>Export inventory from Shopify</h3>
      <p style="margin-bottom:14px; color:#1A1A1A; font-size:0.95rem;">
        Follow these steps so the CSV matches what this tool expects.
      </p>
      <ol style="margin:0 0 0 1.1rem; padding:0; color:#1A1A1A; font-size:0.92rem; line-height:1.65;">
        <li style="margin-bottom:10px;">Open <b>Shopify Admin</b> → <b>Products</b> → <b>Inventory</b>.</li>
        <li style="margin-bottom:10px;">At the <b>top left</b>, next to <b>Inventory</b>, open the <b>location</b> dropdown and select the store you're exporting for.</li>
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
      <span class="step-num">Step 2</span>
      <h3>Upload the CSV</h3>
      <p>Drag the CSV from your desktop or Downloads — usually the file Shopify emailed you.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

uploaded = st.file_uploader(
    "Drop your inventory_export*.csv here",
    type=["csv"],
    label_visibility="collapsed",
)

# Defaults for download file naming. Both location AND date are required — date
# starts empty (None) instead of today() so the user must actively pick one.
if "inv_export_location" not in st.session_state:
    st.session_state["inv_export_location"] = ""
if "inv_export_date" not in st.session_state:
    st.session_state["inv_export_date"] = None

show_naming = uploaded is not None or "xlsx_bytes" in st.session_state

if show_naming:
    st.markdown(
        f"""
        <div class="step-card naming">
          <span class="step-num">Name it</span>
          <h3>Name your download <span style="color:{GOLD};">*required</span></h3>
          <p>We'll save the workbook as <b>Location</b> + <b>date</b> +
             <code style="font-size:0.85em;">_Daily_Inventory_Log.xlsx</code> — e.g.
             <code style="font-size:0.85em;">Dacula_2026-05-13_Daily_Inventory_Log.xlsx</code>.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input(
        "Store / location name *",
        placeholder="e.g. Dacula · Lawrenceville",
        key="inv_export_location",
        help="Required. Unsafe characters become underscores in the file name.",
    )
    st.date_input(
        "Date on the file *",
        key="inv_export_date",
        help="Required. Pick the day of this count / export.",
        format="YYYY-MM-DD",
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
        <div class="step-card build">
          <span class="step-num">Step 3</span>
          <h3>Build the inventory log</h3>
          <p><b>{uploaded.name}</b> · {_human_size(uploaded.size)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _loc_filled = bool(st.session_state.get("inv_export_location", "").strip())
    _date_filled = st.session_state.get("inv_export_date") is not None
    _missing = []
    if not _loc_filled:
        _missing.append("store / location name")
    if not _date_filled:
        _missing.append("date")
    _can_build = _loc_filled and _date_filled

    if _missing:
        st.caption(
            "Fill in the **"
            + "** and **".join(_missing)
            + "** above before building."
        )

    if st.button(
        "Build Inventory Log",
        type="primary",
        use_container_width=True,
        disabled=not _can_build,
    ):
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
        <div class="step-card success">
          <span class="step-num" style="background:{GOLD}; color:{DEEP_GREEN};">Step 4</span>
          <h3>Download &amp; share</h3>
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
      Minted TCG <span class="dot">●</span> Play the Game <span class="dot">●</span> Built {datetime.now():%B %Y}
    </div>
    """,
    unsafe_allow_html=True,
)
