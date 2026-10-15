"""Exact learning duration, independent of any issuer-credit conversion."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def minutes(data):
    return Decimal(str(data['duration_minutes'])) if 'duration_minutes' in data else Decimal(str(data.get('hours', 0))) * 60


def number(value):
    return int(value) if value == value.to_integral_value() else float(value)


def hours_projection(value):
    return number((Decimal(str(value)) / 60).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def validate(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > 6000000 or result.as_tuple().exponent < -2:
            raise ValueError()
        return number(result)
    except (ValueError, InvalidOperation):
        raise ValueError('Learning duration must be between 0 and 100,000 hours, with at most two decimal places in minutes.') from None


def from_fields(hours, minute_part):
    try:
        h, m = Decimal(str(hours or 0)), Decimal(str(minute_part or 0))
        if not h.is_finite() or h < 0 or h != h.to_integral_value():
            raise ValueError('Hours must be a nonnegative whole number.')
        if not m.is_finite() or m < 0 or m >= 60 or m.as_tuple().exponent < -2:
            raise ValueError('Minutes must be from 0 to less than 60, with at most two decimal places.')
        return validate(h * 60 + m)
    except InvalidOperation:
        raise ValueError('Enter numbers for Hours and Minutes.') from None


def parts(data):
    total = minutes(data)
    h = int(total // 60)
    return h, number(total - h * 60)


def label(data):
    h, m = parts(data)
    return f'{h} h {m:g} min'


def hours_based(unit):
    # CPE, CPD and PDU conversions are intentionally not inferred.
    return unit.strip().casefold() in ('h', 'hour', 'hours', 'learning hours')
