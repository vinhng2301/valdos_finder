#!/usr/bin/env python3
"""
Valdo's Map Profit Finder – Flask Web Application
==================================================
Wraps the core logic from ``valdos_finder.py`` in a simple web UI so users
can run profit searches from a browser without using the command line.

Usage
-----
    python app.py
    # Then open http://localhost:5000 in your browser.

Environment Variables
---------------------
    POE_SESSION_ID  – Pre-populate the session-ID field (optional).
    FLASK_SECRET    – Flask session secret (auto-generated if absent).
"""

import os
import secrets
import traceback

import requests
from flask import Flask, render_template, request

from valdos_finder import (
    _build_session,
    fetch_divine_price,
    fetch_ninja_prices,
    fetch_valdos_listings,
    match_and_calculate,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_hex(32))


@app.route("/", methods=["GET", "POST"])
def index():
    """Render the search form and, on POST, the results table."""
    default_session_id = os.environ.get("POE_SESSION_ID", "")

    if request.method == "GET":
        return render_template(
            "index.html",
            league="Settlers",
            session_id=default_session_id,
            include_void=False,
            max_results=100,
            divine_price=None,
            ninja_count=None,
            listing_count=None,
            results=None,
            error=None,
            default_session_id=default_session_id,
        )

    # ── Parse form ────────────────────────────────────────────────────────────
    league = request.form.get("league", "").strip() or "Settlers"
    session_id = request.form.get("session_id", "").strip() or None
    include_void = request.form.get("include_void") == "on"
    try:
        max_results = max(1, min(int(request.form.get("max_results", 100)), 500))
    except (TypeError, ValueError):
        max_results = 100

    # ── Run the pipeline ──────────────────────────────────────────────────────
    error = None
    results = None
    divine_price = None
    ninja_count = None
    listing_count = None

    try:
        divine_price = fetch_divine_price(league)
        ninja_prices = fetch_ninja_prices(league)
        ninja_count = len(ninja_prices)

        trade_session = _build_session(session_id)
        listings = fetch_valdos_listings(trade_session, league, max_results)
        listing_count = len(listings)

        df = match_and_calculate(listings, ninja_prices, divine_price, include_void)

        if not df.empty:
            results = df.to_dict(orient="records")
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status == 401:
            error = (
                f"HTTP {status} – Your POESESSID appears to be missing or expired. "
                "Please obtain a fresh session ID from your browser cookies."
            )
        elif status == 429:
            error = (
                f"HTTP {status} – Rate limit reached. "
                "Please wait a minute and try again."
            )
        else:
            error = f"Trade API error: HTTP {status}."
    except requests.exceptions.ConnectionError:
        error = (
            "Could not connect to the PoE Trade API or poe.ninja. "
            "Please check your internet connection and try again."
        )
    except Exception:
        error = "An unexpected error occurred. Check the server logs for details."
        traceback.print_exc()

    return render_template(
        "index.html",
        league=league,
        session_id=session_id or "",
        include_void=include_void,
        max_results=max_results,
        divine_price=divine_price,
        ninja_count=ninja_count,
        listing_count=listing_count,
        results=results,
        error=error,
        default_session_id=default_session_id,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(debug=False, host=host, port=port)
