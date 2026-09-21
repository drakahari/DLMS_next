"""Storage chart is a read-only projection of the authoritative snapshot."""
from html.parser import HTMLParser
from unittest.mock import Mock

import pytest

from tests._isolation import ensure_test_data_isolation
ensure_test_data_isolation()
import app
from dlms.routes import maintenance
from dlms.services.storage_health import storage_snapshot, format_size


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.fixture
def report(tmp_path):
    result = storage_snapshot(tmp_path)
    sizes = [80, 0, 15, 1, 1, 1, 1, 0, 0, 1]
    for group, size in zip(result["groups"], sizes):
        group.update(bytes=size, size=format_size(size))
    result.update(bytes=sum(sizes), size=format_size(sum(sizes)), free="999 GiB")
    return result


def render(monkeypatch, report):
    scan = Mock(return_value=report)
    monkeypatch.setattr(maintenance, "storage_snapshot", scan)
    page = app.app.test_client().get("/settings/backup?storage=1")
    assert page.status_code == 200
    scan.assert_called_once()
    return page.get_data(as_text=True)


def test_chart_and_list_share_values_without_free_space_slice(monkeypatch, report):
    html = render(monkeypatch, report)
    elements = Elements(html).elements
    chart = [attrs for tag, attrs in elements if tag == "circle" and "data-bytes" in attrs]
    rows = [attrs for tag, attrs in elements if tag == "li" and "data-bytes" in attrs]
    expected = [(g["label"], str(g["bytes"])) for g in report["groups"]]
    assert [(r["data-category"], r["data-bytes"]) for r in rows] == expected
    assert [(s["data-category"], s["data-bytes"]) for s in chart] == [(k, v) for k, v in expected if int(v)]
    assert sum(float(s["stroke-dasharray"].split()[0]) for s in chart) == pytest.approx(100)
    assert 'stroke-dashoffset="-80.0"' in html
    assert '<strong>100.0 B</strong>' in html
    assert 'aria-label="DLMS storage categories"' in html
    assert 'class="storage-donut" aria-hidden="true"' in html
    assert 'focusable="false"' in html
    assert "Free disk space is separate" in html
    assert "999 GiB" not in html[html.index('<div class="storage-usage"'):html.index('class="settings-image-guidance"', html.index('<div class="storage-usage"'))]


@pytest.mark.parametrize("partial", [False, True])
def test_empty_partial_and_missing_report(monkeypatch, tmp_path, partial):
    report = storage_snapshot(tmp_path)
    report["partial"] = partial
    html = render(monkeypatch, report)
    assert "storage-slice " not in html
    assert "0.0 B" in html
    assert ("Measured portion only — scan incomplete." if partial else "No measured file data.") in html
    assert len([1 for tag, a in Elements(html).elements if tag == "li" and "data-bytes" in a]) == 10
    assert "storage-donut" not in render(monkeypatch, None)


def test_escaping_and_tiny_slice(monkeypatch, report):
    report["groups"][0].update(label='<img src=x onerror="alert(1)">', bytes=10**15)
    report["bytes"] = sum(g["bytes"] for g in report["groups"])
    report["size"] = format_size(report["bytes"])
    html = render(monkeypatch, report)
    assert '<img src=x' not in html and '&lt;img src=x' in html
    chart = [a for t, a in Elements(html).elements if t == "circle" and "data-bytes" in a]
    for segment in chart:
        share, rest = map(float, segment["stroke-dasharray"].split())
        assert 0 < share <= 100 and 0 <= rest < 100


def test_refresh_preserves_data_and_uses_one_snapshot(tmp_path, monkeypatch):
    (tmp_path / "results.db").write_bytes(b"not opened by storage reporting")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    monkeypatch.setattr(app, "APP_DATA_DIR", str(tmp_path))
    client = app.app.test_client()
    for _ in range(2):
        assert client.get("/settings/backup?storage=1").status_code == 200
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
