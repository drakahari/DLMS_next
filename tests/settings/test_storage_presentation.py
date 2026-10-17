"""The native chart presents the existing measured groups without redefining them."""
from PySide6.QtWidgets import QApplication

from desktop.settings_surface import THEME_REGISTRY
from desktop.storage_presentation import StorageComposition


def _view():
    app = QApplication.instance() or QApplication([])
    view = StorageComposition()
    return app, view


def _snapshot(amounts, *, partial=False):
    return {"bytes": sum(amounts), "size": f"{sum(amounts)} B", "partial": partial,
            "groups": [{"label": f"Category {index}", "bytes": amount, "size": f"{amount} B"}
                       for index, amount in enumerate(amounts)]}


def test_empty_tiny_and_partial_measurements_keep_exact_legend():
    app, view = _view()
    assert view.set_snapshot(_snapshot([0] * 10))
    assert view.donut.total == 0 and "No measured" in view.note.text()
    assert len(view._labels) == 10
    assert view.set_snapshot(_snapshot([1, 999_999] + [0] * 8, partial=True))
    assert view.donut.total == 1_000_000 and view.donut.partial
    assert view._labels[0].text() == "Category 0: 1 B"
    assert view._labels[1].text() == "Category 1: 999999 B"
    assert "incomplete" in view.note.text()
    assert app is QApplication.instance()


def test_inconsistent_or_unavailable_measurements_draw_no_proportion():
    _, view = _view()
    assert view.set_snapshot(_snapshot([9, 1]))
    wrong = _snapshot([9, 1])
    wrong["bytes"] = 99
    assert not view.set_snapshot(wrong)
    assert view.donut.total == 0 and view._labels == []
    assert "inconsistent" in view.note.text()
    assert not view.set_snapshot({"bytes": None, "groups": []})


def test_all_captured_theme_chart_tokens_apply_without_new_dependencies():
    _, view = _view()
    assert len(THEME_REGISTRY) == 26
    view.set_snapshot(_snapshot([1] * 10))
    for name, entry in THEME_REGISTRY.items():
        view.set_palette(entry)
        assert len(view.donut.segments) == 10, name
        assert all(color.isValid() for color in view.colors), name
        assert all(color.isValid() for _, color in view.donut.segments), name
        assert len({color.name() for color in view.colors}) == 10, name
