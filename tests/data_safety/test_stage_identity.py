"""Stage review identities stay stable and reject changed or unsafe contents."""
from __future__ import annotations

import pytest

from dlms.services.content_pack_mutations import _staged_pack_tree_sha256


def test_pack_tree_identity_is_order_independent_and_binds_empty_directories(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    for root, order in ((left, ("z", "a")), (right, ("a", "z"))):
        root.mkdir()
        for name in order:
            (root / name).mkdir()
        (root / "z" / "data.bin").write_bytes(b"alpha\x00beta")
        (root / "a" / "manifest.json").write_text("{}")
    assert _staged_pack_tree_sha256(left) == _staged_pack_tree_sha256(right)
    (right / "unused").mkdir()
    assert _staged_pack_tree_sha256(left) != _staged_pack_tree_sha256(right)


def test_pack_tree_identity_binds_binary_content_and_rejects_links(tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    member = root / "data.bin"
    member.write_bytes(b"path\x00one")
    first = _staged_pack_tree_sha256(root)
    member.write_bytes(b"path\x00two")
    assert _staged_pack_tree_sha256(root) != first
    (root / "link").symlink_to(member)
    with pytest.raises(ValueError, match="unsafe"):
        _staged_pack_tree_sha256(root)
