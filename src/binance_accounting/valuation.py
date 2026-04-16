"""Valuation layer — converts asset quantities to USD estimates."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from binance_accounting.binance_client import AssetBalance

logger = logging.getLogger(__name__)

# Coins pegged ~1:1 to USD — valued at $1.
STABLECOINS = frozenset({"USDT", "USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USD"})


@dataclass(slots=True)
class ValuedAsset:
    coin: str
    quantity: float
    usd_value: float
    price_usd: float
    account_type: str


def get_usd_price(coin: str, prices: dict[str, float]) -> float | None:
    """Return the USD-equivalent price for *coin*, or None if unavailable."""
    if coin in STABLECOINS:
        return 1.0

    # Direct USDT pair
    key = f"{coin}USDT"
    if key in prices:
        return prices[key]

    # Direct USDC pair
    key = f"{coin}USDC"
    if key in prices:
        return prices[key]

    # Via BTC → USDT
    btc_key = f"{coin}BTC"
    if btc_key in prices and "BTCUSDT" in prices:
        return prices[btc_key] * prices["BTCUSDT"]

    # Via ETH → USDT
    eth_key = f"{coin}ETH"
    if eth_key in prices and "ETHUSDT" in prices:
        return prices[eth_key] * prices["ETHUSDT"]

    return None


def value_assets(
    balances: list[AssetBalance],
    prices: dict[str, float],
    min_usd: float = 1.0,
) -> list[ValuedAsset]:
    """Attach a USD valuation to each balance entry.

    Assets whose USD value < *min_usd* are dropped (dust filter).
    Assets with no discoverable price are kept with usd_value=0.
    """
    result: list[ValuedAsset] = []
    for b in balances:
        price = get_usd_price(b.coin, prices)
        if price is None:
            logger.warning("No price found for %s — recording with $0", b.coin)
            price = 0.0
        usd_value = b.total * price
        if usd_value < min_usd and price > 0:
            continue  # dust
        result.append(
            ValuedAsset(
                coin=b.coin,
                quantity=b.total,
                usd_value=usd_value,
                price_usd=price,
                account_type=b.account_type,
            )
        )
    return result
