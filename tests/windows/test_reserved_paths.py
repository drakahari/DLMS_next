"""Windows namespace refusals happen before filesystem/device acquisition."""
import os
from pathlib import Path

import pytest

if os.name != 'nt':
    pytest.skip('Windows native namespace', allow_module_level=True)

from desktop import windows_files as wf
from desktop import windows_file_selection as selection


@pytest.mark.parametrize('name', ['CON .txt', ' con  .txt', 'NUL .csv', 'PRN .pdf', 'AUX .png',
                                 'COM1 .txt', 'LPT9 .txt', *[f'{prefix}{digit}.txt' for prefix in ('COM', 'LPT') for digit in '¹²³']])
@pytest.mark.parametrize('component', ['leaf', 'ancestor'])
def test_reserved_aliases_rejected_before_filesystem_inspection(tmp_path, monkeypatch, name, component):
    path = tmp_path / name if component == 'leaf' else tmp_path / name / 'ordinary.txt'
    monkeypatch.setattr(Path, 'lstat', lambda *a, **k: pytest.fail('Reserved namespace must be refused before filesystem inspection'))
    with pytest.raises(ValueError, match='ambiguous or reserved'): wf.assert_path(path)
    with pytest.raises(ValueError, match='ambiguous or reserved'): selection.capture([path])


@pytest.mark.parametrize('name', ['CONsole.txt', 'COM10.txt', 'LPT10.txt', 'COM¹notes.txt', 'normal 日本語.txt'])
def test_nondevice_names_remain_lexically_supported(tmp_path, name):
    assert wf.lexical(tmp_path / name) == tmp_path / name
