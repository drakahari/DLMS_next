"""Shared validation for persistent certification display preferences."""
import re


def count(value):
    if value == 'all':return 'all'
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError('Choose All or a positive whole number of certifications.')
    value = str(value).strip()
    if not re.fullmatch(r'[0-9]{1,64}', value) or int(value) < 1:
        raise ValueError('Choose All or a positive whole number of certifications.')
    return str(int(value))


def sort(value):
    if value not in ('earned','name','expiration'):
        raise ValueError('Choose Name, Earned date or Expiration date.')
    return value
