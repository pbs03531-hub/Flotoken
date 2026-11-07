"""Flotoken's own price list (what a restaurant pays). One place to change the numbers."""

PLAN = {"yearly": 7000, "monthly": 649, "gst_percent": 18}   # Rs; monthly = 7000 / 12 plus about 11%


def gst_breakdown(price, percent=PLAN["gst_percent"]):
    """GST added on top of `price`, and the base/GST inside a GST-inclusive `price`. Rupees, 2 decimals.
       add_gst = price x percent / 100       add_total = price + add_gst
       incl_base = price / (1 + percent/100)  incl_gst = price - incl_base"""
    rate = percent / 100
    return {
        "price": price, "percent": percent,
        "add_gst": round(price * rate, 2), "add_total": round(price * (1 + rate), 2),
        "incl_base": round(price / (1 + rate), 2), "incl_gst": round(price - price / (1 + rate), 2),
    }
