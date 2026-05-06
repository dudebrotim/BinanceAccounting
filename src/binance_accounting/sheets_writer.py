"""Google Sheets writer — writes weekly matrix-style records."""

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
SUMMARY_HEADER_ROW = 1
TOKEN_HEADER_ROW = 9
TOKEN_FIXED_COLS = 4

SUMMARY_METRICS = [
    ("Total_USD", lambda d: _fmt(d.today_total_usd)),
    ("Change_USD", lambda d: _fmt(d.change_usd)),
    ("Change_%", lambda d: _fmt(d.change_pct) if d.change_pct is not None else "N/A (first)"),
    ("Spot_USD", lambda d: _fmt(d.today_spot_usd)),
    ("Funding_USD", lambda d: _fmt(d.today_funding_usd)),
    ("Futures_USD", lambda d: _fmt(d.today_futures_usd)),
    ("Earn_USD", lambda d: _fmt(d.today_earn_usd)),
]


def _connect(sa_path: str, spreadsheet_id: str, worksheet_name: str):
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=worksheet_name,
            rows=1000,
            cols=DEFAULT_SHEET_COLS,
            index=0,
        )
        logger.info("Created new worksheet: %s", worksheet_name)
    return ws


def _fmt(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def _col_to_a1(n: int) -> str:
    """1-based column index to A1 notation column letters."""
    letters: list[str] = []
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(65 + rem))
    return "".join(reversed(letters))


def _ensure_col_count(ws, required_cols: int) -> None:
    if ws.col_count < required_cols:
        ws.add_cols(required_cols - ws.col_count)
        logger.info("Expanded worksheet columns to %d", ws.col_count)


def _ensure_row_count(ws, required_rows: int) -> None:
    if ws.row_count < required_rows:
        ws.add_rows(required_rows - ws.row_count)
        logger.info("Expanded worksheet rows to %d", ws.row_count)


def _find_or_create_date_col(ws, header_row: int, fixed_cols: int, date_label: str) -> int:
    row = ws.row_values(header_row)
    for idx in range(fixed_cols + 1, len(row) + 1):
        if row[idx - 1] == date_label:
            return idx
    date_col = max(len(row) + 1, fixed_cols + 1)
    _ensure_col_count(ws, date_col)
    ws.update(
        range_name=f"{_col_to_a1(date_col)}{header_row}",
        values=[[date_label]],
        value_input_option="USER_ENTERED",
    )
    return date_col


def _write_summary_block(ws, diff: SummaryDiff, date_col: int) -> None:
    _ensure_row_count(ws, 2 + len(SUMMARY_METRICS))
    ws.update(range_name="A1", values=[["Metric"]], value_input_option="USER_ENTERED")

    names = [[name] for name, _ in SUMMARY_METRICS]
    ws.update(
        range_name=f"A2:A{1 + len(SUMMARY_METRICS)}",
        values=names,
        value_input_option="USER_ENTERED",
    )

    values = [[formatter(diff)] for _, formatter in SUMMARY_METRICS]
    ws.update(
        range_name=f"{_col_to_a1(date_col)}2:{_col_to_a1(date_col)}{1 + len(SUMMARY_METRICS)}",
        values=values,
        value_input_option="USER_ENTERED",
    )


def _write_token_matrix(
    ws,
    date_col: int,
    diff: SummaryDiff,
    tracked_coins: list[str],
) -> None:
    _ensure_row_count(ws, TOKEN_HEADER_ROW)
    header = ["Token", "Price_USD", "Qty_Change", "USD_Change"]
    ws.update(
        range_name=f"A{TOKEN_HEADER_ROW}:{_col_to_a1(TOKEN_FIXED_COLS)}{TOKEN_HEADER_ROW}",
        values=[header],
        value_input_option="USER_ENTERED",
    )

    existing = ws.get_all_values()
    existing_rows: dict[str, list[str]] = {}
    for row in existing[TOKEN_HEADER_ROW:]:
        if not row or not row[0]:
            continue
        existing_rows[row[0]] = row

    coins = sorted(set(existing_rows.keys()) | set(tracked_coins))
    if not coins:
        return

    required_cols = max(date_col, TOKEN_FIXED_COLS)
    rows: list[list[str]] = []
    for coin in coins:
        cd = diff.coins.get(coin)
        base = list(existing_rows.get(coin, []))
        if len(base) < required_cols:
            base.extend([""] * (required_cols - len(base)))
        base[0] = coin
        if cd:
            price = cd.today_usd / cd.today_qty if cd.today_qty else 0.0
            base[1] = _fmt(price, 8)
            base[2] = _fmt(cd.qty_change, 8)
            base[3] = _fmt(cd.usd_change)
            base[date_col - 1] = _fmt(cd.today_qty, 8)
        rows.append(base)

    start_row = TOKEN_HEADER_ROW + 1
    end_row = start_row + len(rows) - 1
    _ensure_row_count(ws, end_row)
    _ensure_col_count(ws, required_cols)
    ws.update(
        range_name=f"A{start_row}:{_col_to_a1(required_cols)}{end_row}",
        values=rows,
        value_input_option="USER_ENTERED",
    )


def append_row(
    sa_path: str,
    spreadsheet_id: str,
    worksheet_name: str,
    today: date,
    diff: SummaryDiff,
    tracked_coins: list[str],
    notes: str = "",
    weekly_summary: bool = False,
) -> None:
    """Write daily values into a weekly matrix worksheet."""
    ws = _connect(sa_path, spreadsheet_id, worksheet_name)
    date_label = today.strftime("%m/%d")

    summary_date_col = _find_or_create_date_col(
        ws, header_row=SUMMARY_HEADER_ROW, fixed_cols=1, date_label=date_label
    )
    token_date_col = _find_or_create_date_col(
        ws, header_row=TOKEN_HEADER_ROW, fixed_cols=TOKEN_FIXED_COLS, date_label=date_label
    )

    _write_summary_block(ws, diff, summary_date_col)
    _write_token_matrix(ws, token_date_col, diff, tracked_coins)
    logger.info("Updated worksheet for %s (%s)", today.isoformat(), worksheet_name)
