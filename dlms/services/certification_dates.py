"""Independent date-only targets; old shared deadlines retain unresolved provenance."""
from datetime import date

FIELDS = ('planning_deadline', 'renewal_deadline')
LEGACY_SOURCE = 'cycle.data.renewal'


def calendar_day(value):
    if not isinstance(value, str):
        raise ValueError('Certification dates must be calendar-date strings.')
    if value and (len(value) != 10 or date.fromisoformat(value).isoformat() != value):
        raise ValueError('Certification dates must use YYYY-MM-DD.')
    return value


def upgrade_legacy(data, version):
    """Used by migration and read-only validation of old backups; never guess meaning."""
    if not isinstance(data, dict):
        raise ValueError('Certification period fields must be an object.')
    if any(k in data for k in (*FIELDS, 'legacy_deadline')):
        raise ValueError('Legacy certification data contains conflicting deadline fields.')
    result = dict(data)
    value = calendar_day(result.pop('renewal', ''))
    result.update(planning_deadline='', renewal_deadline='')
    if value:
        result['legacy_deadline'] = dict(value=value, source=LEGACY_SOURCE,
                                         source_schema=version, classification='unresolved')
    return result


def validate_legacy(value):
    if (not isinstance(value, dict) or set(value) != {'value', 'source', 'source_schema', 'classification'}
            or value['source'] != LEGACY_SOURCE or type(value['source_schema']) is not int
            or not 7 <= value['source_schema'] <= 9
            or value['classification'] not in ('unresolved', *FIELDS)
            or not calendar_day(value['value'])):
        raise ValueError('The preserved legacy deadline is invalid.')
    return dict(value)


def prompt_dates(data):
    result = {'Planning deadline': data['planning_deadline'] or 'Not recorded',
              'Renewal deadline (user recorded; not issuer verified)': data['renewal_deadline'] or 'Not recorded',
              'Expires': data['expiration'] or 'Not recorded'}
    if data.get('legacy_deadline'):
        old = data['legacy_deadline']
        result['Preserved legacy date'] = {'date': old['value'], 'classification': old['classification']}
    return result
