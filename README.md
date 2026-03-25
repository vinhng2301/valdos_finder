# valdos_finder

A Python CLI tool that calculates **profit margins for Valdo's Maps** (Puzzle Box rewards) in Path of Exile.

It cross-references current Valdo's Map listings from the **official PoE Trade API** with reward item prices from **poe.ninja**, then ranks them by net profit so you can instantly see the best buys.

---

## Output example

```
╔══ Valdo's Map Profit Finder  |  League: Settlers ══╗

[1/4] Fetching Divine Orb price from poe.ninja…
      Divine Orb ≈ 198 c

[2/4] Fetching unique item prices from poe.ninja…
      3842 item price(s) loaded.

[3/4] Fetching Valdo's Map listings from the PoE Trade API…
      78 valid listing(s) parsed.

[4/4] Calculating profit margins…

┌─ Results (sorted by Net Profit, highest first) ─────────────────┐

╭────────────────┬───────────────┬──────────────────┬─────────────────┬──────╮
│ Reward         │   Map Price (c) │   Reward Price (c) │   Net Profit (c) │ Void │
├────────────────┼───────────────┼──────────────────┼─────────────────┼──────┤
│ Mageblood      │          50.0 │            520.0 │           470.0 │      │
│ Headhunter     │         180.0 │            310.0 │           130.0 │      │
│ Astramentis    │          40.0 │             75.0 │            35.0 │      │
╰────────────────┴───────────────┴──────────────────┴─────────────────┴──────╯

  Total listings shown: 3
  (Void maps excluded – run with --include-void to include them)
```

---

## Requirements

- Python 3.10+
- A Path of Exile account (for the `POESESSID` trade API cookie)

---

## Installation

```bash
git clone https://github.com/vinhng2301/valdos_finder.git
cd valdos_finder
pip install -r requirements.txt
```

---

## Web Interface

A browser-based UI is available via the bundled Flask application:

```bash
python app.py
# Then open http://localhost:5000 in your browser.
```

The web interface provides the same functionality as the CLI but in a
point-and-click form:

| Field | Default | Description |
|-------|---------|-------------|
| League Name | `Settlers` | PoE league name (must match exactly). |
| POESESSID | `$POE_SESSION_ID` | Your session cookie (see below). |
| Max Listings | `100` | Maximum number of trade listings to fetch (1–500). |
| Include Void maps | off | Show Void maps alongside regular maps. |

You can also pre-populate the session-ID field by setting the
`POE_SESSION_ID` environment variable before starting the server.

To expose the server on all network interfaces (e.g. for access from
another machine), set `HOST=0.0.0.0`:

```bash
HOST=0.0.0.0 python app.py
```

---

## Obtaining a POESESSID

The PoE Official Trade API requires an authenticated session cookie.

1. Open <https://www.pathofexile.com> and **log in**.
2. Open your browser's **Developer Tools** (press `F12`).
3. Navigate to the Cookies section for `https://www.pathofexile.com`:
   - **Chrome / Edge**: Application tab → Storage → Cookies → `https://www.pathofexile.com`
   - **Firefox**: Storage tab → Cookies → `https://www.pathofexile.com`
4. Find the cookie named **`POESESSID`** and copy its value.
5. Keep this value secret – it is equivalent to your login session token.

---

## Usage

```bash
# Basic usage (league name must match exactly, e.g. "Settlers", "Necropolis")
python valdos_finder.py --league "Settlers" --session-id "YOUR_POESESSID"

# Or export the session ID as an environment variable (recommended)
export POE_SESSION_ID="YOUR_POESESSID"
python valdos_finder.py --league "Settlers"

# Include Void maps (maps that destroy the item on death) in results
python valdos_finder.py --league "Settlers" --include-void

# Limit the number of trade listings fetched (default: 100)
python valdos_finder.py --league "Settlers" --max-results 50
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--league NAME` | `Settlers` | PoE league name. Must match the in-game league name exactly. |
| `--session-id POESESSID` | `$POE_SESSION_ID` | Your POESESSID cookie (see above). |
| `--include-void` | off | Show Void maps (destroyed on death) alongside normal maps. |
| `--max-results N` | `100` | Maximum number of listings to fetch from the trade API. |

---

## How it works

1. **poe.ninja prices** – Fetches current chaos values for every unique weapon,
   armour, accessory, flask, and jewel via the poe.ninja item-overview API.

2. **Trade listings** – Searches the official PoE Trade API for all online
   Valdo's Map listings and fetches the first *N* results (sorted cheapest first).

3. **Reward extraction** – Parses each map's explicit mods to find the contained
   item (e.g. `"Contains Mageblood"`).

4. **Margin calculation** – `Net Profit = Reward Price (c) − Map Price (c)`.
   Divine-priced listings are automatically converted using the live
   divine → chaos rate from poe.ninja.

5. **Filtering & ranking** – Void maps are excluded by default (toggle with
   `--include-void`).  Results are sorted by highest net profit.

---

## Rate limiting

GGG's trade API enforces strict rate limits. The script respects them by:

- Sleeping **6 seconds** between trade search requests.
- Sleeping **1.2 seconds** between trade fetch requests.
- Fetching at most **10 listing IDs** per fetch call (the API maximum).
- Sleeping **0.5 seconds** between poe.ninja requests.

These delays are enforced by a `@rate_limited` decorator applied to every API
call function.

---

## Data sources

| Source | Purpose | Docs |
|--------|---------|------|
| [poe.ninja](https://poe.ninja) | Reward item prices (chaos value) | Unofficial; widely used |
| [PoE Trade API](https://www.pathofexile.com/developer/docs/trade) | Valdo's Map listings & prices | Official GGG API |

---

## Disclaimer

This tool is a third-party project and is not affiliated with or endorsed by
Grinding Gear Games.  Use it responsibly and in accordance with GGG's
[terms of service](https://www.pathofexile.com/legal/terms-of-use).
