"""Issuer-neutral, user-recorded renewal requirements; never issuer approval.

Unknown requirements stay unknown. Numeric totals describe saved allocations, not
eligibility verification. Dates here are calendar dates, never UTC timestamps.
"""
from datetime import date, timedelta
from decimal import Decimal


def normalize(data, text, day, amount):
    if not isinstance(data, dict):
        raise ValueError('Renewal tracking fields must be an object.')
    result = {}
    for key in ('version', 'route'):
        result[key] = text(data.get(key, ''), key.title(), 200)
    result['checked'] = day(data.get('checked', ''), 'Policy date checked')
    result['verification'] = data.get('verification', 'unverified')
    if result['verification'] not in ('unverified', 'user_checked'):
        raise ValueError('Choose whether you have checked the rules.')
    result['requirement_known'] = data.get('requirement_known', False)
    if type(result['requirement_known']) is not bool:
        raise ValueError('Choose whether the total requirement is known.')
    for key in ('reporting_start', 'reporting_end'):
        result[key] = day(data.get(key, ''), key.replace('_', ' ').title())
    if all(result[k] for k in ('reporting_start', 'reporting_end')) and result['reporting_end'] < result['reporting_start']:
        raise ValueError('Reporting end cannot precede reporting start.')
    result['annual_kind'] = data.get('annual_kind', 'unknown')
    if result['annual_kind'] not in ('unknown', 'none', 'minimum', 'pacing'):
        raise ValueError('Choose annual minimum, optional pacing, none, or unknown.')
    result['annual_amount'] = amount(data.get('annual_amount') or 0, 'Annual amount')
    if result['annual_kind'] in ('minimum','pacing') and not result['annual_amount']:
        raise ValueError('Enter a positive annual amount, or leave the annual rule unknown.')
    result['year_basis'] = data.get('year_basis', 'unknown')
    if result['year_basis'] not in ('unknown', 'calendar', 'anniversary'):
        raise ValueError('Choose the reporting-year definition.')
    result['year_anchor'] = day(data.get('year_anchor', ''), 'Reporting-year anchor')
    if result['year_basis'] == 'anniversary' and not result['year_anchor']:
        raise ValueError('Enter the first day of a reporting year. Do not guess the issuer’s reporting year.')
    result['conditions'] = text(data.get('conditions', ''), 'Other renewal conditions', 3000)
    result['conditions_status'] = data.get('conditions_status', 'unknown')
    if result['conditions_status'] not in ('unknown', 'outstanding', 'checked'):
        raise ValueError('Choose the status of other renewal conditions.')
    categories = data.get('categories', [])
    if not isinstance(categories, list) or len(categories) > 6:
        raise ValueError('Use up to six credit categories.')
    result['categories'] = []
    for item in categories:
        if not isinstance(item, dict):
            raise ValueError('Invalid credit category.')
        name = text(item.get('name', ''), 'Category', 100, True)
        if name.casefold() in {c['name'].casefold() for c in result['categories']}:
            raise ValueError('Category names must be distinct.')
        minimum = None if item.get('minimum') in ('', None) else amount(item['minimum'], 'Category minimum')
        cap = None if item.get('cap') in ('', None) else amount(item['cap'], 'Category cap')
        if minimum is not None and cap is not None and minimum > cap:
            raise ValueError('A category minimum cannot exceed its cap.')
        result['categories'].append(dict(name=name, minimum=minimum, cap=cap))
    return result


def _sum(items):
    return float(sum((Decimal(str(x)) for x in items), Decimal(0)))


def _remaining(required, recorded):
    # Inputs have at most two decimal places. Preserve that arithmetic through
    # caps and differences instead of exposing binary floating-point residue.
    return float(max(Decimal(0), Decimal(str(required))-Decimal(str(recorded))))


def progress(cycle, *, include_unclassified=False):
    """One activity per cycle is enforced in storage. Never count reuse as hours."""
    data = cycle['data']; rules = data.get('tracking', {})
    known = rules.get('requirement_known', bool(data['required']))
    start, end = rules.get('reporting_start', ''), rules.get('reporting_end', '')
    bounded = bool(start and end)
    allocations = cycle['allocations']
    def reporting_day(row):
        return row['data'].get('reporting_date') or row['training']['data']['completed']
    included = [a for a in allocations if not bounded or start <= reporting_day(a) <= end]
    excluded = [a for a in allocations if a not in included]
    categories = []
    for rule in rules.get('categories', []):
        accepted = _sum(a['data']['accepted'] for a in included if a['data'].get('category') == rule['name'])
        cap = rule['cap']
        categories.append({**rule, 'accepted': accepted, 'over_cap': _remaining(accepted, cap) if cap is not None else 0,
                           'remaining': _remaining(rule['minimum'], accepted) if rule['minimum'] is not None else None})
    names={c['name'] for c in categories}
    unclassified=[a for a in included if names and a['data'].get('category') not in names]
    accepted = _sum(a['data']['accepted'] for a in included if include_unclassified or a not in unclassified)
    capped = _remaining(accepted, _sum(c['over_cap'] for c in categories))
    annual = []
    basis = rules.get('year_basis', 'unknown')
    if bounded and basis != 'unknown':
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if (last-first).days > 3660:
            # Remain bounded even with unusually long manually entered periods.
            return dict(known=known, accepted=capped, remaining=_remaining(data['required'], capped) if known else None,
                        categories=categories, annual=[], unclassified=unclassified, excluded=excluded, bounded=bounded, annual_unavailable=True)
        anchor = date.fromisoformat(rules['year_anchor']) if basis == 'anniversary' else date(first.year, 1, 1)
        def boundary(year):
            if year<1:return date.min
            try: return date(year, anchor.month, anchor.day)
            except ValueError: return date(year, 2, 28)  # Explicitly disclosed on the form.
        for year in range(first.year-1, last.year+1):
            next_start = boundary(year+1) if year < 9999 else None
            # Skip an interval ending before the reporting period before
            # subtracting a day; date.min has no representable previous day.
            if next_start is not None and next_start <= first:
                continue
            begin = max(first, boundary(year))
            finish = min(last, next_start-timedelta(days=1) if next_start else date.max)
            if begin > finish: continue
            amount = _sum(a['data']['accepted'] for a in included if begin.isoformat() <= reporting_day(a) <= finish.isoformat())
            annual.append(dict(start=begin.isoformat(), end=finish.isoformat(), accepted=amount,
                               remaining=_remaining(rules.get('annual_amount', 0), amount)))
    return dict(known=known, accepted=capped, remaining=_remaining(data['required'], capped) if known else None,
                categories=categories, annual=annual, unclassified=unclassified, excluded=excluded, bounded=bounded, annual_unavailable=False)


def status(certification, current, today=None):
    today = today or date.today()
    data = certification['data']
    if data.get('standing') == 'superseded': return 'Superseded · earned achievement retained'
    if data['non_expiring'] == 'yes': return 'Does not expire'
    expiration = current['data']['expiration'] if current else ''
    if not expiration: return 'Expiration not recorded'
    if expiration < today.isoformat(): return 'Expired · earned achievement retained'
    return 'Expires '+expiration


def contribution(allocation):
    """One contribution per activity: never add its workflow stages together."""
    data = allocation['data']
    proposed = data.get('proposed')
    if proposed is not None:
        return max(proposed, data['accepted'])
    return max(data['submitted'], data['accepted']) or None


def planning_progress(cycle):
    from copy import deepcopy
    estimate = deepcopy(cycle)
    unknown = 0
    for row in estimate['allocations']:
        value = contribution(row)
        if value is None:unknown += 1
        row['data']['accepted'] = value or 0
    result = progress(estimate, include_unclassified=True)
    result['unknown'] = unknown
    result['today'] = date.today().isoformat()
    return result
