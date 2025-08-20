from decimal import Decimal, ROUND_HALF_UP

def q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
