"""
src/auth.py — Supabase Auth wrapper for HandoverAI.

Provides login / logout / session helpers using Supabase Auth.
Falls back gracefully when SUPABASE_URL / SUPABASE_KEY are not configured
(local development without Supabase credentials).
"""
from __future__ import annotations

import os
from datetime import datetime

import streamlit as st


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _get_supabase_creds() -> tuple[str | None, str | None]:
    """Return (SUPABASE_URL, SUPABASE_KEY) from st.secrets then os.environ."""
    url: str | None = None
    key: str | None = None
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
    except Exception:
        pass
    if not url:
        url = os.getenv("SUPABASE_URL")
    if not key:
        key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    return url, key


def init_supabase_client():
    """Return a Supabase client, or None if credentials are not configured.

    Validates that the key looks like a Supabase JWT (starts with 'eyJ' and is
    >100 chars).  A short key means the .env has the database password rather
    than the API anon/service key — catches this early with a clear message.
    """
    url, key = _get_supabase_creds()
    if not url or not key:
        return None
    if not key.startswith("eyJ") or len(key) < 100:
        # Store warning in session state so the login page can surface it
        try:
            import streamlit as _st  # noqa: PLC0415
            _st.session_state["_auth_config_error"] = (
                "SUPABASE_KEY appears to be the database password, not the API key. "
                "Set SUPABASE_KEY to the **anon** (or **service_role**) JWT from "
                "Supabase → Project Settings → API. It should start with 'eyJ' and "
                "be ~200–400 characters long."
            )
        except Exception:
            pass
        return None
    try:
        from supabase import create_client  # noqa: PLC0415
        return create_client(url, key)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Alias map — short usernames for demo / clinical convenience
# ---------------------------------------------------------------------------

ALIAS_MAP: dict[str, str] = {
    "admin1":  "dennis.ehiobu@sutatscode.com",
    "gp1":     "dr.ehiobu@holmhurst.nhs.uk",
    "cons1":   "dr.waketrent@eastsurrey.nhs.uk",
    "nurse1":  "nurse.jones@holmhurst.nhs.uk",
    "mgr1":    "manager@holmhurst.nhs.uk",
}


def resolve_alias(username: str) -> tuple[str, str | None]:
    """Return (real_email, alias_used_or_None) for a username-or-email input.

    If the input is a known alias, the mapped email is returned and the alias
    is captured for audit.  Otherwise the input is returned unchanged.
    """
    stripped = username.strip().lower()
    if stripped in ALIAS_MAP:
        return ALIAS_MAP[stripped], stripped
    return username.strip(), None


# ---------------------------------------------------------------------------
# Auth actions
# ---------------------------------------------------------------------------

def login(username: str, password: str) -> dict:
    """Authenticate with username-or-email + password.

    Aliases (e.g. 'admin1') are resolved to real emails before the Supabase
    call.  The alias is recorded in the returned dict for audit purposes.

    Returns dict with keys:
        success (bool), user (dict | None), error (str | None),
        alias_used (str | None)
    """
    real_email, alias_used = resolve_alias(username)

    client = init_supabase_client()
    if client is None:
        return {
            "success": False, "user": None, "alias_used": alias_used,
            "error": "Supabase not configured — add SUPABASE_URL and SUPABASE_KEY.",
        }

    try:
        response = client.auth.sign_in_with_password(
            {"email": real_email, "password": password}
        )
        user    = response.user
        session = response.session
        meta    = user.user_metadata or {}
        role    = meta.get("role", "gp")
        name    = meta.get("name", real_email.split("@")[0].replace(".", " ").title())

        return {
            "success":    True,
            "error":      None,
            "alias_used": alias_used,
            "user": {
                "id":           user.id,
                "email":        user.email,
                "name":         name,
                "role":         role,
                "alias":        alias_used,
                "last_sign_in": user.last_sign_in_at,
            },
            "access_token": session.access_token,
        }
    except Exception as exc:
        err = str(exc)
        if any(k in err.lower() for k in ("invalid login", "invalid_grant", "credentials")):
            return {"success": False, "user": None, "alias_used": alias_used,
                    "error": "Invalid username/email or password."}
        return {"success": False, "user": None, "alias_used": alias_used,
                "error": f"Login error: {err}"}


def logout() -> None:
    """Sign out from Supabase and clear auth session state."""
    client = init_supabase_client()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    for key in ("auth_user", "auth_login_time", "last_activity"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Session state accessors
# ---------------------------------------------------------------------------

def get_current_user() -> dict | None:
    return st.session_state.get("auth_user")


def is_authenticated() -> bool:
    return st.session_state.get("auth_user") is not None


def get_user_role() -> str:
    user = get_current_user()
    return user.get("role", "gp") if user else "gp"


def get_user_name() -> str:
    user = get_current_user()
    return user.get("name", "Unknown User") if user else "Unknown User"


def get_user_email() -> str:
    user = get_current_user()
    return user.get("email", "") if user else ""


def get_user_alias() -> str | None:
    """Return the alias used to log in, or None if a full email was used."""
    user = get_current_user()
    return user.get("alias") if user else None


# ---------------------------------------------------------------------------
# Role permissions
# ---------------------------------------------------------------------------

_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin":      {"triage", "pathway", "dashboard", "governance", "ward", "admin"},
    "gp":         {"triage", "pathway", "dashboard", "governance", "ward"},
    "consultant": {"triage", "pathway", "dashboard", "governance", "ward"},
    "nurse":      {"pathway", "ward"},
    "manager":    {"dashboard", "governance"},
}


def can_access(feature: str) -> bool:
    """Return True if the current user's role permits the given feature."""
    return feature in _ROLE_PERMISSIONS.get(get_user_role(), set())


# ---------------------------------------------------------------------------
# Session timeout helpers
# ---------------------------------------------------------------------------

SESSION_TIMEOUT_SECONDS  = 3600   # 60 minutes
SESSION_WARNING_SECONDS  = 3300   # 55 minutes


def touch_activity() -> None:
    """Update the last-activity timestamp."""
    st.session_state["last_activity"] = datetime.now()


def check_session_timeout() -> bool:
    """Check timeout; resets on activity.  Returns True if session was expired."""
    if not is_authenticated():
        return False
    last = st.session_state.get("last_activity")
    if last is None:
        touch_activity()
        return False
    elapsed = (datetime.now() - last).total_seconds()
    if elapsed >= SESSION_TIMEOUT_SECONDS:
        return True   # caller should do_logout + rerun
    if elapsed >= SESSION_WARNING_SECONDS:
        remaining = int((SESSION_TIMEOUT_SECONDS - elapsed) / 60)
        st.warning(
            f"Your session will expire in {remaining} minute(s) due to inactivity. "
            "Interact with the app to stay logged in."
        )
    touch_activity()
    return False
