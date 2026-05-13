"""
Builds the Minted-branded Inventory Log workbook from a Shopify-style
inventory export CSV.

Sheets:
  1. Dashboard       - Live stats (formulas pulling from Active Inventory)
  2. Active Inventory- All SKUs currently in stock (Physical Count + auto Diff/Status)
  3. Full Catalog    - Every SKU from the export (for searching anything)
  4. Discrepancy Log - Quick-reference table that auto-flags counted mismatches

Brand palette (Minted TCG):
  Primary green #1B733D · Deep green #0E1B14 · Gold accent #E8C547 · White
"""

from __future__ import annotations

import csv
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import column_index_from_string
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.filters import AutoFilter, FilterColumn, Filters
from openpyxl.worksheet.table import Table, TableStyleInfo


# --- Singles vs Sealed classifier -----------------------------------------

def print_progress(iteration, total, prefix='', suffix='', decimals=1, length=40, fill='█'):
    if total == 0:
        return
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    if iteration == total:
        sys.stdout.write('\n')

CARD_NUM_RE = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}\b")
GRADE_RE = re.compile(r"\b(PSA|BGS|CGC|SGC|HGA|GMA)\s*\d", re.IGNORECASE)
PROMO_CODE_RE = re.compile(
    r"\b(SAR|SIR|FA|GG\d+|TG\d+|SV\d+|SWSH\d+|XY\d+|SM\d+|BW\d+|HGSS\d+)\b",
    re.IGNORECASE,
)

SEALED_PATTERNS = [
    r"booster box", r"booster bundle", r"booster pack", r"build[-\s]?n[-\s]?play",
    r"\bETB\b", r"elite trainer", r"elite trainer box",
    r"collection box", r"collector(?:'?s)? box", r"collector(?:'?s)? chest",
    r"premium collection", r"gift box", r"gift set", r"gift pack",
    r"theme deck", r"starter deck", r"commander deck", r"preconstructed deck",
    r"deck box", r"\bbundle\b", r"\btin\b", r"\balbum\b", r"\bbinder\b",
    r"\bportfolio\b", r"\bsleeves?\b", r"\bplaymat\b", r"play mat",
    r"\bdice\b", r"\bdisplay\b", r"dynacrate", r"storage", r"top\s?loader",
    r"magnetic (?:case|holder|loader)", r"\bdivider\b", r"gamegenic",
    r"ultra pro", r"dragon shield", r"ultimate guard",
    r"\bbox set\b", r"backpack", r"\bsatchel\b",
    r"tournament pack", r"token set", r"\bplush\b", r"\bkeychain\b",
    r"\blanyard\b", r"\bfigurines?\b", r"\bfigure\b", r"mystery box",
    r"\bsticker pack\b", r"\bcard case\b", r"\bdeckbox\b",
    r"\baccessor\w+", r"\bsleeve set\b", r"box opening", r"fat pack",
    r"\bpin set\b", r"\bsquaroes\b", r"\bboulder\s*\d", r"\bmat\b\s",
]
SEALED_RE = re.compile("|".join(SEALED_PATTERNS), re.IGNORECASE)


def classify_category(title: str) -> str:
    """Return 'Single' or 'Sealed' for a product title."""
    if not title:
        return "Single"
    if GRADE_RE.search(title):
        return "Single"
    has_card_num = bool(CARD_NUM_RE.search(title))
    if SEALED_RE.search(title) and not has_card_num:
        return "Sealed"
    if has_card_num:
        return "Single"
    if PROMO_CODE_RE.search(title):
        return "Single"
    return "Single"


# --- Game / IP detector ----------------------------------------------------

# Order matters: most specific patterns first. Each entry = (label, regex).
GAME_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Pokémon",        re.compile(r"\b(pok[eé]?mon|pokeball|eevee|pikachu|charizard|umbreon|sylveon|gengar|mewtwo|venusaur|blastoise)\b", re.IGNORECASE)),
    ("Magic",          re.compile(r"\b(magic[:\s]*the\s*gathering|mtg|\bmagic\s+(?:booster|the)\b)", re.IGNORECASE)),
    ("Yu-Gi-Oh!",      re.compile(r"\byu[\s-]?gi[\s-]?oh\b", re.IGNORECASE)),
    ("One Piece",      re.compile(r"\bone\s*piece\b|\bOP\d+", re.IGNORECASE)),
    ("Lorcana",        re.compile(r"\blorcana\b", re.IGNORECASE)),
    ("Dragon Ball",    re.compile(r"\bdragon\s*ball|\bDBS\b", re.IGNORECASE)),
    ("Flesh & Blood",  re.compile(r"\bflesh\s*(?:&|and|n)\s*blood\b|tales\s+of\s+aria", re.IGNORECASE)),
    ("Union Arena",    re.compile(r"\bunion\s*arena\b", re.IGNORECASE)),
    ("Riftbound",      re.compile(r"\briftbound\b|\bleague\s+of\s+legends\b", re.IGNORECASE)),
    ("Weiss Schwarz",  re.compile(r"\bweiss\s*schwarz\b", re.IGNORECASE)),
    ("Grand Archive",  re.compile(r"\bgrand\s*archive\b", re.IGNORECASE)),
    ("Universus",      re.compile(r"\buniversus\b", re.IGNORECASE)),
    ("Warhammer",      re.compile(r"\bwarhammer\b|astra\s+militarum|space\s+marine", re.IGNORECASE)),
    ("Sports",         re.compile(r"\b(topps|donruss|bowman|panini|prizm|select|chrome|optic|fleer|leaf|upper\s*deck|mosaic|stadium\s+club)\b", re.IGNORECASE)),
    ("Star Wars",      re.compile(r"\bstar\s*wars|\bswu\b|unlimited", re.IGNORECASE)),
    ("Digimon",        re.compile(r"\bdigimon\b", re.IGNORECASE)),
    ("Disney",         re.compile(r"\bdisney\b", re.IGNORECASE)),
    ("Accessories",    re.compile(r"\b(dragon shield|ultra pro|ultimate guard|gamegenic|vault\s*x|bcw|toploader|top\s*loader|penny sleeve|sleeve|binder|deck box|playmat|dice\b|pin\s+collection)\b", re.IGNORECASE)),
    ("Beverages",      re.compile(r"\bbeverage|\bdrinks?\b", re.IGNORECASE)),
]


def detect_game(title: str) -> str:
    if not title:
        return "Other"
    for label, rx in GAME_PATTERNS:
        if rx.search(title):
            return label
    return "Other"


# Brand-friendly color palette per game. Format: (bg, fg).
GAME_COLORS: dict[str, tuple[str, str]] = {
    "Pokémon":       ("FFFEF3C7", "FF92400E"),  # soft yellow / amber
    "Magic":         ("FFDBEAFE", "FF1E3A8A"),  # soft blue / deep blue
    "Yu-Gi-Oh!":     ("FFEDE9FE", "FF6D28D9"),  # lavender / purple
    "One Piece":     ("FFFED7AA", "FFC2410C"),  # peach / orange-red
    "Lorcana":       ("FFFCE7F3", "FFBE185D"),  # pink / magenta
    "Dragon Ball":   ("FFFFEDD5", "FF9A3412"),  # warm orange
    "Flesh & Blood": ("FFFEE2E2", "FF991B1B"),  # blush / crimson
    "Union Arena":   ("FFCCFBF1", "FF115E59"),  # mint teal
    "Riftbound":     ("FFCFFAFE", "FF155E75"),  # cyan / teal
    "Weiss Schwarz": ("FFECFCCB", "FF3F6212"),  # olive / lime
    "Grand Archive": ("FFD1FAE5", "FF065F46"),  # green
    "Universus":     ("FFF3F4F6", "FF374151"),  # silver / slate
    "Warhammer":     ("FFE5E7EB", "FF1F2937"),  # grey / charcoal
    "Sports":        ("FFDCFCE7", "FF166534"),  # forest green
    "Star Wars":     ("FF1F2937", "FFFEF3C7"),  # dark with gold
    "Digimon":       ("FFE0F2FE", "FF075985"),  # sky blue
    "Disney":        ("FFFBCFE8", "FF9D174D"),  # disney pink
    "Accessories":   ("FFE7E5E4", "FF44403C"),  # stone / neutral
    "Beverages":     ("FFFEF9C3", "FF713F12"),  # cream / brown
    "Other":         ("FFF3F4F6", "FF4B5563"),  # neutral
}




ROOT = Path(__file__).resolve().parent
DOWNLOADS = Path.home() / "Downloads"


def _find_logo() -> Path | None:
    """Workbook banner: white horizontal logo on dark green rows."""
    for candidate in (
        ROOT / "assets" / "branding" / "logo_excel_header.png",
        ROOT / "assets" / "minted-logo.png",
        ROOT / "design-system" / "assets" / "minted-logo.png",
    ):
        if candidate.exists():
            return candidate
    return None


LOGO_PATH: Path | None = _find_logo()
OUTPUT_PATH = ROOT / "Minted_Inventory_Log.xlsx"


_FILENAME_UNSAFE = re.compile(r"[\s/\\:*?\"<>|]+")


def sanitize_filename_part(raw: str) -> str:
    """One path segment safe for macOS / Windows / Linux file names."""
    s = (raw or "").strip()
    if not s:
        return "Location_unknown"
    s = _FILENAME_UNSAFE.sub("_", s)
    s = s.strip("._")
    return s or "Location_unknown"


def build_inventory_download_filename(location: str, export_date: date) -> str:
    """Build download name: ``{Location}_{YYYY-MM-DD}_Daily_Inventory_Log.xlsx``."""
    loc = sanitize_filename_part(location)
    return f"{loc}_{export_date:%Y-%m-%d}_Daily_Inventory_Log.xlsx"


def find_inventory_csv() -> Path:
    """Locate the Shopify inventory export to use.

    Resolution order:
      1. Path passed on the command line (sys.argv[1])
      2. Newest `inventory_export*.csv` in ~/Downloads
      3. Fall back to `~/Downloads/inventory_export_1.csv`
    """
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1]).expanduser().resolve()
        if not candidate.exists():
            raise SystemExit(f"CSV not found: {candidate}")
        return candidate

    matches = sorted(
        DOWNLOADS.glob("inventory_export*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]

    fallback = DOWNLOADS / "inventory_export_1.csv"
    if fallback.exists():
        return fallback

    raise SystemExit(
        f"No Shopify inventory export found.\n"
        f"Save your CSV as ~/Downloads/inventory_export_1.csv "
        f"or pass a path: python3 build_inventory_log.py /path/to/export.csv"
    )


# --- Brand tokens (Minted TCG · 2026 palette) -------------------------------
# Medium forest green, deep green, gold accent, white — aligned with brand kit.

BRAND_PRIMARY = "FF1B733D"   # primary green (logo / CTAs)
MINT = "FFC8DDD0"            # light sage for secondary tiles & tints
MINT_SOFT = "FFEEF4F0"      # very light wash for hints & stripes
DEEP_GREEN = "FF0E1B14"     # near-black forest for headers & banners
NEON = "FFE8C547"           # gold / "PLAY" accent (bars, highlights)
WHITE = "FFFFFFFF"
INK = "FF1A1A1A"
SOFT_BORDER = "FFC5D4CC"
DANGER_BG = "FFFDE7E9"
DANGER_FG = "FFB42318"
WARN_BG = "FFFFF4D6"
WARN_FG = "FF8A6100"
SUCCESS_BG = "FFE6F8EF"
SUCCESS_FG = "FF1B733D"
NEUTRAL_BG = "FFF1F4F2"

DISPLAY_FONT = "Inter"
BODY_FONT = "DM Sans"

THIN = Side(style="thin", color=SOFT_BORDER)
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def fill(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


# --- Banner / chrome -------------------------------------------------------

def banner(ws, title: str, subtitle: str, end_col_letter: str, logo_path: Path | None = None) -> None:
    """Apply the standard Minted dark banner across the top of a sheet."""
    ws.merge_cells(f"A1:{end_col_letter}1")
    ws.merge_cells(f"A2:{end_col_letter}2")
    ws.merge_cells(f"A3:{end_col_letter}3")

    ws.row_dimensions[1].height = 10
    ws.row_dimensions[2].height = 44
    ws.row_dimensions[3].height = 22

    cell = ws.cell(row=2, column=1, value=title)
    cell.font = Font(name=DISPLAY_FONT, size=22, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=2)

    cell = ws.cell(row=3, column=1, value=subtitle)
    cell.font = Font(name=BODY_FONT, size=11, bold=True, color=NEON)
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=2)

    last_col = column_index_from_string(end_col_letter)
    for r in (1, 2, 3):
        for c in range(1, last_col + 1):
            ws.cell(row=r, column=c).fill = fill(DEEP_GREEN)

    ws.row_dimensions[4].height = 4
    for c in range(1, last_col + 1):
        ws.cell(row=4, column=c).fill = fill(NEON)

    if logo_path and logo_path.exists():
        try:
            img = XLImage(str(logo_path))
            scale = 36 / img.height
            img.width = int(img.width * scale)
            img.height = 36
            img.anchor = f"{end_col_letter}2"
            ws.add_image(img)
        except Exception:
            pass


def style_header_row(ws, row: int, columns: int, *, start_column: int = 1) -> None:
    for c in range(start_column, start_column + columns):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill(DEEP_GREEN)
        cell.font = Font(name=BODY_FONT, size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER_ALL
    ws.row_dimensions[row].height = 34


def style_data_cell(cell, *, bold: bool = False, align: str = "left", color: str = INK) -> None:
    cell.font = Font(name=BODY_FONT, size=10, bold=bold, color=color)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    cell.border = BORDER_ALL


# --- Read source CSV -------------------------------------------------------

def safe_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def build_variant_label(row: dict) -> str:
    """Combine Option*-style fields into a readable variant string."""
    parts: list[str] = []
    for n in (1, 2, 3):
        name = (row.get(f"Option{n} Name") or "").strip()
        value = (row.get(f"Option{n} Value") or "").strip()
        if not value or value.lower() == "default title":
            continue
        if name and name.lower() not in {"title", "default title"}:
            parts.append(f"{name}: {value}")
        else:
            parts.append(value)
    return " · ".join(parts)


# Columns the Shopify "Inventory" CSV export must contain. If any are missing
# we bail with a clean error rather than producing an empty workbook.
REQUIRED_CSV_COLUMNS = (
    "Handle",
    "Title",
    "On hand (current)",
)


class InvalidShopifyCsv(ValueError):
    """Raised when the uploaded CSV isn't a Shopify Inventory export."""


def validate_shopify_csv(csv_path: Path) -> None:
    """Inspect a CSV's headers and raise InvalidShopifyCsv if it can't be used."""
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])

    fieldset = set(fieldnames)
    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in fieldset]
    if missing:
        hint = (
            "This doesn't look like a Shopify Inventory export.\n\n"
            f"Missing required column(s): {', '.join(missing)}\n\n"
            f"Found columns: {', '.join(fieldnames) or '(none)'}\n\n"
            "Export the right file from Shopify Admin → Products → Inventory → "
            "Export → 'CSV for Excel, Numbers, or other spreadsheet programs'."
        )
        raise InvalidShopifyCsv(hint)


def load_rows(csv_path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            on_hand = safe_int(raw.get("On hand (current)"))
            available = safe_int(raw.get("Available (not editable)"))
            committed = safe_int(raw.get("Committed (not editable)"))
            unavailable = safe_int(raw.get("Unavailable (not editable)"))
            incoming = safe_int(raw.get("Incoming (not editable)"))
            title = raw.get("Title") or ""
            sku = (raw.get("SKU") or "").strip()
            rows.append({
                "handle": raw.get("Handle") or "",
                "title": title,
                "variant": build_variant_label(raw),
                "sku": sku,
                "location": raw.get("Location") or "",
                "bin": raw.get("Bin name") or "",
                "on_hand": on_hand,
                "available": available,
                "committed": committed,
                "unavailable": unavailable,
                "incoming": incoming,
                "category": classify_category(title),
                "game": detect_game(title),
            })
    return rows


# --- Sheet builders --------------------------------------------------------

ACTIVE_HEADERS = [
    "#",                 # A
    "Counted?",           # B
    "Game",               # C
    "Product",            # D
    "Variant",            # E
    "SKU",                # F
    "System On Hand",     # G
    "Physical Count",     # H
    "Difference",         # I
    "Status",             # J
    "Counted By",         # K
    "Date Counted",       # L
    "Notes",              # M
]

ACTIVE_WIDTHS = [6, 11, 16, 48, 26, 18, 14, 14, 13, 24, 16, 14, 36]


def build_active_inventory(
    wb: Workbook,
    rows: list[dict],
    logo: Path,
    *,
    sheet_name: str,
    title: str,
    subtitle: str,
    tab_color: str,
    table_name: str,
    pad_rows: int = 40,
) -> tuple[str, int, int]:
    """Working sheet for a category. Only items with stock > 0.

    Returns (sheet_name, first_data_row, last_data_row_including_padding).
    """
    ws = wb.create_sheet(sheet_name)
    ws.sheet_view.showGridLines = False

    for i, w in enumerate(ACTIVE_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    end_col_letter = get_column_letter(len(ACTIVE_HEADERS))
    banner(ws, title, subtitle, end_col_letter, logo)

    # Instruction strip
    ws.row_dimensions[6].height = 22
    ws.cell(row=6, column=1, value="HOW TO USE").fill = fill(MINT)
    ws.cell(row=6, column=1).font = Font(name=BODY_FONT, size=10, bold=True, color=DEEP_GREEN)
    ws.cell(row=6, column=1).alignment = Alignment(horizontal="center", vertical="center")
    ws.cell(row=6, column=1).border = BORDER_ALL
    ws.merge_cells(start_row=6, start_column=2, end_row=6, end_column=len(ACTIVE_HEADERS))
    hint = ws.cell(
        row=6,
        column=2,
        value="Fill in PHYSICAL COUNT (column H). Difference + Status update automatically. Use Counted? to mark done.",
    )
    hint.font = Font(name=BODY_FONT, size=10, italic=True, color=DEEP_GREEN)
    hint.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    hint.fill = fill(MINT_SOFT)

    # Headers (row 8)
    header_row = 8
    for i, h in enumerate(ACTIVE_HEADERS, start=1):
        ws.cell(row=header_row, column=i, value=h)
    style_header_row(ws, header_row, len(ACTIVE_HEADERS))

    # Caller has already filtered to the relevant category. Sort alphabetically.
    active = list(rows)
    active.sort(key=lambda r: (r["title"].lower(), r["variant"].lower()))
    total_active = len(active)

    first_data_row = header_row + 1
    for idx, r in enumerate(active, start=1):
        if idx % 100 == 0 or idx == total_active:
            print_progress(idx, total_active, prefix=f"  {sheet_name} rows")
        rr = first_data_row + idx - 1
        ws.cell(row=rr, column=1, value=idx)               # A: #
        ws.cell(row=rr, column=2, value=f'=IF(H{rr}="","No","Yes")')  # B: Counted?
        ws.cell(row=rr, column=3, value=r["game"])          # C: Game
        ws.cell(row=rr, column=4, value=r["title"])         # D: Product
        ws.cell(row=rr, column=5, value=r["variant"])       # E: Variant
        ws.cell(row=rr, column=6, value=r["sku"])           # F: SKU
        ws.cell(row=rr, column=7, value=r["on_hand"])       # G: System On Hand
        # H: Physical Count (blank for now)
        # I: Difference = H - G (blank when not counted)
        ws.cell(row=rr, column=9, value=f'=IF(H{rr}="","",H{rr}-G{rr})')
        # J: Status
        ws.cell(
            row=rr,
            column=10,
            value=(
                f'=IF(H{rr}="","Pending Count",'
                f'IF(H{rr}=G{rr},"OK - Match",'
                f'IF(AND(H{rr}=0,G{rr}>0),"MISSING - Out of Stock",'
                f'IF(H{rr}<G{rr},"SHORT - Discrepancy",'
                f'IF(H{rr}>G{rr},"OVER - Discrepancy","")))))'
            ),
        )

    last_data_row = first_data_row + len(active) - 1

    # Padding rows
    pad = pad_rows
    last_total_row = last_data_row + pad
    for rr in range(last_data_row + 1, last_total_row + 1):
        ws.cell(row=rr, column=1, value=f"=IF(D{rr}=\"\",\"\",MAX($A${first_data_row}:A{rr - 1})+1)")
        ws.cell(row=rr, column=2, value=f'=IF(H{rr}="","No","Yes")')
        ws.cell(row=rr, column=9, value=f'=IF(OR(G{rr}="",H{rr}=""),"",H{rr}-G{rr})')
        ws.cell(
            row=rr,
            column=10,
            value=(
                f'=IF(OR(G{rr}="",H{rr}=""),"",'
                f'IF(H{rr}=G{rr},"OK - Match",'
                f'IF(AND(H{rr}=0,G{rr}>0),"MISSING - Out of Stock",'
                f'IF(H{rr}<G{rr},"SHORT - Discrepancy",'
                f'IF(H{rr}>G{rr},"OVER - Discrepancy","")))))'
            ),
        )

    # Style every cell in the body
    left_cols = {3, 4, 5, 13}  # Game, Product, Variant, Notes
    for rr in range(first_data_row, last_total_row + 1):
        ws.row_dimensions[rr].height = 30
        for cc in range(1, len(ACTIVE_HEADERS) + 1):
            cell = ws.cell(row=rr, column=cc)
            align = "left" if cc in left_cols else "center"
            bold = (cc == 10)  # Status is bold
            style_data_cell(cell, bold=bold, align=align)
    for rr in range(first_data_row, last_total_row + 1):
        ws.cell(row=rr, column=7).number_format = "#,##0"             # System
        ws.cell(row=rr, column=8).number_format = "#,##0"             # Physical
        ws.cell(row=rr, column=9).number_format = "+#,##0;-#,##0;0;@" # Diff
        ws.cell(row=rr, column=12).number_format = "yyyy-mm-dd"        # Date

    # Game color chips — apply per row (only on data rows, not padding)
    for offset, r in enumerate(active):
        rr = first_data_row + offset
        bg, fg = GAME_COLORS.get(r["game"], GAME_COLORS["Other"])
        chip = ws.cell(row=rr, column=3)
        chip.fill = fill(bg)
        chip.font = Font(name=BODY_FONT, size=10, bold=True, color=fg)
        chip.alignment = Alignment(horizontal="center", vertical="center")

    # --- Hidden helper column N: discrepancy rank used by Discrepancy Log --
    # For each data row, emit ROW-offset if status is a discrepancy/missing,
    # else "". SMALL() then walks this column from smallest to largest to
    # compact only the populated rows.
    helper_col = 14  # column N
    for rr in range(first_data_row, last_total_row + 1):
        ws.cell(
            row=rr,
            column=helper_col,
            value=(
                f'=IF(OR(ISNUMBER(SEARCH("Discrepancy",J{rr})),'
                f'ISNUMBER(SEARCH("MISSING",J{rr}))),ROW()-{first_data_row - 1},"")'
            ),
        )
    ws.column_dimensions[get_column_letter(helper_col)].hidden = True

    # Freeze top + first 4 cols (#, Counted?, Game, Product)
    ws.freeze_panes = ws.cell(row=first_data_row, column=5)
    ws.sheet_view.zoomScale = 110

    table_ref = f"A{header_row}:{end_col_letter}{last_total_row}"
    tbl = Table(displayName=table_name, ref=table_ref)
    tbl.tableStyleInfo = TableStyleInfo(
        name="TableStyleLight1",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(tbl)

    # Conditional formatting on Status column J and Counted column B
    counted_range = f"B{first_data_row}:B{last_total_row}"
    ws.conditional_formatting.add(
        counted_range,
        CellIsRule(operator="equal", formula=['"Yes"'], fill=fill(SUCCESS_BG), font=Font(name=BODY_FONT, size=10, bold=True, color=SUCCESS_FG)),
    )
    ws.conditional_formatting.add(
        counted_range,
        CellIsRule(operator="equal", formula=['"No"'], fill=fill(DANGER_BG), font=Font(name=BODY_FONT, size=10, bold=True, color=DANGER_FG)),
    )

    status_range = f"J{first_data_row}:J{last_total_row}"
    ws.conditional_formatting.add(
        status_range,
        FormulaRule(
            formula=[f'ISNUMBER(SEARCH("OK",J{first_data_row}))'],
            fill=fill(SUCCESS_BG),
            font=Font(name=BODY_FONT, size=10, bold=True, color=SUCCESS_FG),
        ),
    )
    ws.conditional_formatting.add(
        status_range,
        FormulaRule(
            formula=[f'ISNUMBER(SEARCH("Discrepancy",J{first_data_row}))'],
            fill=fill(DANGER_BG),
            font=Font(name=BODY_FONT, size=10, bold=True, color=DANGER_FG),
        ),
    )
    ws.conditional_formatting.add(
        status_range,
        FormulaRule(
            formula=[f'ISNUMBER(SEARCH("MISSING",J{first_data_row}))'],
            fill=fill(DANGER_BG),
            font=Font(name=BODY_FONT, size=10, bold=True, color=DANGER_FG),
        ),
    )
    ws.conditional_formatting.add(
        status_range,
        FormulaRule(
            formula=[f'J{first_data_row}="Pending Count"'],
            fill=fill(NEUTRAL_BG),
            font=Font(name=BODY_FONT, size=10, italic=True, color="FF666666"),
        ),
    )

    # Difference column I
    diff_range = f"I{first_data_row}:I{last_total_row}"
    ws.conditional_formatting.add(
        diff_range,
        CellIsRule(operator="lessThan", formula=["0"], fill=fill(DANGER_BG), font=Font(name=BODY_FONT, size=10, bold=True, color=DANGER_FG)),
    )
    ws.conditional_formatting.add(
        diff_range,
        CellIsRule(operator="greaterThan", formula=["0"], fill=fill(WARN_BG), font=Font(name=BODY_FONT, size=10, bold=True, color=WARN_FG)),
    )

    # Low stock on System On Hand column G — only if we have data rows
    if last_data_row >= first_data_row:
        low_range = f"G{first_data_row}:G{last_data_row}"
        ws.conditional_formatting.add(
            low_range,
            CellIsRule(operator="lessThanOrEqual", formula=["2"], fill=fill(WARN_BG), font=Font(name=BODY_FONT, size=10, bold=True, color=WARN_FG)),
        )

    ws.sheet_properties.tabColor = tab_color

    return ws.title, first_data_row, last_total_row


CATALOG_HEADERS = [
    "Category",
    "Game",
    "Product",
    "Variant",
    "SKU",
    "Handle",
    "On Hand",
    "Available",
    "Committed",
    "Incoming",
]
CATALOG_WIDTHS = [11, 14, 50, 28, 18, 36, 12, 12, 12, 12]


def build_full_catalog(wb: Workbook, rows: list[dict], logo: Path) -> None:
    ws = wb.create_sheet("Full Catalog")
    ws.sheet_view.showGridLines = False

    for i, w in enumerate(CATALOG_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    end_col_letter = get_column_letter(len(CATALOG_HEADERS))
    banner(
        ws,
        "MINTED — FULL CATALOG",
        "Every SKU from Shopify · Read-only reference for searching",
        end_col_letter,
        logo,
    )

    # Sub strip
    ws.row_dimensions[6].height = 22
    note = ws.cell(
        row=6,
        column=1,
        value=f"Snapshot: {len(rows):,} SKUs · Exported {date.today():%B %d, %Y} · Filter to find any item",
    )
    note.font = Font(name=BODY_FONT, size=10, italic=True, color=DEEP_GREEN)
    note.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    note.fill = fill(MINT_SOFT)
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=len(CATALOG_HEADERS))

    header_row = 8
    for i, h in enumerate(CATALOG_HEADERS, start=1):
        ws.cell(row=header_row, column=i, value=h)
    style_header_row(ws, header_row, len(CATALOG_HEADERS))

    rows_sorted = sorted(rows, key=lambda r: (-r["on_hand"], r["title"].lower(), r["variant"].lower()))
    total_rows = len(rows_sorted)

    first_data_row = header_row + 1
    for i, r in enumerate(rows_sorted, start=0):
        if i % 1000 == 0 or i == total_rows - 1:
            print_progress(i + 1, total_rows, prefix="  Catalog data")
        rr = first_data_row + i
        ws.cell(row=rr, column=1, value=r["category"])
        ws.cell(row=rr, column=2, value=r["game"])
        ws.cell(row=rr, column=3, value=r["title"])
        ws.cell(row=rr, column=4, value=r["variant"])
        ws.cell(row=rr, column=5, value=r["sku"])
        ws.cell(row=rr, column=6, value=r["handle"])
        ws.cell(row=rr, column=7, value=r["on_hand"])
        ws.cell(row=rr, column=8, value=r["available"])
        ws.cell(row=rr, column=9, value=r["committed"])
        ws.cell(row=rr, column=10, value=r["incoming"])

    last_data_row = first_data_row + len(rows_sorted) - 1

    # Light styling — for 79K rows we keep it lean for performance
    body_font = Font(name=BODY_FONT, size=10, color=INK)
    left_align = Alignment(horizontal="left", vertical="center")
    center_align = Alignment(horizontal="center", vertical="center")
    left_cols = {3, 4, 6}  # Product, Variant, Handle
    for rr in range(first_data_row, last_data_row + 1):
        ws.row_dimensions[rr].height = 25
        bg_color = "FFF9FAFB" if rr % 2 == 0 else WHITE
        if (rr - first_data_row) % 1000 == 0 or rr == last_data_row:
            print_progress(rr - first_data_row + 1, last_data_row - first_data_row + 1, prefix="  Catalog styles")
        for cc in range(1, len(CATALOG_HEADERS) + 1):
            cell = ws.cell(row=rr, column=cc)
            cell.font = body_font
            cell.alignment = left_align if cc in left_cols else center_align
            cell.fill = fill(bg_color)

    # Game color chip per row (column B)
    for i, r in enumerate(rows_sorted, start=0):
        rr = first_data_row + i
        bg, fg = GAME_COLORS.get(r["game"], GAME_COLORS["Other"])
        chip = ws.cell(row=rr, column=2)
        chip.fill = fill(bg)
        chip.font = Font(name=BODY_FONT, size=10, bold=True, color=fg)
        chip.alignment = Alignment(horizontal="center", vertical="center")

    # Highlight stocked rows so they pop (column G = On Hand)
    stocked_range = f"A{first_data_row}:{end_col_letter}{last_data_row}"
    ws.conditional_formatting.add(
        stocked_range,
        FormulaRule(formula=[f"$G{first_data_row}>0"], fill=fill(SUCCESS_BG)),
    )

    # AutoFilter (not a Table — better performance at 79K rows)
    ws.auto_filter.ref = f"A{header_row}:{end_col_letter}{last_data_row}"
    ws.freeze_panes = ws.cell(row=first_data_row, column=1)
    ws.sheet_properties.tabColor = "FFB7CCBE"


def build_discrepancy_log(
    wb: Workbook,
    sources: list[tuple[str, str, int, int]],
    logo: Path,
    slots_per_section: int = 100,
) -> None:
    """Auto-compacted discrepancy report.

    Singles and Sealed appear **side by side** (cols A–H and J–Q) so both lists
    are visible without scrolling from one block to the other.

    Uses INDEX/SMALL against hidden helper columns on each count sheet so only
    populated rows appear (no empty mirror rows to filter past).

    sources: list of (category_label, sheet_name, first_row, last_row).
    """
    ws = wb.create_sheet("Discrepancy Log")
    ws.sheet_view.showGridLines = False

    widths = [44, 26, 18, 13, 13, 13, 24, 30]
    SINGLES_START = 1
    SEALED_START = 10
    SPACER = 9
    last_sheet_col = SEALED_START + len(widths) - 1  # 17
    end_sheet_col = get_column_letter(last_sheet_col)

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.column_dimensions[get_column_letter(SPACER)].width = 3
    for j in range(SEALED_START, last_sheet_col + 1):
        ws.column_dimensions[get_column_letter(j)].width = widths[j - SEALED_START]

    banner(
        ws,
        "MINTED — DISCREPANCY LOG",
        "Auto-compacted · Only items needing attention show up here",
        end_sheet_col,
        logo,
    )

    # --- Live summary tiles (rows 6-7) ------------------------------------
    ws.row_dimensions[6].height = 22
    ws.row_dimensions[7].height = 40

    helper_ranges: dict[str, str] = {}
    for label, sheet_name, first_row, last_row in sources:
        helper_ranges[label] = f"'{sheet_name}'!$N${first_row}:$N${last_row}"

    singles_helper = helper_ranges.get("Single", "")
    sealed_helper = helper_ranges.get("Sealed", "")
    total_formula = (
        f"=COUNT({singles_helper})+COUNT({sealed_helper})"
        if singles_helper and sealed_helper
        else f"=COUNT({singles_helper or sealed_helper})"
        if (singles_helper or sealed_helper)
        else "=0"
    )

    singles_status = ""
    sealed_status = ""
    for label, sheet_name, first_row, last_row in sources:
        rng = f"'{sheet_name}'!$J${first_row}:$J${last_row}"
        if label == "Single":
            singles_status = rng
        elif label == "Sealed":
            sealed_status = rng
    missing_formula = (
        f'=COUNTIF({singles_status},"MISSING - Out of Stock")'
        f'+COUNTIF({sealed_status},"MISSING - Out of Stock")'
        if singles_status and sealed_status
        else "=0"
    )

    tile_specs = [
        ("TOTAL OPEN DISCREPANCIES", total_formula,         DEEP_GREEN, WHITE),
        ("SINGLES DISCREPANCIES",     f"=COUNT({singles_helper})" if singles_helper else "=0", MINT, DEEP_GREEN),
        ("SEALED DISCREPANCIES",      f"=COUNT({sealed_helper})"  if sealed_helper  else "=0", MINT, DEEP_GREEN),
        ("MISSING ON SHELF",          missing_formula,       DANGER_BG, DANGER_FG),
    ]
    tile_cols = [(1, 2), (3, 4), (5, 6), (7, 8)]
    for (start_col, end_col), (label, formula, bg, fg) in zip(tile_cols, tile_specs):
        lbl_cell = ws.cell(row=6, column=start_col, value=label)
        lbl_cell.fill = fill(MINT)
        lbl_cell.font = Font(name=BODY_FONT, size=10, bold=True, color=DEEP_GREEN)
        lbl_cell.alignment = Alignment(horizontal="center", vertical="center")
        lbl_cell.border = BORDER_ALL
        ws.merge_cells(start_row=6, start_column=start_col, end_row=6, end_column=end_col)

        val_cell = ws.cell(row=7, column=start_col, value=formula)
        val_cell.fill = fill(bg)
        val_cell.font = Font(name=DISPLAY_FONT, size=20, bold=True, color=fg)
        val_cell.alignment = Alignment(horizontal="center", vertical="center")
        val_cell.number_format = "#,##0"
        val_cell.border = BORDER_ALL
        ws.merge_cells(start_row=7, start_column=start_col, end_row=7, end_column=end_col)

    ws.row_dimensions[9].height = 22
    note = ws.cell(
        row=9,
        column=1,
        value=(
            "Singles (left) and Sealed (right) · Lists auto-compact — only items needing attention appear. "
            "Fix mismatches by updating PHYSICAL COUNT on the Singles Count or Sealed Count tab."
        ),
    )
    note.font = Font(name=BODY_FONT, size=10, italic=True, color=DEEP_GREEN)
    note.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    note.fill = fill(MINT_SOFT)
    ws.merge_cells(start_row=9, start_column=1, end_row=9, end_column=last_sheet_col)

    headers = [
        "Product",
        "Variant",
        "SKU",
        "System",
        "Physical",
        "Difference",
        "Status",
        "Notes",
    ]
    source_letters = ["D", "E", "F", "G", "H", "I", "J", "M"]

    SECTION_TITLE_ROW = 11

    def write_section(
        label: str, sheet_name: str, first_row: int, last_row: int, start_col: int
    ) -> None:
        end_col = start_col + len(headers) - 1
        helper_range = f"'{sheet_name}'!$N${first_row}:$N${last_row}"

        ws.row_dimensions[SECTION_TITLE_ROW].height = 26
        title_cell = ws.cell(
            row=SECTION_TITLE_ROW,
            column=start_col,
            value=f'="{label.upper()} — "&COUNT({helper_range})&" OPEN"',
        )
        title_cell.font = Font(name=DISPLAY_FONT, size=12, bold=True, color=WHITE)
        title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        title_cell.fill = fill(DEEP_GREEN)
        ws.merge_cells(
            start_row=SECTION_TITLE_ROW,
            start_column=start_col,
            end_row=SECTION_TITLE_ROW,
            end_column=end_col,
        )

        header_row = SECTION_TITLE_ROW + 1
        for i, h in enumerate(headers):
            ws.cell(row=header_row, column=start_col + i, value=h)
        style_header_row(ws, header_row, len(headers), start_column=start_col)

        first_slot = header_row + 1
        last_slot = first_slot + slots_per_section - 1
        for rr in range(first_slot, last_slot + 1):
            for off, src_letter in enumerate(source_letters):
                src_range = f"'{sheet_name}'!${src_letter}${first_row}:${src_letter}${last_row}"
                formula = (
                    f'=IFERROR(INDEX({src_range},SMALL({helper_range},ROW()-{first_slot - 1})),"")'
                )
                ws.cell(row=rr, column=start_col + off, value=formula)

        for rr in range(first_slot, last_slot + 1):
            ws.row_dimensions[rr].height = 30
            bg_color = "FFF9FAFB" if rr % 2 == 0 else WHITE
            for off in range(len(headers)):
                cc = start_col + off
                align = "left" if off in (0, 1, 7) else "center"
                cell = ws.cell(row=rr, column=cc)
                cell.fill = fill(bg_color)
                style_data_cell(cell, align=align, bold=(off == 6))
            ws.cell(row=rr, column=start_col + 3).number_format = "#,##0;-#,##0;0;@"
            ws.cell(row=rr, column=start_col + 4).number_format = "#,##0;-#,##0;0;@"
            ws.cell(row=rr, column=start_col + 5).number_format = "+#,##0;-#,##0;0;@"

        st_l = get_column_letter(start_col + 6)
        df_l = get_column_letter(start_col + 5)
        top_r = first_slot
        full_rng = (
            f"{get_column_letter(start_col)}{first_slot}:"
            f"{get_column_letter(end_col)}{last_slot}"
        )

        # Full-row color: red = missing / short / negative diff; green = over / surplus / OK.
        red_rule = FormulaRule(
            formula=[
                f'=AND(${st_l}{top_r}<>"",OR('
                f'ISNUMBER(SEARCH("MISSING",${st_l}{top_r})),'
                f'ISNUMBER(SEARCH("SHORT",${st_l}{top_r})),'
                f'IFERROR(${df_l}{top_r}<0,FALSE)))'
            ],
            fill=fill(DANGER_BG),
            font=Font(name=BODY_FONT, size=10, bold=True, color=DANGER_FG),
        )
        green_rule = FormulaRule(
            formula=[
                f'=AND(${st_l}{top_r}<>"",OR('
                f'ISNUMBER(SEARCH("OVER",${st_l}{top_r})),'
                f'ISNUMBER(SEARCH("OK - Match",${st_l}{top_r})),'
                f'IFERROR(${df_l}{top_r}>0,FALSE)))'
            ],
            fill=fill(SUCCESS_BG),
            font=Font(name=BODY_FONT, size=10, bold=True, color=SUCCESS_FG),
        )
        ws.conditional_formatting.add(full_rng, red_rule)
        ws.conditional_formatting.add(full_rng, green_rule)

    by_label = {lbl: (sn, fr, lr) for lbl, sn, fr, lr in sources}
    if "Single" in by_label:
        sn, fr, lr = by_label["Single"]
        write_section("Single", sn, fr, lr, SINGLES_START)
    if "Sealed" in by_label:
        sn, fr, lr = by_label["Sealed"]
        write_section("Sealed", sn, fr, lr, SEALED_START)

    data_start_row = SECTION_TITLE_ROW + 2
    ws.freeze_panes = f"A{data_start_row}"
    ws.sheet_properties.tabColor = "FFE0B4B4"


def _stat_tile(ws, row_label: int, col: int, *, label: str, value, bg: str, fg: str,
               is_formula: bool = False, fmt: str | None = None) -> None:
    """Render a labeled stat tile (label row + value row, 2 cols wide)."""
    row_value = row_label + 1
    ws.row_dimensions[row_label].height = 22
    ws.row_dimensions[row_value].height = 50

    label_cell = ws.cell(row=row_label, column=col, value=label)
    label_cell.fill = fill(MINT)
    label_cell.font = Font(name=BODY_FONT, size=10, bold=True, color=DEEP_GREEN)
    label_cell.alignment = Alignment(horizontal="center", vertical="center")
    label_cell.border = BORDER_ALL
    ws.merge_cells(start_row=row_label, start_column=col, end_row=row_label, end_column=col + 1)

    val_cell = ws.cell(row=row_value, column=col, value=value)
    val_cell.fill = fill(bg)
    val_cell.font = Font(name=DISPLAY_FONT, size=22, bold=True, color=fg)
    val_cell.alignment = Alignment(horizontal="center", vertical="center")
    val_cell.border = BORDER_ALL
    if fmt:
        val_cell.number_format = fmt
    elif is_formula:
        val_cell.number_format = "#,##0"
    ws.merge_cells(start_row=row_value, start_column=col, end_row=row_value, end_column=col + 1)


def _section_header(ws, row: int, col: int, span: int, label: str) -> None:
    ws.row_dimensions[row].height = 22
    cell = ws.cell(row=row, column=col, value=label)
    cell.fill = fill(DEEP_GREEN)
    cell.font = Font(name=BODY_FONT, size=11, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)


def build_dashboard(
    wb: Workbook,
    *,
    singles_sheet: str, singles_first: int, singles_last: int, singles_stocked: int,
    sealed_sheet: str, sealed_first: int, sealed_last: int, sealed_stocked: int,
    total_skus: int, logo: Path,
) -> None:
    ws = wb.create_sheet("Dashboard", 0)
    ws.sheet_view.showGridLines = False

    widths = [3, 22, 22, 22, 22, 22, 22, 3]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    banner(
        ws,
        "MINTED — INVENTORY LOG",
        f"Snapshot from Shopify · Lawrenceville · Updated {date.today():%B %d, %Y}",
        "H",
        logo,
    )

    # Welcome line
    ws.row_dimensions[6].height = 32
    ws.merge_cells("B6:G6")
    welcome = ws.cell(
        row=6,
        column=2,
        value=(
            "Singles Count = individual cards.  Sealed Count = booster boxes, ETBs, sleeves, etc. "
            "Type the shelf count into PHYSICAL COUNT and mismatches will appear below and on the Discrepancy Log."
        ),
    )
    welcome.font = Font(name=BODY_FONT, size=11, italic=True, color=DEEP_GREEN)
    welcome.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
    welcome.fill = fill(MINT_SOFT)

    # Overview row: snapshot totals
    _section_header(ws, 8, 2, 6, "OVERVIEW")
    _stat_tile(ws, 9, 2, label="TOTAL SKUS",      value=f"{total_skus:,}",        bg=DEEP_GREEN, fg=WHITE)
    _stat_tile(ws, 9, 4, label="ITEMS WITH STOCK", value=f"{singles_stocked + sealed_stocked:,}", bg=MINT, fg=DEEP_GREEN)
    _stat_tile(ws, 9, 6, label="SINGLES STOCKED",  value=f"{singles_stocked:,}",   bg=MINT, fg=DEEP_GREEN)

    def section(start_row: int, title: str, sheet: str, first: int, last: int) -> None:
        sheet_ref = f"'{sheet}'"
        status_range   = f"{sheet_ref}!J{first}:J{last}"
        physical_range = f"{sheet_ref}!H{first}:H{last}"
        system_range   = f"{sheet_ref}!G{first}:G{last}"

        _section_header(ws, start_row, 2, 6, title)
        # Row 1: Units in system, Units counted, Pending count
        _stat_tile(ws, start_row + 1, 2,
                   label="UNITS IN SYSTEM",
                   value=f"=SUM({system_range})", is_formula=True,
                   bg=DEEP_GREEN, fg=WHITE)
        _stat_tile(ws, start_row + 1, 4,
                   label="UNITS COUNTED",
                   value=f"=SUMIF({physical_range},\">=0\")", is_formula=True,
                   bg=MINT, fg=DEEP_GREEN)
        _stat_tile(ws, start_row + 1, 6,
                   label="PENDING COUNT",
                   value=f"=COUNTIF({status_range},\"Pending Count\")", is_formula=True,
                   bg="FFF4E5A8", fg=DEEP_GREEN)
        # Row 2: OK, Discrepancies, Missing
        _stat_tile(ws, start_row + 4, 2,
                   label="ITEMS OK",
                   value=f"=COUNTIF({status_range},\"OK - Match\")", is_formula=True,
                   bg=SUCCESS_BG, fg=SUCCESS_FG)
        _stat_tile(ws, start_row + 4, 4,
                   label="DISCREPANCIES",
                   value=f"=SUMPRODUCT(--ISNUMBER(SEARCH(\"Discrepancy\",{status_range})))", is_formula=True,
                   bg=DANGER_BG, fg=DANGER_FG)
        _stat_tile(ws, start_row + 4, 6,
                   label="MISSING ON SHELF",
                   value=f"=COUNTIF({status_range},\"MISSING - Out of Stock\")", is_formula=True,
                   bg=DANGER_BG, fg=DANGER_FG)

    section(13, "SINGLES",  singles_sheet, singles_first, singles_last)
    section(20, "SEALED & ACCESSORIES", sealed_sheet, sealed_first, sealed_last)

    legend_row = 28
    _section_header(ws, legend_row, 2, 6, "STATUS KEY")

    legend = [
        ("OK - Match",            "Physical count equals system on hand. No action needed.",        SUCCESS_BG, SUCCESS_FG),
        ("Pending Count",         "Item hasn't been counted yet. Type a number in Physical Count.", NEUTRAL_BG, "FF555555"),
        ("SHORT - Discrepancy",   "Physical count is LESS than system. Possible shrink.",           DANGER_BG,  DANGER_FG),
        ("OVER - Discrepancy",    "Physical count is MORE than system. Possible mis-receive.",      WARN_BG,    WARN_FG),
        ("MISSING - Out of Stock","System shows units but the shelf is empty.",                     DANGER_BG,  DANGER_FG),
    ]
    for i, (label, desc, bg, fg) in enumerate(legend):
        rr = legend_row + 1 + i
        ws.row_dimensions[rr].height = 20
        tag = ws.cell(row=rr, column=2, value=label)
        tag.fill = fill(bg)
        tag.font = Font(name=BODY_FONT, size=10, bold=True, color=fg)
        tag.alignment = Alignment(horizontal="center", vertical="center")
        tag.border = BORDER_ALL
        ws.merge_cells(start_row=rr, start_column=2, end_row=rr, end_column=3)
        desc_cell = ws.cell(row=rr, column=4, value=desc)
        desc_cell.font = Font(name=BODY_FONT, size=10, color=INK)
        desc_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        desc_cell.fill = fill(WHITE)
        desc_cell.border = BORDER_ALL
        ws.merge_cells(start_row=rr, start_column=4, end_row=rr, end_column=7)

    foot_row = legend_row + len(legend) + 3
    ws.merge_cells(start_row=foot_row, start_column=2, end_row=foot_row, end_column=7)
    foot = ws.cell(
        row=foot_row,
        column=2,
        value="Minted TCG · Internal use only · Refresh by re-exporting from Shopify and rerunning the builder.",
    )
    foot.font = Font(name=BODY_FONT, size=9, italic=True, color="FF666666")
    foot.alignment = Alignment(horizontal="left", vertical="center")

    ws.sheet_properties.tabColor = NEON[2:]


# --- Main ------------------------------------------------------------------

def build_workbook(
    csv_path: Path,
    output_path: Path,
    logo_path: Path | None = None,
    *,
    progress: Callable[[float, str], None] | None = None,
) -> dict:
    """Build the full Minted Inventory Log workbook from a Shopify CSV export.

    Args:
        csv_path:    Path to the Shopify inventory export CSV (any name).
        output_path: Where to save the resulting .xlsx workbook.
        logo_path:   Optional path to the Minted logo PNG; defaults to LOGO_PATH.
        progress:    Optional callback ``(fraction, message)`` with fraction in
                     ``[0, 1]`` for UIs (e.g. Streamlit progress bar).

    Returns:
        Dict with summary stats: {total, singles_stocked, sealed_stocked}.

    Raises:
        InvalidShopifyCsv: if the CSV doesn't match the expected Shopify schema.
    """
    def _p(frac: float, msg: str) -> None:
        if progress is not None:
            progress(max(0.0, min(1.0, frac)), msg)

    if logo_path is None:
        logo_path = LOGO_PATH

    print(f"Reading {csv_path} ...")
    _p(0.04, "Validating CSV…")
    validate_shopify_csv(csv_path)
    _p(0.10, "Reading rows from export (may take a bit)…")
    rows = load_rows(csv_path)
    total = len(rows)

    stocked_singles = [r for r in rows if r["on_hand"] > 0 and r["category"] == "Single"]
    stocked_sealed  = [r for r in rows if r["on_hand"] > 0 and r["category"] == "Sealed"]
    print(f"  {total:,} rows · {len(stocked_singles):,} singles stocked · {len(stocked_sealed):,} sealed stocked")

    _p(0.22, f"Organized {total:,} SKUs · building Singles Count…")
    wb = Workbook()
    wb.remove(wb.active)

    singles_name, singles_first, singles_last = build_active_inventory(
        wb, stocked_singles, logo_path,
        sheet_name="Singles Count",
        title="MINTED — SINGLES COUNT",
        subtitle="Individual cards · Count what's on the shelf · Mismatches flag automatically",
        tab_color="1B733D",
        table_name="SinglesCount",
        pad_rows=60,
    )
    print(f"  Built Singles Count ({singles_first}..{singles_last})")

    _p(0.42, "Building Sealed & accessories count…")
    sealed_name, sealed_first, sealed_last = build_active_inventory(
        wb, stocked_sealed, logo_path,
        sheet_name="Sealed Count",
        title="MINTED — SEALED & ACCESSORIES COUNT",
        subtitle="Booster boxes · ETBs · sleeves · accessories · count and flag",
        tab_color="0F5132",
        table_name="SealedCount",
        pad_rows=30,
    )
    print(f"  Built Sealed Count ({sealed_first}..{sealed_last})")

    _p(0.55, "Building Discrepancy Log…")
    build_discrepancy_log(
        wb,
        sources=[
            ("Single",  singles_name, singles_first, singles_last),
            ("Sealed",  sealed_name,  sealed_first,  sealed_last),
        ],
        logo=logo_path,
    )
    print("  Built Discrepancy Log")

    _p(0.62, "Building Full Catalog (largest step)…")
    build_full_catalog(wb, rows, logo_path)
    print("  Built Full Catalog")

    _p(0.90, "Building Dashboard…")
    build_dashboard(
        wb,
        singles_sheet=singles_name, singles_first=singles_first, singles_last=singles_last,
        singles_stocked=len(stocked_singles),
        sealed_sheet=sealed_name, sealed_first=sealed_first, sealed_last=sealed_last,
        sealed_stocked=len(stocked_sealed),
        total_skus=total, logo=logo_path,
    )
    print("  Built Dashboard")

    wb.properties.title = "Minted Inventory Log"
    wb.properties.creator = "Minted TCG"
    wb.properties.subject = "Inventory count & discrepancy tracker"
    wb.properties.keywords = "minted, inventory, count, discrepancy, shopify, singles, sealed"

    _p(0.96, "Saving workbook to disk…")
    print(f"Saving to {output_path} ...")
    wb.save(output_path)
    print("Done.")
    _p(1.0, "Finished.")

    return {
        "total": total,
        "singles_stocked": len(stocked_singles),
        "sealed_stocked": len(stocked_sealed),
    }


def main() -> None:
    csv_path = find_inventory_csv()
    out = OUTPUT_PATH
    if len(sys.argv) > 2:
        out = Path(sys.argv[2]).expanduser().resolve()
        if out.suffix.lower() != ".xlsx":
            out = out.with_suffix(".xlsx")
    build_workbook(csv_path, out)


if __name__ == "__main__":
    main()
