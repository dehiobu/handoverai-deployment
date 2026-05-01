"""
tests/test_auth.py -- Unit tests for src/auth.py alias resolution and permissions.

No Supabase connection is required — all tests are pure-logic unit tests.
"""
from __future__ import annotations

import pytest

from src.auth import ALIAS_MAP, can_access, resolve_alias


# ---------------------------------------------------------------------------
# Alias resolution — individual aliases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_alias_resolution_admin1():
    email, alias = resolve_alias("admin1")
    assert email == "dennis.ehiobu@sutatscode.com"
    assert alias == "admin1"


@pytest.mark.unit
def test_alias_resolution_gp1():
    email, alias = resolve_alias("gp1")
    assert email == "dr.ehiobu@holmhurst.nhs.uk"
    assert alias == "gp1"


@pytest.mark.unit
def test_alias_resolution_nurse1():
    email, alias = resolve_alias("nurse1")
    assert email == "nurse.jones@holmhurst.nhs.uk"
    assert alias == "nurse1"


@pytest.mark.unit
def test_alias_resolution_mgr1():
    email, alias = resolve_alias("mgr1")
    assert email == "manager@holmhurst.nhs.uk"
    assert alias == "mgr1"


@pytest.mark.unit
def test_alias_resolution_cons1():
    email, alias = resolve_alias("cons1")
    assert email == "dr.waketrent@eastsurrey.nhs.uk"
    assert alias == "cons1"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_invalid_alias_returns_none():
    """An unrecognised alias should pass through unchanged with alias=None."""
    email, alias = resolve_alias("unknown_user")
    assert email == "unknown_user"
    assert alias is None


@pytest.mark.unit
def test_alias_case_insensitive():
    """Alias lookup must be case-insensitive (GP1 → gp1)."""
    email_lower, _ = resolve_alias("gp1")
    email_upper, _ = resolve_alias("GP1")
    email_mixed, _ = resolve_alias("Gp1")
    assert email_lower == email_upper == email_mixed


@pytest.mark.unit
def test_real_email_passthrough():
    """A full email address that is not in ALIAS_MAP returns unchanged."""
    raw = "dr.smith@nhs.uk"
    email, alias = resolve_alias(raw)
    assert email == raw
    assert alias is None


@pytest.mark.unit
def test_alias_map_completeness():
    """All expected aliases exist and map to non-empty NHS emails."""
    expected_aliases = {"admin1", "gp1", "cons1", "nurse1", "mgr1"}
    assert expected_aliases.issubset(set(ALIAS_MAP.keys())), (
        f"Missing aliases: {expected_aliases - set(ALIAS_MAP.keys())}"
    )
    for alias, email in ALIAS_MAP.items():
        assert "@" in email, f"Alias {alias!r} maps to a non-email value: {email!r}"
        assert len(email) > 5, f"Alias {alias!r} maps to a suspiciously short email."


# ---------------------------------------------------------------------------
# Role-based permissions
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_admin_can_access_all_features(monkeypatch):
    """Admin role should have access to every feature."""
    import streamlit as st  # noqa: PLC0415
    monkeypatch.setattr(
        "src.auth.get_current_user",
        lambda: {"role": "admin", "name": "Admin", "email": "a@b.com"},
    )
    for feature in ("triage", "pathway", "dashboard", "governance", "ward", "admin"):
        assert can_access(feature), f"Admin should be able to access {feature!r}"


@pytest.mark.unit
def test_nurse_cannot_access_triage(monkeypatch):
    """Nurse role must not access triage."""
    monkeypatch.setattr(
        "src.auth.get_current_user",
        lambda: {"role": "nurse", "name": "Nurse", "email": "n@b.com"},
    )
    assert not can_access("triage")


@pytest.mark.unit
def test_nurse_can_access_ward(monkeypatch):
    """Nurse role must be able to access ward features."""
    monkeypatch.setattr(
        "src.auth.get_current_user",
        lambda: {"role": "nurse", "name": "Nurse", "email": "n@b.com"},
    )
    assert can_access("ward")


@pytest.mark.unit
def test_manager_cannot_access_triage(monkeypatch):
    """Manager role must not access triage."""
    monkeypatch.setattr(
        "src.auth.get_current_user",
        lambda: {"role": "manager", "name": "Mgr", "email": "m@b.com"},
    )
    assert not can_access("triage")


@pytest.mark.unit
def test_manager_can_access_dashboard(monkeypatch):
    """Manager role must be able to view the dashboard."""
    monkeypatch.setattr(
        "src.auth.get_current_user",
        lambda: {"role": "manager", "name": "Mgr", "email": "m@b.com"},
    )
    assert can_access("dashboard")
