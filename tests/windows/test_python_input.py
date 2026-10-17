"""Checksum lookup and tampered-input refusal before any interpreter runs."""
import base64
import hashlib
from unittest.mock import patch

import pytest
from package_windows.prepare_python import verify_package

def test_publisher_metadata_and_hash_are_both_required():
    payload = b"synthetic CPython package"
    digest = base64.b64encode(hashlib.sha512(payload).digest()).decode()
    metadata = {"id":"python", "version":"3.14.7", "authors":"Python Software Foundation",
                "packageHashAlgorithm":"SHA512", "packageSize":len(payload), "packageHash":digest}
    with patch("package_windows.prepare_python.PUBLISHER_SHA512", digest):
        assert verify_package(payload, metadata) == hashlib.sha512(payload).hexdigest()
        with pytest.raises(ValueError, match="digest mismatch"):
            verify_package(b"X" + payload[1:], metadata)
        for field, value in (("id","other"), ("version","3.14.6"), ("packageHashAlgorithm","SHA256"),
                             ("packageSize",0), ("authors","other"), ("packageHash","")):
            with pytest.raises(ValueError, match="publisher metadata"):
                verify_package(payload, metadata | {field:value})
