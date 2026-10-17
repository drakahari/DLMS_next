"""Native focus protocol/traversal rules without a browser or visible window."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from desktop.webview2_browser import View


@pytest.fixture(scope='module', autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize('reason,expected', [(Qt.FocusReason.TabFocusReason, 'next'),
    (Qt.FocusReason.BacktabFocusReason, 'previous'), (Qt.FocusReason.OtherFocusReason, 'programmatic')])
def test_qt_entry_reason_is_explicit(reason, expected):
    view = View(); view._ready = True; commands = []
    view.command = lambda op, **kw: commands.append((op, kw))
    view.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, reason))
    assert commands == [('focus', {'reason': expected})]
    view._retiring = True
    view.focusInEvent(QFocusEvent(QEvent.Type.FocusIn, reason))
    assert len(commands) == 1


class Node:
    def __init__(self, *, child=False, visible=True, enabled=True, policy=Qt.FocusPolicy.StrongFocus):
        self.child, self.visible, self.enabled, self.policy = child, visible, enabled, policy
        self.focused = []
    def nextInFocusChain(self): return self.next
    def previousInFocusChain(self): return self.previous
    def window(self): return 'same-window'
    def isVisible(self): return self.visible
    def isEnabled(self): return self.enabled
    def focusPolicy(self): return self.policy
    def setFocus(self, reason): self.focused.append(reason)


class FakeView(Node):
    def __init__(self):
        super().__init__(); self._ready, self._retiring = True, False
        self.owner = SimpleNamespace(view=self, _closing=False, _browser_dialog_depth=0, _retiring_browser=None)
    def page(self): return SimpleNamespace(owner=self.owner)
    def isAncestorOf(self, widget): return widget.child


def chain(nodes):
    for index, node in enumerate(nodes): node.next, node.previous = nodes[(index + 1) % len(nodes)], nodes[index - 1]


@pytest.mark.parametrize('direction,reason', [('next', Qt.FocusReason.TabFocusReason), ('previous', Qt.FocusReason.BacktabFocusReason)])
def test_boundary_skips_foreign_container_hidden_disabled_and_non_tab_controls(direction, reason):
    view = FakeView(); target = Node()
    rejected = [Node(child=True), Node(visible=False), Node(enabled=False), Node(policy=Qt.FocusPolicy.ClickFocus)]
    chain([view, *rejected, target] if direction == 'next' else [view, target, *rejected])
    View._leave_browser_focus(view, direction)
    assert target.focused == [reason] and all(not node.focused for node in rejected)


@pytest.mark.parametrize('guard', ['retiring', 'not-ready', 'stale-view', 'closing', 'dialog', 'retirement'])
def test_boundary_cannot_move_focus_from_stale_or_modal_page(guard):
    view, target = FakeView(), Node(); chain([view, target])
    if guard == 'retiring': view._retiring = True
    elif guard == 'not-ready': view._ready = False
    elif guard == 'stale-view': view.owner.view = None
    elif guard == 'closing': view.owner._closing = True
    elif guard == 'dialog': view.owner._browser_dialog_depth = 1
    else: view.owner._retiring_browser = object()
    View._leave_browser_focus(view, 'next')
    assert not target.focused


def test_no_target_ends_without_reentering_browser():
    view, child = FakeView(), Node(child=True); chain([view, child])
    View._leave_browser_focus(view, 'next')
    assert not view.focused and not child.focused


@pytest.mark.parametrize('generation,navigation,accepted', [(3, 8, True), (2, 8, False), (3, 7, False), (None, 8, False)])
def test_native_event_requires_current_document(generation, navigation, accepted):
    directions = []
    view = SimpleNamespace(_active_generation=3, _active_navigation=8, _leave_browser_focus=directions.append)
    event = {'event': 'focus-boundary', 'direction': 'next', 'nav_id': navigation}
    if generation is not None: event['generation'] = generation
    View._event(view, event)
    assert directions == (['next'] if accepted else [])


def test_ancestor_move_position_notification_and_reparent_filter_detach():
    ancestor, new_ancestor = QWidget(), QWidget()
    middle = QWidget(ancestor); view = View(middle); commands = []
    view.command = lambda op, **kw: commands.append((op, kw))
    view._page = SimpleNamespace(owner=SimpleNamespace(view=view, _closing=False, _retiring_browser=None))
    view.native_window, view._ready = object(), True
    view._refresh_position_filters()
    assert ancestor in view._position_ancestors and middle in view._position_ancestors
    QApplication.sendEvent(ancestor, QEvent(QEvent.Type.Move))
    assert commands[-1] == ('position', {})
    view.setParent(new_ancestor)
    assert view._position_ancestors == [new_ancestor]
    before = len(commands)
    QApplication.sendEvent(ancestor, QEvent(QEvent.Type.Move))
    assert len(commands) == before
    QApplication.sendEvent(new_ancestor, QEvent(QEvent.Type.Move))
    assert len(commands) == before + 1
    view._retiring = True; view._detach_position_filters()
    assert view._position_ancestors == []
    QApplication.sendEvent(new_ancestor, QEvent(QEvent.Type.Move))
    assert len(commands) == before + 1


@pytest.mark.parametrize('guard', ['not-ready', 'retiring', 'stale-view', 'closing', 'retirement', 'not-embedded'])
def test_position_notification_refuses_unowned_or_retired_context(guard):
    commands = []
    owner = SimpleNamespace(view=None, _closing=False, _retiring_browser=None)
    view = SimpleNamespace(_ready=True, _retiring=False, native_window=object(),
                           page=lambda: SimpleNamespace(owner=owner), command=lambda op: commands.append(op))
    owner.view = view
    if guard == 'not-ready': view._ready = False
    elif guard == 'retiring': view._retiring = True
    elif guard == 'stale-view': owner.view = None
    elif guard == 'closing': owner._closing = True
    elif guard == 'retirement': owner._retiring_browser = object()
    else: view.native_window = None
    View._notify_parent_position(view)
    assert not commands
