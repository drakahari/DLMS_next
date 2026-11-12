"""Explicit investigation scope; these repetitions are not full-gate acceptance."""

import pytest

from tests.browser.test_critical_workflows import test_ai_settings_coherent_save_cancel_and_focus as run_workflow

pytest_plugins = ['tests.browser.test_critical_workflows']
pytestmark = pytest.mark.browser


@pytest.mark.parametrize('iteration', range(10))
@pytest.mark.parametrize('theme', ['light', 'dark', 'ethereal'])
def test_ai_save_diagnostic(browser_stack, iteration, theme):
    run_workflow(browser_stack, theme)
