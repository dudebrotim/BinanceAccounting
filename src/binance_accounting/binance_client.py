"""Binance API client — fetches Spot, Funding, Futures, and Earn balances."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"

REQUEST_TIMEOUT = 30
RECV_WINDOW = 5000


@dataclass(slots=True)
class AssetBalance:
    """A single asset balance entry."""

    coin: str
    free: float
    locked: float
    total: float
    account_type: str  # "spot" | "funding" | "futures" | "earn"


class BinanceClient:
    """Thin wrapper around Binance REST endpoints for balance queries."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._http = httpx.Client(timeout=REQUEST_TIMEOUT)

    # ── authentication ──────────────────────────────────────────────

    def _sign(self, params: dict | None = None) -> dict:
        params = dict(params) if params else {}
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = RECV_WINDOW
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(
            self._secret_key.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key}

    def _iter_simple_earn_positions(self, endpoint: str, page_size: int = 100) -> list[dict]:
        """Fetch all paginated Simple Earn positions from a signed sapi endpoint."""
        rows: list[dict] = []
        current = 1
        total: int | None = None
        while True:
            params = self._sign({"current": current, "size": page_size})
            resp = self._http.get(
                f"{SPOT_BASE}{endpoint}",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
            page_rows = payload.get("rows", [])
            rows.extend(page_rows)
            if total is None:
                total = int(payload.get("total", 0))
            if not page_rows or len(rows) >= total:
                break
            current += 1
        return rows

    @staticmethod
    def _extract_earn_amount(position: dict) -> float:
        for key in ("totalAmount", "amount", "holdingAmount"):
            raw = position.get(key)
            if raw is not None:
                return float(raw)
        return 0.0

    # ── spot ────────────────────────────────────────────────────────

    def get_spot_balances(self) -> list[AssetBalance]:
        params = self._sign()
        resp = self._http.get(
            f"{SPOT_BASE}/api/v3/account",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        result: list[AssetBalance] = []
        for b in data["balances"]:
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            if total > 0:
                result.append(
                    AssetBalance(b["asset"], free, locked, total, "spot")
                )
        logger.info("Spot: fetched %d non-zero assets", len(result))
        return result

    # ── funding ─────────────────────────────────────────────────────

    def get_funding_balances(self) -> list[AssetBalance]:
        params = self._sign()
        resp = self._http.post(
            f"{SPOT_BASE}/sapi/v1/asset/get-funding-asset",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        result: list[AssetBalance] = []
        for b in data:
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            freeze = float(b.get("freeze", 0))
            total = free + locked + freeze
            if total > 0:
                result.append(
                    AssetBalance(b["asset"], free, locked + freeze, total, "funding")
                )
        logger.info("Funding: fetched %d non-zero assets", len(result))
        return result

    # ── futures (USDT-M) ────────────────────────────────────────────

    def get_futures_balances(self) -> list[AssetBalance]:
        params = self._sign()
        resp = self._http.get(
            f"{FUTURES_BASE}/fapi/v3/balance",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        result: list[AssetBalance] = []
        for b in data:
            balance = float(b.get("balance", 0))
            available = float(b.get("availableBalance", 0))
            if abs(balance) > 0:
                result.append(
                    AssetBalance(
                        b["asset"], available, balance - available, balance, "futures"
                    )
                )
        logger.info("Futures: fetched %d non-zero assets", len(result))
        return result

    # ── simple earn (flexible + locked) ──────────────────────────────

    def get_earn_balances(self) -> list[AssetBalance]:
        result: list[AssetBalance] = []

        flexible_rows = self._iter_simple_earn_positions("/sapi/v1/simple-earn/flexible/position")
        for p in flexible_rows:
            amount = self._extract_earn_amount(p)
            if amount <= 0:
                continue
            asset = p.get("asset")
            if not asset:
                continue
            result.append(AssetBalance(asset, 0.0, amount, amount, "earn"))

        locked_rows = self._iter_simple_earn_positions("/sapi/v1/simple-earn/locked/position")
        for p in locked_rows:
            amount = self._extract_earn_amount(p)
            if amount <= 0:
                continue
            asset = p.get("asset")
            if not asset:
                continue
            result.append(AssetBalance(asset, 0.0, amount, amount, "earn"))

        logger.info("Earn: fetched %d non-zero positions", len(result))
        return result

    # ── prices ──────────────────────────────────────────────────────

    def get_all_prices(self) -> dict[str, float]:
        resp = self._http.get(f"{SPOT_BASE}/api/v3/ticker/price")
        resp.raise_for_status()
        return {p["symbol"]: float(p["price"]) for p in resp.json()}

    # ── aggregate ───────────────────────────────────────────────────

    def get_all_balances(self) -> list[AssetBalance]:
        spot = self.get_spot_balances()
        funding = self.get_funding_balances()
        futures = self.get_futures_balances()
        earn = self.get_earn_balances()
        return spot + funding + futures + earn

    def close(self) -> None:
        self._http.close()
