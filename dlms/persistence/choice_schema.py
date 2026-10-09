"""Explicit choice presentation order; labels are not identities or positions."""


def migrate(conn):
    columns = {row[1] for row in conn.execute('PRAGMA table_info(choices)')}
    if 'choice_order' not in columns:
        conn.execute('ALTER TABLE choices ADD COLUMN choice_order INTEGER')
        # Existing readers sorted labels. SQLite's ordinary rowid tie-break is
        # made explicit here: equal labels retain their ascending choice IDs.
        rows = conn.execute('SELECT id, question_id FROM choices ORDER BY question_id, label, id').fetchall()
        previous, position = None, 0
        for choice_id, question_id in rows:
            if question_id != previous:
                previous, position = question_id, 0
            conn.execute('UPDATE choices SET choice_order=? WHERE id=?', (position, choice_id))
            position += 1
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_choices_order ON choices(question_id, choice_order)')


def validate(conn):
    # Nullable positions defensively retain legacy/manual SQL rows; all app
    # writers set positions. Such rows use the old label,id fallback ordering.
    if conn.execute("SELECT 1 FROM choices WHERE choice_order IS NOT NULL AND (typeof(choice_order) != 'integer' OR choice_order < 0) LIMIT 1").fetchone():
        raise RuntimeError('DLMS choice order is invalid')

    index = next((row for row in conn.execute("PRAGMA index_list(choices)") if row[1] == 'idx_choices_order'), None)
    columns = [row[2] for row in conn.execute('PRAGMA index_info(idx_choices_order)')]
    if not index or index[2] != 1 or index[4] != 0 or columns != ['question_id', 'choice_order']:
        raise RuntimeError('DLMS choice order index is invalid')
    if conn.execute('SELECT 1 FROM choices WHERE choice_order IS NOT NULL GROUP BY question_id,choice_order HAVING COUNT(*)>1 LIMIT 1').fetchone():
        raise RuntimeError('DLMS choice positions are repeated')
