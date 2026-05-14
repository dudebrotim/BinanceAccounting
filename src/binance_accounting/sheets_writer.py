"""Google Sheets writer — writes legacy weekly table style."""

from __future__ import annotations

import logging
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

from binance_accounting.diff import SummaryDiff

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]
DEFAULT_SHEET_COLS = 200
LEGACY_HEADER = [
    "Token",
    "Fixed Rate",
    "Spot Rate",
    "",
    "Prev Qty",
    "(CEX/DEX)",
]
LEGACY_TAIL = ["Weekly", "Spot Value Diff"]
TOKEN_START_ROW = 2
SECTION_ORDER = [
    "Margin",
    "Staking",
    "Chain/Cex",
    "Loan",
    "Short without profit",
    "Limit Order (Recovery)",
]
RESERVED_ROW_KEYS = {"Token"}
SPECIAL_HIGHLIGHT_TOKENS = {"BNB", "USDT"}
SECTION_COLORS = {
    "Token": {"red": 0.86, "green": 0.92, "blue": 0.98},
    "Margin": {"red": 1.0, "green": 0.95, "blue": 0.8},
    "Staking": {"red": 0.88, "green": 0.96, "blue": 0.88},
    "Chain/Cex": {"red": 0.94, "green": 0.89, "blue": 0.98},
    "Loan": {"red": 1.0, "green": 0.9, "blue": 0.85},
    "Short without profit": {"red": 0.99, "green": 0.86, "blue": 0.86},
    "Limit Order (Recovery)": {"red": 0.86, "green": 0.97, "blue": 0.97},
}
SPECIAL_TOKEN_COLOR = {"red": 1.0, "green": 0.93, "blue": 0.75}


def _connect(
    sa_path: str,
    spreadsheet_id: str,
    worksheet_name: str,
    template_worksheet: str = "",
):
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        if template_worksheet:
            try:
                template_ws = sh.worksheet(template_worksheet)
                ws = sh.duplicate_sheet(
                    source_sheet_id=template_ws.id,
                    insert_sheet_index=0,
                    new_sheet_name=worksheet_name,
                )
                logger.info(
                    "Created new worksheet from template: %s <- %s",
                    worksheet_name,
                    template_worksheet,
                )
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(
                    title=worksheet_name,
                    rows=1000,
                    cols=DEFAULT_SHEET_COLS,
                    index=0,
                )
                logger.warning(
                    "Template worksheet %r not found; created blank worksheet %s",
                    template_worksheet,
                    worksheet_name,
                )
        else:
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


def _week_day_labels(today: date) -> list[str]:
    week_start = today - timedelta(days=today.weekday())
    return [
        f"{(week_start + timedelta(days=i)).month}/{(week_start + timedelta(days=i)).day}"
        for i in range(7)
    ]


def _header_row(today: date) -> list[str]:
    return LEGACY_HEADER + _week_day_labels(today) + LEGACY_TAIL


def _write_legacy_weekly_table(
    ws,
    today: date,
    diff: SummaryDiff,
    tracked_coins: list[str],
) -> None:
    header = _header_row(today)
    current_col = 7 + today.weekday()  # G=Mon ... M=Sun
    required_cols = len(header)
    _ensure_col_count(ws, required_cols)
    ws.update(
        range_name=f"A1:{_col_to_a1(required_cols)}1",
        values=[header],
        value_input_option="USER_ENTERED",
    )

    existing = ws.get_all_values()
    existing_rows: dict[str, list[str]] = {}
    for row in existing[TOKEN_START_ROW - 1 :]:
        if not row or not row[0]:
            continue
        if row[0] in RESERVED_ROW_KEYS:
            continue
        if row[0] in SECTION_ORDER:
            continue
        existing_rows[row[0]] = row

    coins = sorted(set(existing_rows.keys()) | set(tracked_coins))
    token_coins = [c for c in coins if not c.startswith("LD")]
    staking_coins = [c for c in coins if c.startswith("LD")]

    rows: list[list[str]] = []
    row_styles: list[tuple[int, str, str | None]] = []
    day_col = _col_to_a1(current_col)
    row_idx = TOKEN_START_ROW

    for coin in token_coins:
        cd = diff.coins.get(coin)
        prev = existing_rows.get(coin, [])
        row = [""] * required_cols
        row[0] = coin
        row[3] = ""
        row[5] = coin
        if len(prev) > 1:
            row[1] = prev[1]

        if cd:
            price = cd.today_usd / cd.today_qty if cd.today_qty else 0.0
            row[2] = _fmt(price, 8)
            row[4] = _fmt(cd.prev_qty, 8)
            row[current_col - 1] = _fmt(cd.today_qty, 8)
            row[13] = f'=IF(OR(E{row_idx}="",{day_col}{row_idx}=""),"",{day_col}{row_idx}-E{row_idx})'
            row[14] = f'=IF(OR(N{row_idx}="",C{row_idx}=""),"",N{row_idx}*C{row_idx})'

        rows.append(row[:required_cols])
        row_styles.append((row_idx, "token", coin))
        row_idx += 1

    for section_name in SECTION_ORDER:
        section_row = [""] * required_cols
        section_row[0] = section_name
        rows.append(section_row)
        row_styles.append((row_idx, "section", section_name))
        row_idx += 1

        if section_name == "Staking":
            section_coins = staking_coins
        else:
            section_coins = []

        for coin in section_coins:
            cd = diff.coins.get(coin)
            prev = existing_rows.get(coin, [])
            row = [""] * required_cols
            row[0] = coin
            row[3] = ""
            row[5] = coin[2:] if coin.startswith("LD") and len(coin) > 2 else coin
            if len(prev) > 1:
                row[1] = prev[1]

            if cd:
                price = cd.today_usd / cd.today_qty if cd.today_qty else 0.0
                row[2] = _fmt(price, 8)
                row[4] = _fmt(cd.prev_qty, 8)
                row[current_col - 1] = _fmt(cd.today_qty, 8)
                row[13] = f'=IF(OR(E{row_idx}="",{day_col}{row_idx}=""),"",{day_col}{row_idx}-E{row_idx})'
                row[14] = f'=IF(OR(N{row_idx}="",C{row_idx}=""),"",N{row_idx}*C{row_idx})'

            rows.append(row[:required_cols])
            row_styles.append((row_idx, "token", coin))
            row_idx += 1

    start_row = TOKEN_START_ROW
    end_row = start_row + len(rows) - 1
    _ensure_row_count(ws, end_row)
    ws.batch_clear([f"A{start_row}:{_col_to_a1(required_cols)}1000"])
    ws.update(
        range_name=f"A{start_row}:{_col_to_a1(required_cols)}{end_row}",
        values=rows,
        value_input_option="USER_ENTERED",
    )
    _apply_row_styles(ws, row_styles, required_cols)
    return required_cols


def _apply_row_styles(ws, row_styles: list[tuple[int, str, str | None]], required_cols: int) -> None:
    requests: list[dict] = [
        {
            "unmergeCells": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": required_cols,
                }
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": 1,
                    "endRowIndex": 1000,
                    "startColumnIndex": 0,
                    "endColumnIndex": required_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                        "textFormat": {
                            "bold": False,
                            "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                        },
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor)",
            }
        }
    ]
    for row_idx, row_type, key in row_styles:
        if row_type == "section" and key:
            color = SECTION_COLORS.get(key)
            if color:
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": row_idx - 1,
                                "endRowIndex": row_idx,
                                "startColumnIndex": 0,
                                "endColumnIndex": required_cols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color,
                                    "textFormat": {
                                        "bold": True,
                                        "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                                    },
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor)",
                        }
                    }
                )

        if row_type == "token" and key in SPECIAL_HIGHLIGHT_TOKENS:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": row_idx - 1,
                            "endRowIndex": row_idx,
                            "startColumnIndex": 0,
                            "endColumnIndex": required_cols,
                        },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": SPECIAL_TOKEN_COLOR,
                                    "textFormat": {
                                        "bold": True,
                                        "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                                    },
                                }
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold,textFormat.foregroundColor)",
                        }
                    }
                )
    if requests:
        ws.spreadsheet.batch_update({"requests": requests})


def _copy_header_format_from_template(
    ws,
    template_worksheet: str,
    required_cols: int,
) -> None:
    if not template_worksheet:
        return
    try:
        template_ws = ws.spreadsheet.worksheet(template_worksheet)
    except gspread.WorksheetNotFound:
        logger.warning("Template worksheet %r not found for header format copy", template_worksheet)
        return
    ws.spreadsheet.batch_update(
        {
            "requests": [
                {
                    "copyPaste": {
                        "source": {
                            "sheetId": template_ws.id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": required_cols,
                        },
                        "destination": {
                            "sheetId": ws.id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": required_cols,
                        },
                        "pasteType": "PASTE_FORMAT",
                        "pasteOrientation": "NORMAL",
                    }
                }
            ]
        }
    )


def _repair_sparse_token_rows(
    ws,
    diff: SummaryDiff,
    current_col: int,
    required_cols: int,
) -> None:
    day_col = _col_to_a1(current_col)
    values = ws.get(f"A{TOKEN_START_ROW}:{_col_to_a1(required_cols)}1000")
    updates: list[tuple[str, list[str]]] = []
    for offset, row in enumerate(values, start=TOKEN_START_ROW):
        if not row:
            continue
        token = row[0]
        if not token or token in RESERVED_ROW_KEYS or token in SECTION_ORDER:
            continue
        if len(row) > 1:
            continue
        cd = diff.coins.get(token)
        if not cd:
            continue
        patched = [""] * required_cols
        patched[0] = token
        patched[3] = ""
        patched[5] = token[2:] if token.startswith("LD") and len(token) > 2 else token
        price = cd.today_usd / cd.today_qty if cd.today_qty else 0.0
        patched[2] = _fmt(price, 8)
        patched[4] = _fmt(cd.prev_qty, 8)
        patched[current_col - 1] = _fmt(cd.today_qty, 8)
        patched[13] = f'=IF(OR(E{offset}="",{day_col}{offset}=""),"",{day_col}{offset}-E{offset})'
        patched[14] = f'=IF(OR(N{offset}="",C{offset}=""),"",N{offset}*C{offset})'
        updates.append((f"A{offset}:{_col_to_a1(required_cols)}{offset}", patched))
    for rng, row in updates:
        ws.update(range_name=rng, values=[row], value_input_option="USER_ENTERED")
    if updates:
        logger.info("Repaired sparse rows: %s", ", ".join(r for r, _ in updates))


def append_row(
    sa_path: str,
    spreadsheet_id: str,
    worksheet_name: str,
    today: date,
    diff: SummaryDiff,
    tracked_coins: list[str],
    template_worksheet: str = "",
    notes: str = "",
    weekly_summary: bool = False,
) -> None:
    """Write daily values into legacy weekly table format."""
    ws = _connect(sa_path, spreadsheet_id, worksheet_name, template_worksheet)
    required_cols = _write_legacy_weekly_table(ws, today, diff, tracked_coins)
    _copy_header_format_from_template(ws, template_worksheet, required_cols)
    _repair_sparse_token_rows(ws, diff, 7 + today.weekday(), required_cols)
    logger.info("Updated worksheet for %s (%s)", today.isoformat(), worksheet_name)
