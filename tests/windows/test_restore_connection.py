"""Exercise the actual copied adapter without importing app/startup data."""
import ast
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

@pytest.mark.parametrize("refuse", [False, True])
def test_readonly_certification_validator_closes_connection(tmp_path,monkeypatch,refuse):
    from desktop.frozen_runtime import source_import_path
    source_import_path()
    from dlms.services import certifications
    database=tmp_path/"results.db"
    with sqlite3.connect(database) as connection:connection.execute("CREATE TABLE synthetic (value TEXT)")
    connection.close()
    opened=[]
    class Tracked(sqlite3.Connection):
        closed=False
        def close(self):
            self.closed=True
            return super().close()
    def connect(*args,**kwargs):
        value=sqlite3.connect(*args,**kwargs,factory=Tracked);opened.append(value);return value
    def validate(conn):
        conn.execute("SELECT * FROM synthetic").fetchall()
        if refuse:raise ValueError("synthetic semantic refusal")
    monkeypatch.setattr(certifications,"validate_restored",validate)
    root=Path(__file__).resolve().parents[2]
    tree=ast.parse((root/"app.py").read_text(encoding="utf-8"))
    function=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=="_validate_restored_sqlite")
    scope={"sqlite3":SimpleNamespace(connect=connect),"os":os,
           "_backup_service":SimpleNamespace(validate_restored_sqlite=lambda *a,**kw:{"valid":True}),
           "DLMS_BACKUP_CORE_DB_SCHEMA":{}}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(root/"app.py"),"exec"),scope)
    if refuse:
        with pytest.raises(ValueError,match="semantic refusal"):scope[function.name](database)
    else:assert scope[function.name](database)=={"valid":True}
    assert len(opened)==1 and opened[0].closed
    database.unlink()  # Also proves the native Windows stage handle is released.

@pytest.mark.parametrize("refuse", [False, True])
def test_stage_transaction_commits_or_rolls_back_and_closes(tmp_path,monkeypatch,refuse):
    from desktop.frozen_runtime import source_import_path
    source_import_path()
    from dlms.services import restore
    database=tmp_path/"results.db"
    connection=sqlite3.connect(database);connection.execute("CREATE TABLE synthetic(value TEXT)");connection.close()
    opened=[]
    class Tracked(sqlite3.Connection):
        closed=False
        def close(self):self.closed=True;return super().close()
    def connect(*args,**kwargs):
        value=sqlite3.connect(*args,**kwargs,factory=Tracked);opened.append(value);return value
    monkeypatch.setattr(restore,"sqlite3",SimpleNamespace(connect=connect))
    calls=[]
    def invalidate(conn):
        conn.execute("INSERT INTO synthetic VALUES ('retained transaction semantics')")
        calls.append(True)
        if refuse and len(calls)==2:raise ValueError("synthetic validation refusal")
    for name in ("invalidate_queues","invalidate_mistakes","invalidate_plans","invalidate_marks","invalidate_certifications"):
        monkeypatch.setattr(restore,name,invalidate)
    def validate(path):
        assert all(x.closed for x in opened)
        return {"validated":True}
    kwargs=dict(staged_database_path=lambda root:database,bootstrap_database=lambda path:{},
                validate_current_restored_database=validate,regenerate_staged_quiz_html=lambda *a:{},
                unsupported_schema_error=RuntimeError,future_schema_public_error="newer schema")
    if refuse:
        with pytest.raises(ValueError,match="migrated and validated"):restore.prepare_staged_restore_database(tmp_path,**kwargs)
    else:restore.prepare_staged_restore_database(tmp_path,**kwargs)
    assert len(opened)==1 and opened[0].closed
    connection=sqlite3.connect(database)
    try:assert connection.execute("SELECT COUNT(*) FROM synthetic").fetchone()[0]==(0 if refuse else 5)
    finally:connection.close()
    database.unlink()
