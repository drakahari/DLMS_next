"""The synthetic facts reader must release its Windows database handle."""
from contextlib import closing
import gc
import hashlib
import os
import sqlite3

import pytest

from tests.settings.gui_native_roundtrip import TABLES, facts


@pytest.mark.skipif(os.name != "nt", reason="Windows SQLite replacement semantics")
def test_facts_closes_database_without_garbage_collection(tmp_path):
    backend = tmp_path / "synthetic backend 日本語"
    backend.mkdir()
    database = backend / "results.db"
    expected_rows = {}
    with closing(sqlite3.connect(database)) as connection:
        for index, table in enumerate(TABLES, 1):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER, value TEXT)')
            value = f"synthetic {table} {index}"
            connection.execute(f'INSERT INTO "{table}" VALUES (?, ?)', (index, value))
            expected_rows[table] = [{"id": index, "value": value}]
        connection.commit()
    expected_assets = {}
    for folder in ("quizzes", "quiz_assets", "data"):
        target = backend / folder / "neutral ü.txt"
        target.parent.mkdir()
        content = f"synthetic {folder}".encode()
        target.write_bytes(content)
        expected_assets[str(target.relative_to(backend))] = hashlib.sha256(content).hexdigest()

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        observed = facts(backend)
        # An unclosed SQLite connection refuses this rename on Windows even
        # after its transaction context exits. No collection obtains this pass.
        moved = backend / "renamed.db"
        database.rename(moved)
        moved.rename(database)
        assert observed == {"rows": expected_rows, "assets": expected_assets}
    finally:
        if was_enabled:
            gc.enable()
