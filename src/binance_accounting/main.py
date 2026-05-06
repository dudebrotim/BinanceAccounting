"""Binance daily accounting — CLI entry point.

Usage:
    python -m binance_accounting              # normal run
    python -m binance_accounting --dry-run    # skip sheet upload
    python -m binance_accounting --config path/to/config.toml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tomllib
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from binance_accounting.binance_client import BinanceClient
from binance_accounting.valuation import value_assets
from binance_accounting.diff import build_snapshot_data, compute_diff
from binance_accounting.snapshot_store import SnapshotStore
from binance_accounting.sheets_writer import append_row

logger = logging.getLogger("binance_accounting")

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "config.toml"
TZ_TAIPEI = timezone(timedelta(hours=8))


# ── config loading ──────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    if not path.exists():
        logger.error("Config file not found: %s", path)
        sys.exit(1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve(cfg_value: str, env_key: str) -> str:
    """Return env var if set, else config value. Exit if both empty."""
    val = os.environ.get(env_key) or cfg_value
    if not val:
        logger.error("Missing %s (set env or config)", env_key)
        sys.exit(1)
    return val


# ── coin selection ──────────────────────────────────────────────────

def pick_tracked_coins(
    snapshot_data: dict, configured: list[str]
) -> list[str]:
    """If user configured coins, use those; otherwise include all coins in snapshot."""
    if configured:
        return configured
    return sorted(snapshot_data.get("assets", {}).keys())


def resolve_worksheet(today: date, google_cfg: dict) -> tuple[str, bool]:
    """Resolve worksheet name and whether weekly summary mode is enabled."""
    base = google_cfg.get("worksheet_name", "daily_assets")
    mode = str(google_cfg.get("worksheet_mode", "weekly")).strip().lower()
    if mode == "fixed":
        return base, False
    if mode != "weekly":
        logger.warning("Unknown google.worksheet_mode=%r, fallback to weekly", mode)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    return f"{base}_{week_start:%Y%m%d}_{week_end:%Y%m%d}", True


# ── main pipeline ───────────────────────────────────────────────────

def run(cfg: dict, dry_run: bool = False) -> None:
    today = datetime.now(TZ_TAIPEI).date()
    logger.info("=== Binance Accounting — %s ===", today.isoformat())

    # 1) Binance balances
    api_key = resolve(cfg.get("binance", {}).get("api_key", ""), "BINANCE_API_KEY")
    secret = resolve(cfg.get("binance", {}).get("secret_key", ""), "BINANCE_SECRET_KEY")
    client = BinanceClient(api_key, secret)

    try:
        balances = client.get_all_balances()
        prices = client.get_all_prices()
    finally:
        client.close()

    logger.info("Total raw balances: %d  |  Price pairs: %d", len(balances), len(prices))

    # 2) Valuation
    min_usd = cfg.get("settings", {}).get("min_usd_value", 0.0)
    valued = value_assets(balances, prices, min_usd=min_usd)
    logger.info("Valued assets (after dust filter): %d", len(valued))

    # 3) Build snapshot & save
    snapshot_data = build_snapshot_data(valued)
    snapshot_data["date"] = today.isoformat()
    snapshot_data["timestamp"] = datetime.now(TZ_TAIPEI).isoformat()

    data_dir = cfg.get("snapshot", {}).get("data_dir", "data")
    store = SnapshotStore(data_dir)
    store.save(today, snapshot_data)

    # 4) Diff with previous
    prev = store.load_previous(before=today)
    diff = compute_diff(snapshot_data, prev)
    logger.info(
        "Total USD: %.2f  |  Change: %s%.2f (%s)",
        diff.today_total_usd,
        "+" if diff.change_usd >= 0 else "",
        diff.change_usd,
        f"{diff.change_pct:+.2f}%" if diff.change_pct is not None else "first run",
    )

    # 5) Upload to Google Sheet
    if dry_run:
        logger.info("[DRY-RUN] Skipping Google Sheet upload")
        _print_summary(diff)
        return

    google_cfg = cfg.get("google", {})
    sa_path = resolve(google_cfg.get("service_account_path", ""), "GOOGLE_SERVICE_ACCOUNT_PATH")
    spreadsheet_id = google_cfg.get("spreadsheet_id", "")
    worksheet_name, weekly_summary = resolve_worksheet(today, google_cfg)

    if not spreadsheet_id:
        logger.error("Missing google.spreadsheet_id in config")
        sys.exit(1)

    tracked = pick_tracked_coins(
        snapshot_data,
        cfg.get("settings", {}).get("tracked_coins", []),
    )
    logger.info("Tracked coins for sheet: %s", ", ".join(tracked))

    append_row(
        sa_path=sa_path,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
        today=today,
        diff=diff,
        tracked_coins=tracked,
        weekly_summary=weekly_summary,
    )
    logger.info("Done — row appended to Google Sheet")


def _print_summary(diff) -> None:
    """Print a human-readable summary to stdout (used in dry-run)."""
    print(f"\n{'─' * 50}")
    print(f"  Total USD:     ${diff.today_total_usd:>14,.2f}")
    print(f"  Change USD:    ${diff.change_usd:>+14,.2f}")
    if diff.change_pct is not None:
        print(f"  Change %:       {diff.change_pct:>+13.2f}%")
    print(f"  Spot USD:      ${diff.today_spot_usd:>14,.2f}")
    print(f"  Funding USD:   ${diff.today_funding_usd:>14,.2f}")
    print(f"  Futures USD:   ${diff.today_futures_usd:>14,.2f}")
    print(f"{'─' * 50}")
    print("  Top coins:")
    ranked = sorted(diff.coins.values(), key=lambda c: c.today_usd, reverse=True)
    for c in ranked[:15]:
        if c.today_usd < 1:
            continue
        chg = f"({c.usd_change:+.2f})" if c.prev_usd > 0 else "(new)"
        print(f"    {c.coin:<8s}  qty={c.today_qty:<16.8f}  ${c.today_usd:>12,.2f}  {chg}")
    print(f"{'─' * 50}\n")


# ── CLI ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Binance daily accounting")
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to config TOML (default: config/config.toml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch & snapshot only, skip Google Sheet upload",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    cfg = load_config(args.config)

    try:
        run(cfg, dry_run=args.dry_run)
    except Exception:
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
