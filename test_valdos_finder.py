"""
Tests for valdos_finder.py
===========================
Covers all major functions using pytest and unittest.mock so that no real
HTTP calls are made during the test run.
"""

import time
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

import valdos_finder as vf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    explicit_mods=None,
    implicit_mods=None,
    descr_text=None,
    amount=10.0,
    currency="chaos",
):
    """Return a minimal raw trade-API entry dict."""
    item = {}
    if explicit_mods is not None:
        item["explicitMods"] = explicit_mods
    if implicit_mods is not None:
        item["implicitMods"] = implicit_mods
    if descr_text is not None:
        item["descrText"] = descr_text
    return {
        "item": item,
        "listing": {
            "price": {
                "amount": amount,
                "currency": currency,
            }
        },
    }


# ===========================================================================
# _parse_listing
# ===========================================================================

class TestParseListing:
    def test_contains_reward(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Mageblood"

    def test_map_contains_reward(self):
        entry = _make_entry(explicit_mods=["Map contains Headhunter"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Headhunter"

    def test_reward_colon_format(self):
        entry = _make_entry(explicit_mods=["Reward: Astramentis"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Astramentis"

    def test_item_colon_format(self):
        entry = _make_entry(explicit_mods=["Item: Mageblood"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Mageblood"

    def test_implicit_mod_used_as_fallback(self):
        entry = _make_entry(implicit_mods=["Contains Headhunter"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Headhunter"

    def test_descr_text_used_as_fallback(self):
        entry = _make_entry(descr_text="Contains Mageblood")
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Mageblood"

    def test_void_keyword_detected(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood", "Destroy on Death"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["is_void"] is True

    def test_void_keyword_void(self):
        entry = _make_entry(explicit_mods=["Contains Headhunter", "This is a Void Map"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["is_void"] is True

    def test_not_void_by_default(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["is_void"] is False

    def test_divine_currency_stored(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood"], amount=2.0, currency="divine")
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["currency"] == "divine"
        assert result["map_price_raw"] == 2.0

    def test_missing_price_returns_none(self):
        entry = {
            "item": {"explicitMods": ["Contains Mageblood"]},
            "listing": {"price": {"amount": None, "currency": "chaos"}},
        }
        result = vf._parse_listing(entry)
        assert result is None

    def test_zero_amount_returns_none(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood"], amount=0)
        result = vf._parse_listing(entry)
        assert result is None

    def test_negative_amount_returns_none(self):
        entry = _make_entry(explicit_mods=["Contains Mageblood"], amount=-5)
        result = vf._parse_listing(entry)
        assert result is None

    def test_no_matching_mod_returns_none(self):
        entry = _make_entry(explicit_mods=["Some random mod without reward"])
        result = vf._parse_listing(entry)
        assert result is None

    def test_empty_entry_returns_none(self):
        result = vf._parse_listing({"item": {}, "listing": {}})
        assert result is None

    def test_case_insensitive_contains(self):
        entry = _make_entry(explicit_mods=["CONTAINS Mageblood"])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Mageblood"

    def test_reward_with_extra_whitespace_stripped(self):
        entry = _make_entry(explicit_mods=["Contains   Mageblood  "])
        result = vf._parse_listing(entry)
        assert result is not None
        assert result["reward"] == "Mageblood"

    def test_invalid_amount_string_returns_none(self):
        entry = {
            "item": {"explicitMods": ["Contains Mageblood"]},
            "listing": {"price": {"amount": "not_a_number", "currency": "chaos"}},
        }
        result = vf._parse_listing(entry)
        assert result is None


# ===========================================================================
# match_and_calculate
# ===========================================================================

class TestMatchAndCalculate:
    def _listings(self, *overrides):
        """Generate a list of listing dicts."""
        defaults = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
            {"reward": "Headhunter", "map_price_raw": 180.0, "currency": "chaos", "is_void": False},
        ]
        return list(overrides) if overrides else defaults

    def test_basic_profit_calculation(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
        ]
        ninja = {"mageblood": 520.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert len(df) == 1
        assert df.iloc[0]["Net Profit (c)"] == 470.0
        assert df.iloc[0]["Map Price (c)"] == 50.0
        assert df.iloc[0]["Reward Price (c)"] == 520.0

    def test_divine_currency_conversion(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 2.0, "currency": "divine", "is_void": False},
        ]
        ninja = {"mageblood": 520.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert len(df) == 1
        # 2 divine × 200 c = 400 c map price → 520 - 400 = 120
        assert df.iloc[0]["Map Price (c)"] == 400.0
        assert df.iloc[0]["Net Profit (c)"] == 120.0

    def test_div_currency_alias(self):
        """'div' should also be treated as divine."""
        listings = [
            {"reward": "Mageblood", "map_price_raw": 1.0, "currency": "div", "is_void": False},
        ]
        ninja = {"mageblood": 300.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert df.iloc[0]["Map Price (c)"] == 200.0

    def test_unknown_currency_treated_as_chaos(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "exalt", "is_void": False},
        ]
        ninja = {"mageblood": 100.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert df.iloc[0]["Map Price (c)"] == 50.0

    def test_void_maps_excluded_by_default(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
            {"reward": "Headhunter", "map_price_raw": 50.0, "currency": "chaos", "is_void": True},
        ]
        ninja = {"mageblood": 520.0, "headhunter": 300.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert len(df) == 1
        assert df.iloc[0]["Reward"] == "Mageblood"

    def test_void_maps_included_when_requested(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
            {"reward": "Headhunter", "map_price_raw": 50.0, "currency": "chaos", "is_void": True},
        ]
        ninja = {"mageblood": 520.0, "headhunter": 300.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=True)
        assert len(df) == 2

    def test_void_column_marker(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": True},
        ]
        ninja = {"mageblood": 520.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=True)
        assert df.iloc[0]["Void"] == "✓"

    def test_non_void_column_empty(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
        ]
        ninja = {"mageblood": 520.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=True)
        assert df.iloc[0]["Void"] == ""

    def test_sorted_by_profit_descending(self):
        listings = [
            {"reward": "ItemA", "map_price_raw": 100.0, "currency": "chaos", "is_void": False},
            {"reward": "ItemB", "map_price_raw": 10.0, "currency": "chaos", "is_void": False},
        ]
        ninja = {"itema": 150.0, "itemb": 500.0}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        profits = df["Net Profit (c)"].tolist()
        assert profits == sorted(profits, reverse=True)

    def test_unknown_reward_defaults_to_zero_price(self):
        listings = [
            {"reward": "UnknownItem", "map_price_raw": 50.0, "currency": "chaos", "is_void": False},
        ]
        ninja = {}
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert df.iloc[0]["Reward Price (c)"] == 0.0
        assert df.iloc[0]["Net Profit (c)"] == -50.0

    def test_partial_name_match(self):
        """Partial name match should find the price when exact match fails."""
        listings = [
            {
                "reward": "Mageblood Belt",
                "map_price_raw": 50.0,
                "currency": "chaos",
                "is_void": False,
            }
        ]
        ninja = {"mageblood": 520.0}  # key is shorter than reward key
        df = vf.match_and_calculate(listings, ninja, divine_price=200.0, include_void=False)
        assert df.iloc[0]["Reward Price (c)"] == 520.0

    def test_empty_listings_returns_empty_dataframe(self):
        df = vf.match_and_calculate([], {}, divine_price=200.0, include_void=False)
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        expected_cols = {"Reward", "Map Price (c)", "Reward Price (c)", "Net Profit (c)", "Void"}
        assert set(df.columns) == expected_cols

    def test_all_void_excluded_returns_empty_dataframe(self):
        listings = [
            {"reward": "Mageblood", "map_price_raw": 50.0, "currency": "chaos", "is_void": True},
        ]
        df = vf.match_and_calculate(listings, {"mageblood": 520.0}, 200.0, include_void=False)
        assert df.empty


# ===========================================================================
# rate_limited decorator
# ===========================================================================

class TestRateLimited:
    def test_return_value_passed_through(self):
        @vf.rate_limited(0.0)
        def fn():
            return 42

        assert fn() == 42

    def test_delay_enforced(self):
        """Second call should be delayed by at least the specified amount."""
        delay = 0.15

        @vf.rate_limited(delay)
        def fn():
            return time.monotonic()

        fn()  # warm up - sets last_called
        t_before = time.monotonic()
        fn()
        t_after = time.monotonic()

        # The wrapper should have waited >= delay seconds from the first call.
        # We allow a small margin for scheduling jitter.
        assert (t_after - t_before) >= delay * 0.8

    def test_no_delay_when_enough_time_has_passed(self):
        """If the delay has already elapsed naturally, no extra sleep occurs."""
        delay = 0.05

        @vf.rate_limited(delay)
        def fn():
            return time.monotonic()

        fn()  # first call
        time.sleep(delay + 0.05)  # wait longer than the delay
        t_before = time.monotonic()
        fn()
        t_after = time.monotonic()

        # Should complete almost immediately (< 2x delay, very conservative)
        assert (t_after - t_before) < delay * 2

    def test_kwargs_forwarded(self):
        @vf.rate_limited(0.0)
        def fn(a, b=10):
            return a + b

        assert fn(1, b=5) == 6


# ===========================================================================
# fetch_divine_price
# ===========================================================================

class TestFetchDivinePrice:
    def test_returns_divine_price_on_success(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_CURRENCY,
            json={
                "lines": [
                    {"currencyTypeName": "Divine Orb", "chaosEquivalent": 195.5},
                    {"currencyTypeName": "Chaos Orb", "chaosEquivalent": 1.0},
                ]
            },
        )
        price = vf.fetch_divine_price("Settlers")
        assert price == 195.5

    def test_case_insensitive_lookup(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_CURRENCY,
            json={
                "lines": [
                    {"currencyTypeName": "DIVINE ORB", "chaosEquivalent": 180.0},
                ]
            },
        )
        price = vf.fetch_divine_price("Settlers")
        assert price == 180.0

    def test_fallback_when_request_fails(self, requests_mock):
        requests_mock.get(vf.POE_NINJA_CURRENCY, exc=requests.ConnectionError)
        price = vf.fetch_divine_price("Settlers")
        assert price == 200.0

    def test_fallback_when_divine_not_in_response(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_CURRENCY,
            json={"lines": [{"currencyTypeName": "Chaos Orb", "chaosEquivalent": 1.0}]},
        )
        price = vf.fetch_divine_price("Settlers")
        assert price == 200.0

    def test_fallback_when_http_error(self, requests_mock):
        requests_mock.get(vf.POE_NINJA_CURRENCY, status_code=500)
        price = vf.fetch_divine_price("Settlers")
        assert price == 200.0


# ===========================================================================
# fetch_ninja_prices
# ===========================================================================

class TestFetchNinjaPrices:
    def _ninja_response(self, items):
        return {"lines": [{"name": n, "chaosValue": v} for n, v in items]}

    def test_returns_prices_lowercased(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_BASE,
            json=self._ninja_response([("Mageblood", 520.0)]),
        )
        with patch("time.sleep"):
            prices = vf.fetch_ninja_prices("Settlers")
        assert "mageblood" in prices
        assert prices["mageblood"] == 520.0

    def test_aggregates_multiple_categories(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_BASE,
            json=self._ninja_response([("SomeItem", 100.0)]),
        )
        with patch("time.sleep"):
            prices = vf.fetch_ninja_prices("Settlers")
        # Each category returns one item, but all share the same name here.
        # At least one entry should be in the result.
        assert "someitem" in prices

    def test_partial_failure_skips_category(self, requests_mock):
        """If one category request fails, others should still succeed."""
        call_count = {"n": 0}

        def response_callback(request, context):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise requests.ConnectionError("boom")
            return {"lines": [{"name": "Headhunter", "chaosValue": 300.0}]}

        requests_mock.get(vf.POE_NINJA_BASE, json=response_callback)
        with patch("time.sleep"):
            prices = vf.fetch_ninja_prices("Settlers")
        assert "headhunter" in prices

    def test_empty_name_items_skipped(self, requests_mock):
        requests_mock.get(
            vf.POE_NINJA_BASE,
            json={"lines": [{"name": "", "chaosValue": 10.0}]},
        )
        with patch("time.sleep"):
            prices = vf.fetch_ninja_prices("Settlers")
        assert "" not in prices


# ===========================================================================
# _build_session
# ===========================================================================

class TestBuildSession:
    def test_user_agent_set(self):
        sess = vf._build_session(None)
        assert "valdos-finder" in sess.headers.get("User-Agent", "")

    def test_accept_header_set(self):
        sess = vf._build_session(None)
        assert sess.headers.get("Accept") == "application/json"

    def test_session_id_cookie_set(self):
        sess = vf._build_session("mysessionid123")
        cookie = sess.cookies.get("POESESSID", domain="www.pathofexile.com")
        assert cookie == "mysessionid123"

    def test_no_cookie_when_session_id_is_none(self):
        sess = vf._build_session(None)
        cookie = sess.cookies.get("POESESSID")
        assert cookie is None

    def test_returns_requests_session(self):
        sess = vf._build_session(None)
        assert isinstance(sess, requests.Session)


# ===========================================================================
# _trade_search
# ===========================================================================

class TestTradeSearch:
    def test_returns_query_id_and_results(self, requests_mock):
        league = "Settlers"
        url = vf.POE_TRADE_SEARCH.format(league=league)
        requests_mock.post(
            url,
            json={"id": "abc123", "result": ["id1", "id2", "id3"]},
        )
        sess = vf._build_session(None)
        with patch("time.sleep"):
            qid, results = vf._trade_search(sess, league)
        assert qid == "abc123"
        assert results == ["id1", "id2", "id3"]

    def test_raises_on_http_error(self, requests_mock):
        league = "Settlers"
        url = vf.POE_TRADE_SEARCH.format(league=league)
        requests_mock.post(url, status_code=429)
        sess = vf._build_session(None)
        with patch("time.sleep"):
            with pytest.raises(requests.HTTPError):
                vf._trade_search(sess, league)

    def test_empty_result_list(self, requests_mock):
        league = "Settlers"
        url = vf.POE_TRADE_SEARCH.format(league=league)
        requests_mock.post(url, json={"id": "xyz", "result": []})
        sess = vf._build_session(None)
        with patch("time.sleep"):
            qid, results = vf._trade_search(sess, league)
        assert results == []


# ===========================================================================
# _trade_fetch
# ===========================================================================

class TestTradeFetch:
    def test_returns_result_list(self, requests_mock):
        ids = ["id1", "id2"]
        url = vf.POE_TRADE_FETCH.format(ids=",".join(ids))
        fake_result = [{"item": {}, "listing": {}}]
        requests_mock.get(url, json={"result": fake_result})
        sess = vf._build_session(None)
        with patch("time.sleep"):
            result = vf._trade_fetch(sess, ids, "qid")
        assert result == fake_result

    def test_raises_on_http_error(self, requests_mock):
        ids = ["id1"]
        url = vf.POE_TRADE_FETCH.format(ids=",".join(ids))
        requests_mock.get(url, status_code=401)
        sess = vf._build_session(None)
        with patch("time.sleep"):
            with pytest.raises(requests.HTTPError):
                vf._trade_fetch(sess, ids, "qid")


# ===========================================================================
# fetch_valdos_listings
# ===========================================================================

class TestFetchValdosListings:
    def _fake_listing(self, reward="Mageblood", amount=50.0):
        return {
            "item": {"explicitMods": [f"Contains {reward}"]},
            "listing": {"price": {"amount": amount, "currency": "chaos"}},
        }

    @patch("valdos_finder._trade_fetch")
    @patch("valdos_finder._trade_search")
    def test_returns_parsed_listings(self, mock_search, mock_fetch):
        mock_search.return_value = ("qid1", ["id1", "id2"])
        mock_fetch.return_value = [
            self._fake_listing("Mageblood"),
            self._fake_listing("Headhunter", 180.0),
        ]
        sess = MagicMock()
        listings = vf.fetch_valdos_listings(sess, "Settlers", max_results=10)
        assert len(listings) == 2
        rewards = {lst["reward"] for lst in listings}
        assert rewards == {"Mageblood", "Headhunter"}

    @patch("valdos_finder._trade_fetch")
    @patch("valdos_finder._trade_search")
    def test_respects_max_results(self, mock_search, mock_fetch):
        # Return 20 IDs but max_results=5
        mock_search.return_value = ("qid", [f"id{i}" for i in range(20)])
        mock_fetch.return_value = [self._fake_listing()]
        sess = MagicMock()
        vf.fetch_valdos_listings(sess, "Settlers", max_results=5)
        # All fetched IDs should come from the first 5 only
        fetched_ids = mock_fetch.call_args[0][1]
        assert len(fetched_ids) <= vf.FETCH_BATCH_SIZE
        # Total IDs passed across all batches <= 5
        all_ids = [id_ for c in mock_fetch.call_args_list for id_ in c[0][1]]
        assert len(all_ids) <= 5

    @patch("valdos_finder._trade_fetch")
    @patch("valdos_finder._trade_search")
    def test_skips_unparseable_entries(self, mock_search, mock_fetch):
        """Entries without a matching reward mod should be silently skipped."""
        mock_search.return_value = ("qid", ["id1"])
        mock_fetch.return_value = [
            {"item": {}, "listing": {"price": {"amount": 10, "currency": "chaos"}}},
        ]
        sess = MagicMock()
        listings = vf.fetch_valdos_listings(sess, "Settlers")
        assert listings == []

    @patch("valdos_finder._trade_fetch")
    @patch("valdos_finder._trade_search")
    def test_empty_search_returns_empty_list(self, mock_search, mock_fetch):
        mock_search.return_value = ("qid", [])
        sess = MagicMock()
        listings = vf.fetch_valdos_listings(sess, "Settlers")
        assert listings == []
        mock_fetch.assert_not_called()
