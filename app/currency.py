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

# Only used if the live lookup fails — the multi-year USD/AUD range is
# roughly 1.30-1.65, so this won't wildly misstate anything even stale,
# and callers should treat a rate they get from here as provisional either
# way (see convert()'s return value).
_FALLBACK_RATES = {"USD": 1.50}


def get_rate(from_currency, to_currency="AUD"):
    """Returns (rate, is_live). is_live is False when the network lookup
    failed and the fallback was used — callers that persist data should
    surface that rather than silently trusting a guessed rate."""
    if from_currency == to_currency:
        return 1.0, True
    try:
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": from_currency, "to": to_currency},
            timeout=8,
        )
        resp.raise_for_status()
        return float(resp.json()["rates"][to_currency]), True
    except Exception:
        return _FALLBACK_RATES.get(from_currency, 1.0), False


def convert(amount, from_currency, to_currency="AUD"):
    """Converts amount and returns (converted_amount, is_live) — see
    get_rate(). Returns (None, True) for a None amount (nothing to convert,
    not a failure)."""
    if amount is None:
        return None, True
    rate, is_live = get_rate(from_currency, to_currency)
    return round(amount * rate, 4), is_live
