"""Google Sheets writer — appends a daily summary row."""

from __future__ import annotations

import logging
from datetime import date

import gspread
from google.oauth2.service_account import Credentials

from binance_accounting.diff import SummaryDiff

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]
DEFAULT_SHEET_COLS = 200

# Fixed header columns (always present)
FIXED_HEADERS = [
    "Date",
    "Total_USD",
    "Change_USD",
    "Change_%",
    "Spot_USD",
    "Funding_USD",
    "Futures_USD",
]


def _connect(sa_path: str, spreadsheet_id: str, worksheet_name: str):
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=DEFAULT_SHEET_COLS)
        logger.info("Created new worksheet: %s", worksheet_name)
    return ws


def _build_coin_headers(tracked_coins: list[str]) -> list[str]:
    """Generate per-coin header pairs: COIN_qty, COIN_usd, COIN_qty_chg, COIN_usd_chg."""
    headers: list[str] = []
    for c in tracked_coins:
        headers.extend([
            f"{c}_qty",
            f"{c}_usd",
            f"{c}_qty_chg",
            f"{c}_usd_chg",
        ])
    return headers


def _ensure_headers(ws, tracked_coins: list[str]) -> list[str]:
    """Make sure the header row exists and includes columns for all tracked coins."""
    coin_headers = _build_coin_headers(tracked_coins)
    full_headers = FIXED_HEADERS + coin_headers + ["Notes"]
    required_cols = len(full_headers)

    if ws.col_count < required_cols:
        ws.add_cols(required_cols - ws.col_count)
        logger.info("Expanded worksheet columns to %d", ws.col_count)

    existing = ws.row_values(1) if ws.row_count > 0 else []
    if not existing:
        ws.update(range_name="A1", values=[full_headers])
        logger.info("Wrote header row (%d cols)", len(full_headers))
        return full_headers

    # Check if we need to extend headers (new coins)
    if existing != full_headers:
        ws.update(range_name="A1", values=[full_headers])
        logger.info("Updated header row (%d cols)", len(full_headers))
    return full_headers


def _fmt(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def append_row(
    sa_path: str,
    spreadsheet_id: str,
    worksheet_name: str,
    today: date,
    diff: SummaryDiff,
    tracked_coins: list[str],
    notes: str = "",
) -> None:
    """Append one summary row to the Google Sheet."""
    ws = _connect(sa_path, spreadsheet_id, worksheet_name)
    _ensure_headers(ws, tracked_coins)

    row: list[str] = [
        today.isoformat(),
        _fmt(diff.today_total_usd),
        _fmt(diff.change_usd),
        _fmt(diff.change_pct) if diff.change_pct is not None else "N/A (first)",
        _fmt(diff.today_spot_usd),
        _fmt(diff.today_funding_usd),
        _fmt(diff.today_futures_usd),
    ]

    # Per-coin columns
    for coin in tracked_coins:
        cd = diff.coins.get(coin)
        if cd:
            row.extend([
                _fmt(cd.today_qty, 8),
                _fmt(cd.today_usd),
                _fmt(cd.qty_change, 8),
                _fmt(cd.usd_change),
            ])
        else:
            row.extend(["0", "0", "0", "0"])

    row.append(notes)

    ws.append_row(row, value_input_option="USER_ENTERED")
    logger.info("Appended row for %s to sheet", today.isoformat())
