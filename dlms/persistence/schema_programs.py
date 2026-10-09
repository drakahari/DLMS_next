"""Reject untrusted SQLite schema programs before validation or migration writes.

DLMS uses ordinary tables/column indexes and two narrowly defined date guards.
Imported SQL is never executed to sanitize a database: unexpected objects fail
closed and the original backup remains available for recovery.
"""
import re

from .certification_schema import DATE_TRIGGERS

_TOKENS = re.compile(r"--[^\n]*(?:\n|$)|/\*[\s\S]*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^]]*\]|[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|<>|!=|[^\s]")


def sql_tokens(sql):
    """Normalize SQL spelling while preserving the meaning of string literals."""
    tokens = []
    for match in _TOKENS.finditer(sql or ''):
        value = match.group()
        if value.startswith(('--', '/*')):
            continue
        if value.startswith("'"):
            tokens.append(value)
        elif value.startswith(('"', '`', '[')):
            tokens.append(value[1:-1].replace(value[0] * 2, value[0]).lower())
        else:
            tokens.append(value.lower())
    return tokens


def _trigger_tokens(sql):
    tokens = sql_tokens(sql)
    if tokens[2:5] == ['if', 'not', 'exists']:
        del tokens[2:5]
    return tokens[:-1] if tokens and tokens[-1] == ';' else tokens


def _check_expressions(tokens):
    for index, token in enumerate(tokens):
        if token != 'check':
            continue
        if tokens[index + 1:index + 2] != ['(']:
            raise ValueError('Invalid restored CHECK constraint')
        depth = 1
        end = index + 2
        while end < len(tokens) and depth:
            depth += (tokens[end] == '(') - (tokens[end] == ')')
            end += 1
        if depth:
            raise ValueError('Invalid restored CHECK constraint')
        yield tokens[index + 2:end - 1]


def validate_schema_programs(conn):
    """Inspect catalog/metadata only, before any imported expression can run.

    This is an executable-schema boundary, not authentication of backup contents
    or protection from vulnerabilities in SQLite itself. Data/structural checks
    still run separately. No extensions or custom SQL functions are loaded.
    """
    from .database import DLMS_SCHEMA_COLUMNS
    conn.execute('PRAGMA trusted_schema = OFF')
    objects = conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master').fetchall()
    for kind, name, table, sql in objects:
        if kind == 'trigger':
            if name not in DATE_TRIGGERS or _trigger_tokens(sql) != _trigger_tokens(DATE_TRIGGERS[name]):
                raise ValueError('Backup contains an unexpected SQLite trigger')
        elif kind == 'view':
            raise ValueError('Backup contains an unexpected SQLite view')
        elif kind == 'table':
            if name not in set(DLMS_SCHEMA_COLUMNS) | {'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4'} or 'virtual' in sql_tokens(sql)[:3]:
                raise ValueError('Backup contains an unexpected SQLite table')
            tokens = sql_tokens(sql)
            expected = ['sequence', '>', '0'] if name == 'study_responses' else ['id', '=', '1']
            allowed_checks = {'schema_meta', 'study_state', 'exam_plan_state', 'review_mark_state', 'certification_state', 'study_responses'}
            for expression in _check_expressions(tokens):
                if name not in allowed_checks or expression != expected:
                    raise ValueError('Backup contains an unexpected SQLite CHECK expression')
            for row in conn.execute(f'PRAGMA table_xinfo("{name}")'):
                if row[6]:
                    raise ValueError('Backup contains an unexpected generated/hidden column')
                default = row[4]
                if default is not None:
                    value = str(default).strip()
                    # Literal defaults and SQLite's built-in timestamp are all
                    # current and legacy DLMS schemas require. No function calls.
                    if not re.fullmatch(r"(?:NULL|TRUE|FALSE|CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME|[+-]?\d+(?:\.\d+)?|'(?:''|[^'])*')", value, re.I):
                        raise ValueError('Backup contains an unexpected SQLite default expression')
            for index, token in enumerate(tokens):
                if token == 'collate' and tokens[index + 1:index + 2] not in (['binary'], ['nocase'], ['rtrim']):
                    raise ValueError('Backup contains an unexpected SQLite collation')
        elif kind == 'index':
            # Quote metadata names safely; index names are imported input.
            quoted = str(name).replace('"', '""')
            index_columns = conn.execute(f'PRAGMA index_xinfo("{quoted}")').fetchall()
            if any(row[1] == -2 for row in index_columns):
                raise ValueError('Backup contains an unexpected SQLite index expression')
            if any(row[4].lower() not in ('binary', 'nocase', 'rtrim') for row in index_columns):
                raise ValueError('Backup contains an unexpected SQLite index collation')
            tokens = sql_tokens(sql)
            if 'where' in tokens:
                predicate = tokens[tokens.index('where') + 1:]
                if (name != 'idx_questions_question_uid_unique' or table != 'questions'
                    or predicate != ['question_uid', 'is', 'not', 'null']):
                    raise ValueError('Backup contains an unexpected SQLite partial index')
        else:
            raise ValueError('Backup contains an unexpected SQLite schema object')
