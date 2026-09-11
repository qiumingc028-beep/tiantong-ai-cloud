"""Portable ACL policy checks; these do not certify Win32 handle behavior."""
import pytest
from ops.r297_windows_file_security import _validate_acl, _ADMINS, _WRITE

OBSERVER = "S-1-5-21-100-200-300-1001"
CANDIDATE = "S-1-5-21-100-200-300-1002"


@pytest.mark.parametrize("reader", [CANDIDATE, "S-1-1-0", "S-1-5-32-545"])
def test_key_denies_candidate_everyone_and_users_even_with_readonly_bit(reader):
    with pytest.raises(RuntimeError, match="KEY_READER"):
        _validate_acl("S-1-5-32-544", [(0, 0, 1, reader)], observer=OBSERVER, secret=True)


@pytest.mark.parametrize("right", [2, 4, 16, 64, 256, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000])
def test_every_mutation_right_requires_reviewed_sid(right):
    assert _WRITE & right
    with pytest.raises(RuntimeError, match="WRITE_ACE"):
        _validate_acl("S-1-5-32-544", [(0, 0, right, CANDIDATE)])


def test_key_management_keeps_system_admin_and_observer_read_but_not_observer_write():
    entries = [(0, 0, 0x1F01FF, sid) for sid in _ADMINS] + [(0, 0, 0x120089, OBSERVER)]
    _validate_acl("S-1-5-32-544", entries, observer=OBSERVER, secret=True)
    with pytest.raises(RuntimeError, match="WRITE_ACE"):
        _validate_acl("S-1-5-32-544", [(0, 0, 2, OBSERVER)], observer=OBSERVER, secret=True)
    _validate_acl(OBSERVER, [(0, 0, 0x1F01FF, OBSERVER)], observer=OBSERVER, output=True)
    with pytest.raises(RuntimeError, match="OWNER"):
        _validate_acl(CANDIDATE, [], observer=OBSERVER, output=True)


def test_ancestor_sibling_creation_does_not_permit_replacement():
    _validate_acl("S-1-5-32-544", [(0, 0, 6, CANDIDATE)], ancestor=True)
    with pytest.raises(RuntimeError, match="WRITE_ACE"):
        _validate_acl("S-1-5-32-544", [(0, 0, 64, CANDIDATE)], ancestor=True)
    with pytest.raises(RuntimeError, match="UNSUPPORTED_ACE"):
        _validate_acl("S-1-5-32-544", [(9, 0, 0, OBSERVER)])


def test_output_directory_cannot_grant_candidate_write_via_inherit_only_ace():
    with pytest.raises(RuntimeError, match="WRITE_ACE"):
        _validate_acl(OBSERVER, [(0, 9, 2, CANDIDATE)], observer=OBSERVER, output=True, children=True)
    _validate_acl(OBSERVER, [(0, 9, 0x1F01FF, "S-1-3-0")], observer=OBSERVER, output=True, children=True)
