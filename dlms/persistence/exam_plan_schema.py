"""Additive optional planning configuration; never a second learning record store."""
STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS exam_plans (
        id TEXT PRIMARY KEY, config_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        scope_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS exam_plan_state (
        id INTEGER PRIMARY KEY CHECK(id=1), active_plan_id TEXT,
        generation TEXT NOT NULL,
        FOREIGN KEY(active_plan_id) REFERENCES exam_plans(id) ON DELETE SET NULL)""",
    "INSERT OR IGNORE INTO exam_plan_state(id,generation) VALUES(1,lower(hex(randomblob(16))))",
    """CREATE TABLE IF NOT EXISTS exam_plan_actions (
        request_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, generation TEXT NOT NULL,
        input_hash TEXT NOT NULL, quiz_id INTEGER, html TEXT, state TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES exam_plans(id) ON DELETE CASCADE,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE SET NULL)""",
)
COLUMNS = {
    'exam_plans': {'id', 'config_json', 'revision', 'scope_json', 'created_at', 'updated_at'},
    'exam_plan_state': {'id', 'active_plan_id', 'generation'},
    'exam_plan_actions': {'request_id', 'plan_id', 'generation', 'input_hash', 'quiz_id', 'html', 'state'},
}


def migrate(conn):
    for statement in STATEMENTS:
        conn.execute(statement)


def invalidate(conn):
    conn.execute("UPDATE exam_plan_state SET generation=lower(hex(randomblob(16))) WHERE id=1")
