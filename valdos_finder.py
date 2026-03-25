#!/usr/bin/env python3
"""
Valdo's Map Profit Calculator
==============================
Identifies the highest-margin Valdo's Maps currently listed on the Path of
Exile trade market by comparing:

  - The asking price of each Valdo's Map listing (from the official PoE Trade API).
  - The current market value of the contained reward item (from poe.ninja).

Profit = Reward Item Price (chaos) - Map Listing Price (chaos)

Usage
-----
    python valdos_finder.py --league "Settlers" [--include-void] \\
                            [--session-id POESESSID] [--max-results 100]

    # Or export your session ID as an environment variable:
    export POE_SESSION_ID="your_poesessid_here"
    python valdos_finder.py --league "Settlers"

Obtaining a POESESSID
---------------------
The PoE Official Trade API requires an authenticated session for reliable
access.  To get your POESESSID:

  1. Open https://www.pathofexile.com and log in.
  2. Open your browser's Developer Tools (F12).
  3. Go to Application → Cookies → https://www.pathofexile.com.
  4. Copy the value next to ``POESESSID``.
  5. Pass it via ``--session-id`` or set the ``POE_SESSION_ID`` environment
     variable.

  Keep this value secret – it is equivalent to your login session.

Rate Limiting
-------------
GGG's trade API enforces strict rate limits.  This script uses a decorator
and per-request ``time.sleep()`` calls to stay well within the published
limits (https://www.pathofexile.com/developer/docs/rate-limiting).
"""

import argparse
import os
import re
import time
from functools import wraps
from typing import Optional

import pandas as pd
import requests
from tabulate import tabulate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# poe.ninja item-overview endpoint
# Docs: https://poe.ninja/  (unofficial; widely used in the PoE community)
POE_NINJA_BASE = "https://poe.ninja/api/data/itemoverview"

# poe.ninja currency-overview endpoint (for the divine-to-chaos rate)
POE_NINJA_CURRENCY = "https://poe.ninja/api/data/currencyoverview"

# PoE Official Trade API endpoints
# Docs: https://www.pathofexile.com/developer/docs/trade
POE_TRADE_SEARCH = "https://www.pathofexile.com/api/trade/search/{league}"
POE_TRADE_FETCH = "https://www.pathofexile.com/api/trade/fetch/{ids}"

# Item categories to pull from poe.ninja for reward price lookups
NINJA_CATEGORIES = [
    "UniqueWeapon",
    "UniqueArmour",
    "UniqueAccessory",
    "UniqueFlask",
    "UniqueJewel",
]

# Conservative rate-limit delays (seconds).
# GGG's published policy: max 12 searches / 60 s, 10 fetches / 10 s.
SEARCH_DELAY = 6.0    # seconds between search POSTs
FETCH_DELAY = 1.2     # seconds between fetch GETs
NINJA_DELAY = 0.5     # courtesy delay between poe.ninja requests

FETCH_BATCH_SIZE = 10  # trade API fetch endpoint accepts up to 10 IDs at once

# ---------------------------------------------------------------------------
# Rate-limiting decorator
# ---------------------------------------------------------------------------


def rate_limited(delay: float):
    """Enforce a minimum *delay* (seconds) between successive calls to *fn*."""
    def decorator(fn):
        last_called: list[float] = [0.0]

        @wraps(fn)
        def wrapper(*args, **kwargs):
            elapsed = time.monotonic() - last_called[0]
            wait = delay - elapsed
            if wait > 0:
                time.sleep(wait)
            result = fn(*args, **kwargs)
            last_called[0] = time.monotonic()
            return result

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# poe.ninja helpers
# ---------------------------------------------------------------------------


def fetch_divine_price(league: str) -> float:
    """Return the current Divine Orb → Chaos Orb exchange rate from poe.ninja.

    Endpoint::

        GET https://poe.ninja/api/data/currencyoverview?league=<league>&type=Currency

    Falls back to 200 c if the request fails.
    """
    params = {"league": league, "type": "Currency"}
    try:
        resp = requests.get(POE_NINJA_CURRENCY, params=params, timeout=10)
        resp.raise_for_status()
        for line in resp.json().get("lines", []):
            if line.get("currencyTypeName", "").lower() == "divine orb":
                return float(line.get("chaosEquivalent", 200.0))
    except requests.RequestException as exc:
        print(f"[WARNING] Could not fetch divine price: {exc}. Using 200 c fallback.")
    return 200.0


def fetch_ninja_prices(league: str) -> dict[str, float]:
    """Fetch unique item chaos values from poe.ninja for all relevant categories.

    Endpoint::

        GET https://poe.ninja/api/data/itemoverview?league=<league>&type=<type>

    Returns a ``dict`` mapping *lowercase* item name → chaos value so that
    subsequent lookups can be case-insensitive.
    """
    prices: dict[str, float] = {}
    for category in NINJA_CATEGORIES:
        params = {"league": league, "type": category}
        try:
            resp = requests.get(POE_NINJA_BASE, params=params, timeout=10)
            resp.raise_for_status()
            for item in resp.json().get("lines", []):
                name = item.get("name", "").strip()
                value = item.get("chaosValue", 0.0)
                if name:
                    prices[name.lower()] = float(value)
        except requests.RequestException as exc:
            print(f"[WARNING] poe.ninja {category} failed: {exc}")
        time.sleep(NINJA_DELAY)
    return prices


# ---------------------------------------------------------------------------
# PoE Trade API helpers
# ---------------------------------------------------------------------------


def _build_session(session_id: Optional[str]) -> requests.Session:
    """Create a ``requests.Session`` pre-configured for the PoE Trade API.

    A valid ``POESESSID`` cookie is required for authenticated endpoints.
    Without it the API may return HTTP 401/429 responses.
    """
    sess = requests.Session()
    sess.headers.update(
        {
            # GGG asks third-party tools to identify themselves in User-Agent.
            "User-Agent": "valdos-finder/1.0 (github.com/vinhng2301/valdos_finder)",
            "Accept": "application/json",
        }
    )
    if session_id:
        sess.cookies.set("POESESSID", session_id, domain="www.pathofexile.com")
    return sess


@rate_limited(SEARCH_DELAY)
def _trade_search(session: requests.Session, league: str) -> tuple[str, list[str]]:
    """POST a search query and return ``(query_id, result_ids)``.

    Endpoint::

        POST https://www.pathofexile.com/api/trade/search/<league>

    The payload filters for **online** listings of the item type
    ``"Valdo's Map"``.
    """
    url = POE_TRADE_SEARCH.format(league=league)
    payload = {
        "query": {
            "type": "Valdo's Map",
            "status": {"option": "online"},
        },
        "sort": {"price": "asc"},
    }
    resp = session.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data.get("result", [])


@rate_limited(FETCH_DELAY)
def _trade_fetch(
    session: requests.Session, ids: list[str], query_id: str
) -> list[dict]:
    """GET item details for a batch of listing IDs.

    Endpoint::

        GET https://www.pathofexile.com/api/trade/fetch/<ids>?query=<query_id>

    ``ids`` must contain at most :data:`FETCH_BATCH_SIZE` entries.
    """
    url = POE_TRADE_FETCH.format(ids=",".join(ids))
    resp = session.get(url, params={"query": query_id}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def fetch_valdos_listings(
    session: requests.Session, league: str, max_results: int = 100
) -> list[dict]:
    """Fetch and parse Valdo's Map listings from the PoE Trade API.

    Returns a list of dicts with keys:

    * ``reward``    – item name contained in the map (str)
    * ``map_price`` – listing price in chaos (float, already converted)
    * ``is_void``   – ``True`` if the map carries the Destroy-on-Death modifier
    """
    print(f"[INFO] Searching PoE trade for Valdo's Maps in '{league}'…")
    query_id, result_ids = _trade_search(session, league)
    total = len(result_ids)
    print(f"[INFO] {total} listing(s) found. Fetching up to {max_results}…")

    result_ids = result_ids[:max_results]
    listings: list[dict] = []

    for i in range(0, len(result_ids), FETCH_BATCH_SIZE):
        batch = result_ids[i : i + FETCH_BATCH_SIZE]
        raw = _trade_fetch(session, batch, query_id)
        for entry in raw:
            parsed = _parse_listing(entry)
            if parsed is not None:
                listings.append(parsed)

    return listings


# Patterns used to extract the reward name from explicit mod text.
# Valdo's Maps carry a mod such as "Contains Mageblood" (or occasionally
# "Map contains Mageblood").  Both forms are matched below.
_REWARD_PATTERNS = [
    re.compile(r"^(?:map\s+)?contains?\s+(.+)$", re.IGNORECASE),
    re.compile(r"^reward[:\s]+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:item|prize)[:\s]+(.+)$", re.IGNORECASE),
]

# Keywords that identify a Void map (no reward, map is consumed on death)
_VOID_KEYWORDS = ["destroy", "void", "on death"]


def _parse_listing(entry: dict) -> Optional[dict]:
    """Extract reward, price, and void status from a raw trade API entry.

    Returns ``None`` for listings that are missing a price or a recognisable
    reward modifier.
    """
    item = entry.get("item", {})
    listing = entry.get("listing", {})

    # ── Price ────────────────────────────────────────────────────────────────
    price_block = listing.get("price", {})
    currency = price_block.get("currency", "chaos")
    try:
        amount = float(price_block.get("amount", 0))
    except (TypeError, ValueError):
        return None

    if amount <= 0:
        return None

    # ── Explicit mods ────────────────────────────────────────────────────────
    # Valdo's Maps list the contained item as an explicit mod.
    # We also check the item's description fields as fallbacks in case GGG
    # ever changes the data format.
    # Known PoE Trade API item text fields: "explicitMods", "implicitMods",
    # "descrText" (description line), "flavourText".
    mod_sources: list[str] = []
    mod_sources.extend(item.get("explicitMods", []))
    mod_sources.extend(item.get("implicitMods", []))
    # "descrText" is the PoE Trade API field name for the item description line
    for text_field in ("descrText", "description", "flavourText"):
        if item.get(text_field):
            mod_sources.append(item[text_field])

    reward: Optional[str] = None
    is_void = False

    for mod in mod_sources:
        mod_stripped = mod.strip()
        mod_lower = mod_stripped.lower()

        # Void / destroy-on-death check
        if any(kw in mod_lower for kw in _VOID_KEYWORDS):
            is_void = True

        # Reward extraction
        if reward is None:
            for pattern in _REWARD_PATTERNS:
                m = pattern.match(mod_stripped)
                if m:
                    reward = m.group(1).strip()
                    break

    if reward is None:
        return None

    return {
        "reward": reward,
        "map_price_raw": amount,
        "currency": currency,
        "is_void": is_void,
    }


# ---------------------------------------------------------------------------
# Profit calculation
# ---------------------------------------------------------------------------


def match_and_calculate(
    listings: list[dict],
    ninja_prices: dict[str, float],
    divine_price: float,
    include_void: bool,
) -> pd.DataFrame:
    """Build a DataFrame of listings with profit margins.

    Steps:

    1. Convert map prices from divine → chaos where necessary.
    2. Look up each reward in *ninja_prices* (exact match, then partial match).
    3. Compute ``Net Profit = Reward Price - Map Price``.
    4. Optionally drop Void maps.
    5. Sort by ``Net Profit`` descending.

    Args:
        listings:      Parsed listing dicts from :func:`fetch_valdos_listings`.
        ninja_prices:  Lowercase name → chaos value mapping from poe.ninja.
        divine_price:  Current Divine Orb value in chaos.
        include_void:  When ``False`` (default), Void maps are excluded.

    Returns:
        A sorted :class:`pandas.DataFrame` with columns:
        ``Reward``, ``Map Price (c)``, ``Reward Price (c)``,
        ``Net Profit (c)``, ``Void``.
    """
    rows = []
    for lst in listings:
        if not include_void and lst["is_void"]:
            continue

        # Normalise price to chaos
        if lst["currency"] in ("divine", "div"):
            map_price_c = lst["map_price_raw"] * divine_price
        else:
            # Assume chaos for any unrecognised currency
            map_price_c = lst["map_price_raw"]

        reward_name = lst["reward"]
        reward_key = reward_name.lower()

        # Exact lookup first
        reward_price = ninja_prices.get(reward_key)

        # Partial-match fallback (handles minor naming inconsistencies)
        if reward_price is None:
            for key, val in ninja_prices.items():
                if reward_key in key or key in reward_key:
                    reward_price = val
                    break

        reward_price = reward_price or 0.0

        rows.append(
            {
                "Reward": reward_name,
                "Map Price (c)": round(map_price_c, 1),
                "Reward Price (c)": round(reward_price, 1),
                "Net Profit (c)": round(reward_price - map_price_c, 1),
                "Void": "✓" if lst["is_void"] else "",
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["Reward", "Map Price (c)", "Reward Price (c)", "Net Profit (c)", "Void"]
        )

    df = pd.DataFrame(rows)
    df.sort_values("Net Profit (c)", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="valdos_finder",
        description="Find the most profitable Valdo's Maps on the PoE trade market.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python valdos_finder.py --league Settlers\n"
            "  python valdos_finder.py --league Settlers --include-void --max-results 50\n"
            "  POE_SESSION_ID=abc123 python valdos_finder.py --league Settlers\n"
        ),
    )
    parser.add_argument(
        "--league",
        default="Settlers",
        metavar="NAME",
        # Update this default value when a new PoE league launches.
        # League names are case-sensitive (e.g. "Settlers", "Necropolis").
        help="PoE league name (default: Settlers).",
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("POE_SESSION_ID"),
        metavar="POESESSID",
        help=(
            "POESESSID cookie for the PoE Trade API. "
            "If omitted, the POE_SESSION_ID environment variable is used."
        ),
    )
    parser.add_argument(
        "--include-void",
        action="store_true",
        default=False,
        help="Include Void maps (maps that are destroyed on death) in results.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=100,
        metavar="N",
        help="Maximum number of trade listings to fetch (default: 100).",
    )
    args = parser.parse_args()

    if not args.session_id:
        print(
            "[WARNING] No POESESSID provided. The PoE Trade API may reject requests\n"
            "          or apply stricter rate limits. See the module docstring for\n"
            "          instructions on obtaining your session ID.\n"
        )

    print(f"╔══ Valdo's Map Profit Finder  |  League: {args.league} ══╗\n")

    # Step 1: Divine → Chaos exchange rate (needed to normalise divine prices)
    print("[1/4] Fetching Divine Orb price from poe.ninja…")
    divine_price = fetch_divine_price(args.league)
    print(f"      Divine Orb ≈ {divine_price:.0f} c\n")

    # Step 2: Unique item prices from poe.ninja
    print("[2/4] Fetching unique item prices from poe.ninja…")
    ninja_prices = fetch_ninja_prices(args.league)
    print(f"      {len(ninja_prices)} item price(s) loaded.\n")

    # Step 3: Valdo's Map listings from PoE Trade API
    print("[3/4] Fetching Valdo's Map listings from the PoE Trade API…")
    session = _build_session(args.session_id)
    try:
        listings = fetch_valdos_listings(session, args.league, args.max_results)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(f"\n[ERROR] Trade API returned HTTP {status}.")
        if status == 401:
            print("        Your POESESSID may be missing or expired.")
        elif status == 429:
            print("        Rate-limit hit – wait a minute and try again.")
        return
    print(f"      {len(listings)} valid listing(s) parsed.\n")

    if not listings:
        print("[ERROR] No listings found. Check your league name and session ID.")
        return

    # Step 4: Calculate profit margins
    print("[4/4] Calculating profit margins…\n")
    df = match_and_calculate(listings, ninja_prices, divine_price, args.include_void)

    if df.empty:
        msg = "No results after filtering."
        if not args.include_void:
            msg += " Try --include-void to include Void maps."
        print(f"[INFO] {msg}")
        return

    # Display
    print("┌─ Results (sorted by Net Profit, highest first) ─────────────────┐\n")
    print(tabulate(df, headers="keys", tablefmt="rounded_outline", showindex=False))
    print(f"\n  Total listings shown: {len(df)}")
    if not args.include_void:
        print("  (Void maps excluded – run with --include-void to include them)")
    print()


if __name__ == "__main__":
    main()
