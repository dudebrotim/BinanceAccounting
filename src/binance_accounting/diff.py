"""Diff layer — computes daily changes in quantity and USD value."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CoinDiff:
    coin: str
    today_qty: float
    prev_qty: float
    qty_change: float
    today_usd: float
    prev_usd: float
    usd_change: float
    usd_change_pct: float | None  # None when prev was 0


@dataclass(slots=True)
class SummaryDiff:
    today_total_usd: float
    prev_total_usd: float
    change_usd: float
    change_pct: float | None
    today_spot_usd: float
    today_funding_usd: float
    today_futures_usd: float
    coins: dict[str, CoinDiff]


def _pct(new: float, old: float) -> float | None:
    if old == 0:
        return None
    return (new - old) / abs(old) * 100


def build_snapshot_data(valued_assets: list) -> dict:
    """Convert a list of ValuedAsset into the JSON-serialisable snapshot dict."""
    assets: dict[str, dict] = {}
    total_usd = 0.0
    by_account = {"spot": 0.0, "funding": 0.0, "futures": 0.0}

    for va in valued_assets:
        total_usd += va.usd_value
        by_account[va.account_type] = by_account.get(va.account_type, 0) + va.usd_value

        if va.coin not in assets:
            assets[va.coin] = {
                "quantity": 0.0,
                "usd_value": 0.0,
                "price_usd": va.price_usd,
                "by_account": {},
            }
        entry = assets[va.coin]
        entry["quantity"] += va.quantity
        entry["usd_value"] += va.usd_value
        entry["by_account"][va.account_type] = {
            "quantity": va.quantity,
            "usd_value": va.usd_value,
        }

    return {
        "total_usd": total_usd,
        "by_account": by_account,
        "assets": assets,
    }


def compute_diff(today: dict, yesterday: dict | None) -> SummaryDiff:
    """Compare today's snapshot with yesterday's.

    If *yesterday* is None (first run), all "prev" fields are zero.
    """
    t_total = today["total_usd"]
    t_spot = today["by_account"].get("spot", 0)
    t_fund = today["by_account"].get("funding", 0)
    t_fut = today["by_account"].get("futures", 0)

    y_total = yesterday["total_usd"] if yesterday else 0
    y_assets = yesterday.get("assets", {}) if yesterday else {}

    # Per-coin diff
    all_coins = set(today.get("assets", {})) | set(y_assets)
    coins: dict[str, CoinDiff] = {}
    for coin in sorted(all_coins):
        t = today.get("assets", {}).get(coin, {})
        y = y_assets.get(coin, {})
        tq = t.get("quantity", 0)
        yq = y.get("quantity", 0)
        tu = t.get("usd_value", 0)
        yu = y.get("usd_value", 0)
        coins[coin] = CoinDiff(
            coin=coin,
            today_qty=tq,
            prev_qty=yq,
            qty_change=tq - yq,
            today_usd=tu,
            prev_usd=yu,
            usd_change=tu - yu,
            usd_change_pct=_pct(tu, yu),
        )

    return SummaryDiff(
        today_total_usd=t_total,
        prev_total_usd=y_total,
        change_usd=t_total - y_total,
        change_pct=_pct(t_total, y_total),
        today_spot_usd=t_spot,
        today_funding_usd=t_fund,
        today_futures_usd=t_fut,
        coins=coins,
    )
