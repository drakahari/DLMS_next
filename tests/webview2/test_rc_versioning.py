import pytest
from package_windows_webview2.versioning import windows_numeric_version

@pytest.mark.parametrize("value", ["3.3.2", "3.3.2 RC1", "3.3.2 RC999"])
def test_numeric_windows_version_preserves_release_components(value):
    assert windows_numeric_version(value) == "3.3.2.0"

@pytest.mark.parametrize("value", ["3.3.2 RC0", "3.3.2 RC1000", "3.3.2;bad", "65536.1.2", "3.3", "3.3.2\n"])
def test_invalid_metadata_is_rejected(value):
    with pytest.raises(ValueError): windows_numeric_version(value)
