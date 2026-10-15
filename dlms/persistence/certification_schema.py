"""Earned credentials and user-recorded renewal evidence, separate from learning."""
import re
import json

STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS certification_state (id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)",
    "INSERT OR IGNORE INTO certification_state(id,generation) VALUES(1,lower(hex(randomblob(16))))",
    "CREATE TABLE IF NOT EXISTS certification_attachments (id TEXT PRIMARY KEY, mime TEXT NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS certifications (id TEXT PRIMARY KEY, data_json TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS certification_cycles (id TEXT PRIMARY KEY, certification_id TEXT NOT NULL REFERENCES certifications(id) ON DELETE CASCADE, data_json TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS certification_training (id TEXT PRIMARY KEY, data_json TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS certification_allocations (id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES certification_cycles(id) ON DELETE CASCADE, training_id TEXT NOT NULL REFERENCES certification_training(id) ON DELETE CASCADE, data_json TEXT NOT NULL, UNIQUE(cycle_id,training_id))",
    "CREATE TABLE IF NOT EXISTS certification_actions (request_id TEXT PRIMARY KEY, generation TEXT NOT NULL, input_hash TEXT NOT NULL, result_json TEXT NOT NULL)",
)
COLUMNS = {
    'certification_state': {'id','generation','revision'},
    'certification_attachments': {'id','mime','sha256','content'},
    'certifications': {'id','data_json'},
    'certification_cycles': {'id','certification_id','data_json','period_order'},
    'certification_training': {'id','data_json'},
    'certification_allocations': {'id','cycle_id','training_id','data_json'},
    'certification_actions': {'request_id','generation','input_hash','result_json'},
}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)


def migrate_periods(conn):
    """Preserve the schema-7 displayed order without guessing any dates."""
    if 'period_order' not in {r[1] for r in conn.execute('PRAGMA table_info(certification_cycles)')}:
        conn.execute('ALTER TABLE certification_cycles ADD COLUMN period_order INTEGER NOT NULL DEFAULT 0')
        rows=conn.execute('SELECT id,certification_id,data_json FROM certification_cycles').fetchall()
        parents={r[1] for r in rows}
        for parent in parents:
            ordered=sorted((r for r in rows if r[1]==parent),key=lambda r:(json.loads(r[2])['start'],r[0]))
            for position,row in enumerate(ordered,1):
                conn.execute('UPDATE certification_cycles SET period_order=? WHERE id=?',(position,row[0]))
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS certification_period_order ON certification_cycles(certification_id,period_order)')


def validate_state(conn):
    rows = conn.execute('SELECT id,generation,revision FROM certification_state').fetchall()
    if (len(rows) != 1 or rows[0][0] != 1 or not isinstance(rows[0][1],str)
            or not re.fullmatch('[0-9a-f]{32}',rows[0][1])
            or type(rows[0][2]) is not int or rows[0][2] < 0):
        raise RuntimeError('Certification state is invalid. Restore a verified backup; no replacement was created.')
    validate_relationship_constraints(conn)
    if 'period_order' in {r[1] for r in conn.execute('PRAGMA table_info(certification_cycles)')}:
        rows=conn.execute('SELECT certification_id,period_order FROM certification_cycles').fetchall()
        if any(type(r[1]) is not int or r[1]<1 for r in rows) or len(set(map(tuple,rows)))!=len(rows):
            raise ValueError('Certification period order is invalid; restore a verified backup.')
        indices=[]
        for row in conn.execute('PRAGMA index_list(certification_cycles)').fetchall():
            if row[2] and not row[4]:indices.append(tuple(r[2] for r in conn.execute('SELECT * FROM pragma_index_info(?)',(row[1],))))
        if ('certification_id','period_order') not in indices:raise ValueError('Certification period order uniqueness is missing; restore a verified backup.')


def validate_relationship_constraints(conn):
    """Imported rows can be valid while their future deletion rules are unsafe."""
    expected = {
        'certification_cycles': {('certification_id', 'certifications', 'id', 'CASCADE')},
        'certification_allocations': {
            ('cycle_id', 'certification_cycles', 'id', 'CASCADE'),
            ('training_id', 'certification_training', 'id', 'CASCADE'),
        },
    }
    for table, required in expected.items():
        actual = {(row[3], row[2], row[4], row[6])
                  for row in conn.execute(f'PRAGMA foreign_key_list({table})')}
        if actual != required:
            raise ValueError('Certification database has incompatible relationship constraints; restore a verified backup.')
    # Inspect index metadata, not an imported SQL string or a trusted index name.
    unique = []
    for row in conn.execute('PRAGMA index_list(certification_allocations)').fetchall():
        if row[2] and not row[4]:
            columns = tuple(item[2] for item in conn.execute(
                'SELECT * FROM pragma_index_info(?)', (row[1],)))
            unique.append(columns)
    if ('cycle_id', 'training_id') not in unique:
        raise ValueError('Certification database is missing its unique activity-per-cycle constraint; restore a verified backup.')


def invalidate(conn):
    conn.execute('UPDATE certification_state SET generation=lower(hex(randomblob(16))),revision=revision+1 WHERE id=1')


def migrate_minutes(conn):
    """Version guard for exact-duration/nullable-estimate JSON; no row conversion.

    Schema-8 writers drop these fields, so must refuse this newer database.
    Existing decimal hours and all history remain byte-for-byte unchanged.
    """
    validate_state(conn)


DATE_TRIGGERS = {
    name: f"""CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON certification_cycles
    WHEN json_type(NEW.data_json,'$.planning_deadline') IS NOT 'text'
      OR json_type(NEW.data_json,'$.renewal_deadline') IS NOT 'text'
      OR json_type(NEW.data_json,'$.renewal') IS NOT NULL
    BEGIN SELECT RAISE(ABORT,'Outdated certification date contract; reopen with the current application.'); END"""
    for name, event in (('certification_dates_insert', 'INSERT'), ('certification_dates_update', 'UPDATE'))
}


def migrate_deadlines(conn):
    """Schema 10: preserve old shared dates, rotate stale forms, block old writers.

    The bootstrap transaction includes rows, triggers, generation and schema version.
    """
    from dlms.services.certification_dates import upgrade_legacy
    version = conn.execute('SELECT version FROM schema_meta WHERE id=1').fetchone()[0]
    installed = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for row in conn.execute('SELECT id,data_json FROM certification_cycles').fetchall():
        data = json.loads(row[1])
        if 'renewal' in data or not all(k in data for k in ('planning_deadline', 'renewal_deadline')):
            data = upgrade_legacy(data, max(7, min(version, 9)))
            conn.execute('UPDATE certification_cycles SET data_json=? WHERE id=?', (json.dumps(data), row[0]))
    for name, statement in DATE_TRIGGERS.items():
        conn.execute('DROP TRIGGER IF EXISTS '+name)
        conn.execute(statement)
    if version<10 or not set(DATE_TRIGGERS) <= installed:
        invalidate(conn)


def validate_date_contract(conn):
    installed = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    if not set(DATE_TRIGGERS) <= installed:
        raise ValueError('Certification date-contract protections are missing; restore a verified backup.')
    canonical=lambda sql:' '.join(sql.lower().replace('if not exists ','').split()).rstrip(';')
    for name, expected in DATE_TRIGGERS.items():
        actual=conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",(name,)).fetchone()[0]
        if canonical(actual)!=canonical(expected):
            raise ValueError('Certification date-contract protections are incompatible.')
    from dlms.services.certification_dates import calendar_day, validate_legacy
    for row in conn.execute('SELECT data_json FROM certification_cycles'):
        data = json.loads(row[0])
        if 'renewal' in data or not all(k in data for k in ('planning_deadline', 'renewal_deadline')):
            raise ValueError('Certification period uses an outdated date contract.')
        for key in ('planning_deadline', 'renewal_deadline'):
            calendar_day(data[key])
        if 'legacy_deadline' in data:
            validate_legacy(data['legacy_deadline'])
