"""Foreign-currency-to-AUD conversion.

Every dollar figure elsewhere in this app (invoices, expenses, GST/BAS,
parts.unit_cost) is implicitly AUD — there's no currency column on parts
or purchase_order_lines. So a supplier cost quoted in another currency has
to be converted to AUD before it's stored, not displayed with a bare "$"
next to genuinely-AUD figures.

Converts once, at the moment new data is actually created (an import, a
new PO line) — not on every page view. This matches standard accounting
practice: a foreign-currency transaction is booked at the spot rate on its
transaction date, then stays at that AUD value; it isn't revalued every
time someone opens a report. So there's no cache table or background
refresh here — the live lookup only ever runs at the point something new
is being written, which is inherently rare (once per real purchase).
"""
import requests

# Only used if a live lookup fails — a multi-year range for each of these
# against AUD, so this won't wildly misstate anything even stale, and
# callers should treat a rate they get from here as provisional either way
# (see convert()'s is_live / *_is_live return values).
_FALLBACK_RATES = {"USD": 0.667, "EUR": 0.614, "GBP": 0.525, "NZD": 1.20, "CNY": 4.81, "JPY": 114.0}

# The set shown on the Analytics currency widgets — Australia's actual
# major trading-partner currencies (largest goods-trade partners plus the
# US, since that's this app's own import sourcing currency), not an
# arbitrary top-N by global trading volume. Order here is the fixed
# categorical order the chart's palette below is assigned in.
COMMON_CURRENCIES = ["USD", "EUR", "GBP", "NZD", "CNY", "JPY"]

# Validated (scripts/validate_palette.js, both brand surfaces — see the
# commit that added this) against light Eggshell (#F6EED9) and dark Carbon
# Black (#1E2124): lightness band, chroma floor, and CVD pairwise
# separation all pass; USD/EUR reuses --chart-teal so the two "this app
# already talks about" currencies (AUD's home rate and the Alibaba import's
# own USD) share a color language with the existing revenue chart. Fixed
# assignment, never cycled — a currency always gets the same color.
CHART_COLORS = {
    "USD": "#0E8F6B", "EUR": "#2B6CB0", "GBP": "#9C7A0A",
    "NZD": "#B93A3A", "CNY": "#6B46A3", "JPY": "#C2427A",
}


def get_rate(from_currency, to_currency="AUD"):
    """Returns (rate, is_live). is_live is False when the network lookup
    failed and the fallback was used — callers that persist data should
    surface that rather than silently trusting a guessed rate."""
    if from_currency == to_currency:
        return 1.0, True
    rates, is_live = get_rates(from_currency, [to_currency])
    return rates.get(to_currency, _FALLBACK_RATES.get(to_currency, 1.0)), is_live


def get_rates(from_currency, to_currencies):
    """Live rates from one currency to several at once (one request) —
    returns ({currency: rate}, is_live)."""
    targets = [c for c in to_currencies if c != from_currency]
    if not targets:
        return {c: 1.0 for c in to_currencies}, True
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": from_currency, "to": ",".join(targets)},
            timeout=8,
        )
        resp.raise_for_status()
        rates = {k: float(v) for k, v in resp.json()["rates"].items()}
        if from_currency in to_currencies:
            rates[from_currency] = 1.0
        return rates, True
    except Exception:
        return {c: (1.0 if c == from_currency else _FALLBACK_RATES.get(c, 1.0)) for c in to_currencies}, False


def get_historical_rates(base_currency, to_currencies, start_date, end_date):
    """Daily rates from base_currency to each of to_currencies, one row per
    date in [start_date, end_date] (both "YYYY-MM-DD" strings). Returns
    (rows, is_live) — rows is a date-ascending list of
    {"date": "YYYY-MM-DD", "rates": {currency: rate}}, empty on failure
    (a chart with no data is an obviously-broken chart; nothing pretends
    a fallback series is real history)."""
    try:
        resp = requests.get(
            f"https://api.frankfurter.app/{start_date}..{end_date}",
            params={"from": base_currency, "to": ",".join(to_currencies)},
            timeout=12,
        )
        resp.raise_for_status()
        by_date = resp.json().get("rates", {})
        rows = [
            {"date": d, "rates": {k: float(v) for k, v in by_date[d].items()}}
            for d in sorted(by_date.keys())
        ]
        return rows, True
    except Exception:
        return [], False


def convert(amount, from_currency, to_currency="AUD"):
    """Converts amount and returns (converted_amount, is_live) — see
    get_rate(). Returns (None, True) for a None amount (nothing to convert,
    not a failure)."""
    if amount is None:
        return None, True
    rate, is_live = get_rate(from_currency, to_currency)
    return round(amount * rate, 4), is_live
