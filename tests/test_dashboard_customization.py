"""Dashboard settings and durable activity integration regressions."""

import json
import re
from contextlib import closing
from pathlib import Path
from unittest import mock

import pytest

from tests._isolation import ensure_test_data_isolation

ensure_test_data_isolation()
import app as dlms
from dlms.persistence.portal import dashboard_card_defaults
from dlms.services.dashboard_activity import activity_timestamp
from tests.csrf_test_utils import csrf_headers, csrf_token


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    paths = {
        "APP_DATA_DIR": tmp_path, "DB_PATH": tmp_path / "results.db",
        "PORTAL_CONFIG": tmp_path / "config/portal.json",
        "QUIZ_REGISTRY": tmp_path / "config/quizzes.json",
        "CONFIG_FOLDER": tmp_path / "config", "DATA_FOLDER": tmp_path / "data",
        "QUIZ_FOLDER": tmp_path / "quizzes", "QUIZ_ASSET_FOLDER": tmp_path / "quiz_assets",
        "LOGO_FOLDER": tmp_path / "static/logos",
    }
    for name, path in paths.items():
        monkeypatch.setattr(dlms, name, str(path))
        if name.endswith("FOLDER"):
            path.mkdir(parents=True, exist_ok=True)
    dlms._initialize_data_root_ownership(str(tmp_path))
    dlms.ensure_db_initialized()
    dlms.save_registry([])
    return dlms.app.test_client()


def save_cards(client, keys=(), action="save"):
    return client.post("/settings/dashboard/save", data={
        "csrf_token": csrf_token(client, "/settings/dashboard"), "action": action,
        **{f"dashboard_card_{key}": "on" for key in keys},
    })


def activity(client):
    response = client.get("/api/dashboard/quiz-activity")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    return response.get_json()


def publish(title="Current quiz"):
    return dlms._publish_quiz(title, [{
        "number": 1, "type": "choice", "question": "Question?",
        "choices": [{"label": "A", "text": "Yes", "is_correct": True},
                    {"label": "B", "text": "No", "is_correct": False}],
    }], filename_prefix="dashboard_test")


def exam_payload(quiz_id, attempt_id="exam-1"):
    return {"quizId": quiz_id, "attemptId": attempt_id, "mode": "Exam",
            "startedAt": "2026-01-01T12:00:00Z", "completedAt": "2026-01-01T12:01:00Z",
            "score": 1, "total": 1, "percent": 100,
            "responseDetails": [{"attemptQuestionNumber": 1, "questionType": "choice",
                                 "selected": ["A"], "wasCorrect": True}], "missedDetails": []}


def study_payload(quiz_id):
    return {"quizId": quiz_id, "questionOrdinal": 1, "eventId": "study-event-1",
            "sessionId": "study-session-1", "questionType": "choice",
            "selected": ["A"], "wasCorrect": True}


@pytest.mark.parametrize("value", [None, [], "false", 0, {"it": False, "law": "false", "medical": 0}])
def test_legacy_and_malformed_settings_default_visible(dashboard, value):
    config = {"title": "Old settings", "custom_extension": {"keep": True}}
    if value is not None:
        config["dashboard_card_visibility"] = value
    Path(dlms.PORTAL_CONFIG).write_text(json.dumps(config))
    result = dlms.load_portal_config()
    expected = dashboard_card_defaults()
    if isinstance(value, dict):
        expected["it"] = False
    assert result["dashboard_card_visibility"] == expected
    assert result["custom_extension"] == {"keep": True}


def test_all_hidden_restore_and_sidebar_are_independent(dashboard):
    quiz_id, _ = publish()
    dashboard.post("/record_attempt", json=exam_payload(quiz_id), headers=csrf_headers(dashboard))
    registry_before = Path(dlms.QUIZ_REGISTRY).read_bytes()
    with closing(dlms.get_db()) as conn:
        records_before = list(conn.iterdump())
    config = dlms.load_portal_config()
    config.update(study_area_visibility={key: False for key in ("it", "law", "medical", "other")},
                  title="Keep title", excluded_learning_folders=["Keep scope"], custom_extension=7)
    dlms._write_settings_portal_config(config)
    assert save_cards(dashboard).status_code == 302
    full_page = dashboard.get("/").get_data(as_text=True)
    page = full_page.split('<main class="dashboard-main"')[1]
    assert "Keep title" in page and "Customize dashboard" not in page
    assert 'href="/settings"' in full_page.split('<main class="dashboard-main"')[0]
    assert 'href="/settings/layout"' in dashboard.get("/settings").get_data(as_text=True)
    for absent in ('class="dashboard-action-card"', 'class="dashboard-lower-grid"',
                   'class="dashboard-action-grid"', 'id="recentActivity"', 'id="dailyReviewList"',
                   'src="/static/dashboard-activity.js"', 'src="/static/daily-review.js"'):
        assert absent not in page
    # Saving Navigation also leaves dashboard flags alone.
    dashboard.post("/settings/navigation/save", data={"csrf_token": csrf_token(dashboard), "study_area_it": "on"})
    assert not any(dlms.load_portal_config()["dashboard_card_visibility"].values())
    before = dlms.load_portal_config()
    assert save_cards(dashboard, action="defaults").status_code == 302
    after = dlms.load_portal_config()
    assert after.pop("dashboard_card_visibility") == dashboard_card_defaults()
    before.pop("dashboard_card_visibility")
    assert after == before
    assert Path(dlms.QUIZ_REGISTRY).read_bytes() == registry_before
    with closing(dlms.get_db()) as conn:
        assert list(conn.iterdump()) == records_before


def test_every_toggle_renders_independently_and_pack_gate_is_preserved(dashboard):
    shortcuts = {"library": "/library", "build": "/upload", "study_packs": "/study-packs",
                 "it": "/it", "law": "/law", "medical": "/medical", "history": "/history", "study_history": "/study-history",
                 "analytics": "/dashboard", "settings": "/settings"}
    for key in dashboard_card_defaults():
        assert save_cards(dashboard, [key]).status_code == 302
        assert dlms.load_portal_config()["dashboard_card_visibility"][key]
        page = dashboard.get("/").get_data(as_text=True)
        if key in shortcuts:
            assert page.count('class="dashboard-action-card"') == 1
            assert f'class="dashboard-action-card" href="{shortcuts[key]}"' in page
        else:
            assert 'class="dashboard-action-card"' not in page
        assert ('class="dashboard-welcome"' in page) == (key == "welcome")
        assert ('id="dailyReviewList"' in page) == (key == "daily_review")
        if key == "recent_activity":
            assert 'id="recentActivity"' in page and 'id="statAttempts"' not in page
        if key == "overview":
            assert 'id="statAttempts"' in page and 'id="recentActivity"' not in page
    save_cards(dashboard, ["medical"])
    with mock.patch.object(dlms, "discover_content_packs", return_value={}):
        page = dashboard.get("/").get_data(as_text=True)
    assert '<a class="dashboard-action-card" href="/medical">' in page
    assert dlms.load_portal_config()["dashboard_card_visibility"]["medical"] is True
    page = dashboard.get("/settings/dashboard", follow_redirects=True).get_data(as_text=True)
    assert page.count('class="settings-toggle-row"') == 18
    assert "Medical Study remains available without an installed content pack" in page
    from flask import render_template
    with dlms.app.test_request_context("/"):
        page = render_template("dashboard/index.html", visibility=dlms.load_portal_config()["dashboard_card_visibility"], medical_pack_installed=False)
    assert '<a class="dashboard-action-card" href="/medical">' not in page


def test_invalid_action_and_failed_write_preserve_settings(dashboard):
    save_cards(dashboard, ["library"])
    before = Path(dlms.PORTAL_CONFIG).read_bytes()
    assert save_cards(dashboard, action="delete").status_code == 400
    with mock.patch.object(dlms, "_atomic_write_json", side_effect=OSError("test failure")):
        response = save_cards(dashboard, action="defaults")
        assert response.status_code == 500
    assert Path(dlms.PORTAL_CONFIG).read_bytes() == before
    assert save_cards(dashboard, action="defaults").status_code == 302


@pytest.mark.parametrize("keys", [[], ["study_history"], ["history"],
                                 ["recent_activity"], ["study_history", "history", "settings"]])
def test_focus_desk_groups_keep_independent_visibility(dashboard, keys):
    assert save_cards(dashboard, keys).status_code == 302
    main = dashboard.get("/").get_data(as_text=True).split('<main class="dashboard-main"')[1]
    assert ('class="dashboard-history-grid"' in main) == bool(set(keys) & {"study_history", "history"})
    assert ('class="dashboard-quick-tools"' in main) == ("settings" in keys)
    assert ('id="recentActivity"' in main) == ("recent_activity" in keys)
    history = re.search(r'<section class="dashboard-history-grid"[^>]*>(.*?)</section>', main, re.S)
    assert re.findall(r'<a[^>]*href="([^"]+)"', history.group(1) if history else '') == [
        url for key, url in (("study_history", "/study-history"), ("history", "/history")) if key in keys]
    assert 'class="dashboard-customize"' not in main
    assert 'href="/settings"' in dashboard.get("/").get_data(as_text=True).split('<main class="dashboard-main"')[0]



@pytest.mark.parametrize("raw,study,expected", [
    ("2026-01-01 12:00:00", True, "2026-01-01T12:00:00.000000+00:00"),
    ("2026-01-01T13:00:00+01:00", False, "2026-01-01T12:00:00.000000+00:00"),
    ("2026-01-01T12:00:00.123Z", False, "2026-01-01T12:00:00.123000+00:00"),
    ("2026-01-01 12:00:00", False, None), ("2026-01-01T12:00:00", True, None),
    ("2026-02-30T12:00:00Z", False, None), ("2026-01-01", True, None),
    ("2026-01-01T12:00:00+99:00", False, None), (None, False, None), (7, True, None),
    ("2026-01-01T12:00:00+01:99", False, None),
])
def test_timestamp_boundary(raw, study, expected):
    assert activity_timestamp(raw, study) == expected


def test_opening_abandonment_and_durable_save_retries(dashboard):
    quiz_id, html = publish()
    headers = csrf_headers(dashboard)
    dashboard.get(f"/quizzes/{html}")
    assert activity(dashboard)["study"]["record_count"] == 0
    assert activity(dashboard)["exam"]["record_count"] == 0
    payload = study_payload(quiz_id)
    with mock.patch.object(dlms, "_record_learning_event", side_effect=OSError("test failure")):
        assert dashboard.post("/api/learning-events/study-response", json=payload, headers=headers).status_code == 500
    assert activity(dashboard)["study"]["record_count"] == 0
    for _ in range(2):
        assert dashboard.post("/api/learning-events/study-response", json=payload, headers=headers).status_code == 200
    data = activity(dashboard)
    assert data["study"]["record_count"] == 1
    assert data["study"]["entry"]["saved_at"].endswith("+00:00")
    assert data["exam"]["record_count"] == 0
    assert data["recent_attempts"] == []  # Leaving after a Study response adds no attempt.
    payload = exam_payload(quiz_id)
    with mock.patch.object(dlms, "_record_learning_event", side_effect=OSError("test failure")):
        assert dashboard.post("/record_attempt", json=payload, headers=headers).status_code == 500
    assert activity(dashboard)["exam"]["record_count"] == 0
    for _ in range(2):
        assert dashboard.post("/record_attempt", json=payload, headers=headers).status_code == 200
    data = activity(dashboard)
    assert data["exam"]["record_count"] == 1
    assert data["exam"]["entry"]["percent"] == 100
    assert data["recent_attempts"][0]["id"] == "exam-1"


def test_mixed_offsets_undated_records_and_stable_ties(dashboard):
    quiz_id, _html = publish()
    conn = dlms.get_db()
    try:
        for identity, timestamp in [("a", "2026-01-01T14:00:00+03:00"),
                                    ("b", "2026-01-01T12:00:00Z"),
                                    ("c", "2026-01-01T13:00:00+01:00"),
                                    ("d", "2099-01-01T00:00:00"), ("e", "bad"), ("f", None)]:
            conn.execute("INSERT INTO attempts(id, quiz_id, score, total, percent, mode, completed_at) VALUES (?, ?, 1, 1, 100, 'Exam', ?)", (identity, quiz_id, timestamp))
        conn.execute("INSERT INTO learning_events(event_type, quiz_id, mode, occurred_at) VALUES ('study_answer', ?, 'Study', 'bad')", (quiz_id,))
        conn.commit()
        data = activity(dashboard)
        assert data["exam"]["entry"]["id"] == "c"
        assert data["exam"]["record_count"] == 6 and data["exam"]["undated_count"] == 3
        assert data["study"] == {"entry": None, "record_count": 1, "undated_count": 1}
        conn.execute("UPDATE attempts SET completed_at = NULL")
        conn.commit()
        assert activity(dashboard)["exam"] == {"entry": None, "record_count": 6, "undated_count": 6}
        assert dashboard.get("/api/attempts").get_json()["total"] == 6
    finally:
        conn.close()


def test_identity_context_links_and_deletion(dashboard):
    quiz_id, html = publish()
    headers = csrf_headers(dashboard)
    dashboard.post("/record_attempt", json=exam_payload(quiz_id), headers=headers)
    dashboard.post("/api/learning-events/study-response", json=study_payload(quiz_id), headers=headers)
    registry = dlms.load_registry()
    registry[0].update(title="Renamed <quiz>", folder="Moved folder", source_type="it",
                       generated_practice_completion={"mode": "Study", "completed_at": "2099-01-01T00:00:00Z", "reference": "first"})
    dlms.save_registry(registry)
    with mock.patch.object(dlms, "load_registry", wraps=dlms.load_registry) as loaded:
        data = activity(dashboard)
    assert loaded.call_count == 1
    for mode in ("study", "exam"):
        assert data[mode]["entry"]["quiz_title"] == "Renamed <quiz>"
        assert data[mode]["entry"]["folder"] == "Moved folder"
        assert data[mode]["entry"]["origin"] == "IT"
        assert data[mode]["entry"]["quiz_url"] == f"/quizzes/{html}"
    assert not data["study"]["entry"]["saved_at"].startswith("2099")
    other_id, _ = publish("Renamed <quiz>")
    assert other_id != quiz_id
    assert activity(dashboard)["study"]["entry"]["quiz_id"] == quiz_id
    dlms._rebuild_registered_quiz_artifacts()
    assert activity(dashboard)["study"]["entry"]["quiz_url"] == f"/quizzes/{html}"
    json_path = Path(dlms.DATA_FOLDER, html[:-5] + ".json")
    raw_json = json_path.read_bytes()
    json_path.unlink()
    assert activity(dashboard)["study"]["entry"]["quiz_url"] is None
    json_path.write_bytes(raw_json)
    Path(dlms.QUIZ_FOLDER, html).unlink()
    entry = activity(dashboard)["exam"]["entry"]
    assert entry["quiz_url"] is None and entry["availability"] == "Quiz page unavailable"
    assert dashboard.get(f"/api/attempts/{entry['id']}").status_code == 200
    dashboard.post(f"/delete_quiz/{quiz_id}", headers=headers)
    assert activity(dashboard)["exam"]["record_count"] == 0
    assert activity(dashboard)["study"]["record_count"] == 0


@pytest.mark.parametrize("filename", ["../escape.html", "/tmp/escape.html", "bad.js", "sub/quiz.html"])
def test_unsafe_artifact_never_becomes_activity_link(dashboard, filename):
    quiz_id, _ = publish()
    dashboard.post("/record_attempt", json=exam_payload(quiz_id), headers=csrf_headers(dashboard))
    registry = dlms.load_registry()
    registry[0]["html"] = filename
    dlms.save_registry(registry)
    assert activity(dashboard)["exam"]["entry"]["quiz_url"] is None


def test_generated_first_completion_alone_is_not_recent_study(dashboard):
    publish()
    registry = dlms.load_registry()
    registry[0]["generated_practice_completion"] = {
        "mode": "Study", "completed_at": "2026-01-01T12:00:00Z", "reference": "first-run",
    }
    dlms.save_registry(registry)
    assert activity(dashboard)["study"] == {"entry": None, "record_count": 0, "undated_count": 0}


def test_legacy_orphan_and_public_attempt_identity(dashboard):
    conn = dlms.get_db()
    try:
        conn.execute("ALTER TABLE attempts ADD COLUMN attempt_id TEXT")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO attempts(id, attempt_id, quiz_id, score, total, percent, mode, completed_at) VALUES ('private-pk', 'public-id', 999999, 1, 1, 100, 'Exam', '2026-01-01T12:00:00Z')")
        conn.commit()
    finally:
        conn.close()
    entry = activity(dashboard)["exam"]["entry"]
    assert entry["id"] == "public-id"
    assert entry["quiz_url"] is None and entry["availability"] == "Quiz unavailable"
    assert dashboard.get("/api/attempts/public-id").status_code == 200


def test_activity_query_work_is_bounded_and_reads_do_not_write(dashboard):
    quiz_id, _ = publish()
    conn = dlms.get_db()
    try:
        conn.executemany("INSERT INTO learning_events(event_type, quiz_id, mode, occurred_at) VALUES ('study_answer', ?, 'Study', ?)",
                         [(quiz_id, "2026-01-01 12:00:00")] * 1000)
        conn.executemany("INSERT INTO attempts(id, quiz_id, score, total, percent, mode, completed_at) VALUES (?, ?, 1, 1, 100, 'Exam', ?)",
                         [(str(n), quiz_id, "2026-01-01T12:00:00Z") for n in range(1000)])
        conn.commit()
        before = list(conn.iterdump())
        statements = []
        conn.set_trace_callback(statements.append)
        from dlms.services.dashboard_activity import recent_quiz_activity
        with mock.patch.object(dlms, "load_registry", wraps=dlms.load_registry) as registry:
            data = recent_quiz_activity(conn.cursor(), history_context=dlms._attempt_history_context,
                                        attempt_summary=dlms._attempt_summary_from_row,
                                        quiz_folder=dlms.QUIZ_FOLDER, data_folder=dlms.DATA_FOLDER,
                                        quiz_origin=dlms._quiz_history_origin)
        conn.set_trace_callback(None)
        assert registry.call_count == 1
        assert len(statements) == 6  # Column inspection, two summaries, two details, bounded list.
        assert len(data["recent_attempts"]) == 3
        assert data["study"]["record_count"] == data["exam"]["record_count"] == 1000
        assert list(conn.iterdump()) == before
    finally:
        conn.close()


def test_unified_layout_save_preserves_differing_choices_and_scoped_resets(dashboard):
    config = dlms.load_portal_config()
    config.update(theme="ethereal", custom_extension={"keep": 1})
    dlms._write_settings_portal_config(config)
    token = csrf_token(dashboard, "/settings/layout")
    form = {"csrf_token": token, "dashboard_card_it": "on", "dashboard_card_history": "on",
            "study_area_law": "on", "study_area_other": "on"}
    response = dashboard.post("/settings/layout/save", data=form)
    assert response.status_code == 302
    saved = dlms.load_portal_config()
    assert saved["dashboard_card_visibility"]["it"] and not saved["study_area_visibility"]["it"]
    assert saved["study_area_visibility"]["law"] and not saved["dashboard_card_visibility"]["law"]
    assert saved["theme"] == "ethereal" and saved["custom_extension"] == {"keep": 1}
    page = dashboard.get("/settings/layout").get_data(as_text=True)
    assert page.count('name="dashboard_card_') == 14
    assert page.count('name="study_area_') == 4
    assert 'dashboard_card_other' not in page
    assert page.count('value="save"') == 1
    for action, changed, unchanged in (
        ("sidebar_defaults", "study_area_visibility", "dashboard_card_visibility"),
        ("dashboard_defaults", "dashboard_card_visibility", "study_area_visibility"),
    ):
        before = dlms.load_portal_config()
        assert dashboard.post("/settings/layout/save", data={"csrf_token": token, "action": action}).status_code == 302
        after = dlms.load_portal_config()
        assert all(after[changed].values())
        assert after[unchanged] == before[unchanged]
        before.pop(changed)
        after.pop(changed)
        assert after == before


def test_unified_layout_security_failed_save_retry_and_old_entry_points(dashboard):
    for old, anchor in (("dashboard", "dashboard-panels"), ("navigation", "study-areas")):
        response = dashboard.get(f"/settings/{old}?saved=1")
        assert response.status_code == 302
        assert response.location == f"/settings/layout?saved=1#{anchor}"
    assert dashboard.post("/settings/layout/save").status_code == 400
    token = csrf_token(dashboard)
    data = {"csrf_token": token, "dashboard_card_it": "on", "study_area_law": "on"}
    before = Path(dlms.PORTAL_CONFIG).read_bytes()
    assert dashboard.post("/settings/layout/save", data={**data, "action": "unknown"}).status_code == 400
    assert dashboard.post("/settings/layout/save", data=data, headers={"Origin": "https://untrusted.example"}).status_code == 403
    with mock.patch.object(dlms, "_write_settings_portal_config", side_effect=OSError("disk unavailable")):
        assert dashboard.post("/settings/layout/save", data=data).status_code == 500
    assert Path(dlms.PORTAL_CONFIG).read_bytes() == before
    assert dashboard.post("/settings/layout/save", data=data).status_code == 302
    assert dlms.load_portal_config()["dashboard_card_visibility"]["it"]
    assert dlms.load_portal_config()["study_area_visibility"]["law"]


def test_recent_attempts_bounded_deduplicated_by_identity_and_history_preserved(dashboard):
    quiz_id, _ = publish("Identical title")
    headers = csrf_headers(dashboard)
    for index in range(6):
        payload = exam_payload(quiz_id, f"attempt-{index}")
        payload["completedAt"] = f"2026-01-01T12:0{index + 1}:00Z"
        assert dashboard.post("/record_attempt", json=payload, headers=headers).status_code == 200
    data = activity(dashboard)
    assert data["exam"]["entry"]["id"] == "attempt-5"
    assert [row["id"] for row in data["recent_attempts"]] == ["attempt-4", "attempt-3", "attempt-2"]
    assert data["exam"]["record_count"] == 6
    with closing(dlms.get_db()) as conn:
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 6
    page = dashboard.get("/").get_data(as_text=True)
    assert page.index('id="dailyReviewList"') < page.index('id="recentActivity"') < page.index('aria-label="Study and Exam history"') < page.index('id="quickToolsHeading"')
    assert 'dashboard-lower-grid' not in page


@pytest.mark.parametrize('history', [True, False])
def test_new_study_history_inherits_without_rewriting_then_saves_independently(dashboard, history):
    cfg = dlms.load_portal_config()
    cfg['dashboard_card_visibility'] = {'history': history, 'daily_review': False}
    dlms._write_settings_portal_config(cfg)
    before = Path(dlms.PORTAL_CONFIG).read_bytes()
    assert dlms.load_portal_config()['dashboard_card_visibility']['study_history'] is history
    assert Path(dlms.PORTAL_CONFIG).read_bytes() == before
    # Explicit choices win over inheritance, including a false value.
    for selected in (['study_history'], ['history']):
        assert save_cards(dashboard, selected).status_code == 302
        saved = dlms.load_portal_config()['dashboard_card_visibility']
        assert saved['study_history'] is ('study_history' in selected)
        assert saved['history'] is ('history' in selected)
        page = dashboard.get('/').get_data(as_text=True)
        assert ('class="dashboard-action-card" href="/study-history"' in page) is saved['study_history']
        assert ('class="dashboard-action-card" href="/history"' in page) is saved['history']
