"""Pure commercial calculations; deliberately independent of beta freight."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def number(value):
    try:
        result = Decimal(str(value or 0))
    except InvalidOperation as exc:
        raise ValueError('A valid number is required') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('Amounts and quantities must be finite and non-negative')
    return result


def money(value):
    return number(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def freight_split(actual, responsibility, customer_amount):
    actual, customer = money(actual), money(customer_amount)
    if responsibility == 'Pending QC':
        raise ValueError('Freight responsibility must be finalized')
    if responsibility == 'SNRG':
        customer = Decimal(0)
    elif responsibility == 'Customer':
        customer = actual
    if customer > actual:
        raise ValueError('Customer freight cannot exceed actual transporter charges')
    return customer


def rejection_deadlines(notice, resolved=None, dispute_days=15, collection_days=30):
    notice = date.fromisoformat(str(notice))
    dispute = notice + timedelta(days=int(dispute_days))
    collection = notice + timedelta(days=int(collection_days))
    if resolved:
        collection = max(collection, date.fromisoformat(str(resolved)) + timedelta(days=15))
    return dispute, collection


def working_due(start, days, holidays):
    current = date.fromisoformat(str(start))
    holidays = {str(h) for h in holidays}
    remaining = int(days)
    if remaining < 0 or remaining > 365:
        raise ValueError('Working-day target must be between 0 and 365')
    # Non-working weekdays (including weekly offs) come from ERPNext Holiday List.
    while remaining:
        current += timedelta(days=1)
        if current.isoformat() not in holidays:
            remaining -= 1
    return current
