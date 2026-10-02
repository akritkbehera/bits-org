"""is_virtual_package: the single predicate that keeps defaults-release and
repository-loader packages out of every store path (upload, reuse, CVMFS
publish). Regression guard for the drift that leaked defaults-release into S3:
CVMFS publish excluded it, the upload/reuse gate did not.
"""
from bits_helpers.utilities import is_virtual_package


def test_defaults_release_is_virtual():
    assert is_virtual_package({"package": "defaults-release", "version": "v1"}) is True


def test_provides_repository_is_virtual():
    assert is_virtual_package({"package": "lcg.bits", "provides_repository": True}) is True


def test_ordinary_package_is_not_virtual():
    assert is_virtual_package({"package": "ROOT", "version": "v6.40.02"}) is False
    # a real package that merely has the key falsy is not virtual
    assert is_virtual_package({"package": "curl", "provides_repository": False}) is False


def test_missing_fields_do_not_raise():
    assert is_virtual_package({}) is False
