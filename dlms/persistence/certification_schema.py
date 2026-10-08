"""Earned credentials and user-recorded renewal evidence, separate from learning."""
import re

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
    'certification_cycles': {'id','certification_id','data_json'},
    'certification_training': {'id','data_json'},
    'certification_allocations': {'id','cycle_id','training_id','data_json'},
    'certification_actions': {'request_id','generation','input_hash','result_json'},
}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)


def validate_state(conn):
    rows = conn.execute('SELECT id,generation,revision FROM certification_state').fetchall()
    if (len(rows) != 1 or rows[0][0] != 1 or not isinstance(rows[0][1],str)
            or not re.fullmatch('[0-9a-f]{32}',rows[0][1])
            or type(rows[0][2]) is not int or rows[0][2] < 0):
        raise RuntimeError('Certification state is invalid. Restore a verified backup; no replacement was created.')
    validate_relationship_constraints(conn)


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
