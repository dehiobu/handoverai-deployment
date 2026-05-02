"""
src/database.py -- PostgreSQL (Supabase) + SQLite persistence layer.

Uses SQLAlchemy 2 with psycopg2 when DATABASE_URL is set (Supabase / Streamlit
Cloud); falls back to SQLite for local development without Supabase credentials.

All public function signatures are identical to the original SQLite version so
no other module needs changing.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Engine — lazy initialisation (no import-time side-effects; tests stay fast)
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_IS_POSTGRES: bool = False


def _resolve_database_url() -> str | None:
    """Return DATABASE_URL from st.secrets (Streamlit Cloud) then os.getenv (.env)."""
    # 1. Streamlit Cloud secrets  -------------------------------------------
    try:
        import streamlit as st          # noqa: PLC0415
        url = st.secrets["database"]["url"]
        if url:
            return str(url)
    except Exception:
        pass
    # 2. .env / environment variable  ----------------------------------------
    return os.getenv("DATABASE_URL")


def _encode_postgres_url(url: str) -> str:
    """Percent-encode the password in a PostgreSQL connection URL.

    Handles three password formats safely:
    - Raw (e.g. ``[eVeG2kk**LWs2+5HH&UJ]``)  — Python urlparse breaks on ``[``
    - Partially encoded (e.g. ``eVeG2kk**LWs2%2B5HH%26UJ``) — won't double-encode
    - Already fully encoded — returned unchanged

    Strategy: decode first (normalise), then re-encode cleanly.
    """
    import re
    from urllib.parse import unquote
    # Regex split avoids urlparse, which chokes on ``[`` in passwords
    m = re.match(r"^(postgresql://|postgres://)([^:@]+):(.+)@(.+)$", url)
    if not m:
        return url
    scheme, user, raw_password, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    decoded = unquote(raw_password)          # normalise any partial encoding
    encoded = quote(decoded, safe="")        # fully encode for libpq
    if encoded == raw_password:
        return url                           # nothing changed, avoid rebuilding
    return f"{scheme}{user}:{encoded}@{rest}"


def _get_engine() -> Engine:
    """Return (or lazily create) the SQLAlchemy engine."""
    global _engine, _IS_POSTGRES
    if _engine is not None:
        return _engine

    db_url = _resolve_database_url()

    if db_url:
        # Normalise postgres:// → postgresql:// (required by psycopg2)
        if db_url.startswith("postgres://"):
            db_url = "postgresql://" + db_url[len("postgres://"):]
        db_url = _encode_postgres_url(db_url)
        _IS_POSTGRES = True
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    else:
        _IS_POSTGRES = False
        _db_path = Path(__file__).parent.parent / "gp_triage.db"
        _engine = create_engine(
            f"sqlite:///{_db_path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _set_wal(dbapi_conn, _record):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")

    return _engine


@contextmanager
def _conn():
    """Yield a transactional connection — commits on success, rolls back on error."""
    with _get_engine().begin() as conn:
        yield conn


# ---------------------------------------------------------------------------
# DDL — PostgreSQL
# ---------------------------------------------------------------------------

_PG_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS login_audit (
        id                       SERIAL PRIMARY KEY,
        user_email               TEXT,
        user_name                TEXT      DEFAULT '',
        user_role                TEXT      DEFAULT '',
        action                   TEXT,
        alias_used               TEXT      DEFAULT '',
        ip_address               TEXT      DEFAULT 'Not captured',
        timestamp                TIMESTAMP DEFAULT NOW(),
        session_duration_minutes INTEGER   DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shift_handovers (
        id              SERIAL PRIMARY KEY,
        nhs_number      TEXT,
        handed_from     TEXT,
        handed_to       TEXT,
        handover_notes  TEXT      DEFAULT '',
        handover_time   TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS patients (
        id          SERIAL PRIMARY KEY,
        nhs_number  TEXT   UNIQUE NOT NULL,
        name        TEXT   DEFAULT '',
        age         TEXT   DEFAULT '',
        gender      TEXT   DEFAULT '',
        description TEXT   DEFAULT '',
        created_at  TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS triage_sessions (
        id                    SERIAL PRIMARY KEY,
        nhs_number            TEXT,
        triage_decision       TEXT,
        urgency               TEXT,
        clinical_reasoning    TEXT,
        red_flags             TEXT,
        confidence            TEXT,
        nice_guideline        TEXT,
        recommended_action    TEXT,
        differentials         TEXT,
        response_time_seconds REAL      DEFAULT 0,
        clinician_override    TEXT,
        override_reason       TEXT,
        created_at            TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assignments (
        id          SERIAL PRIMARY KEY,
        nhs_number  TEXT,
        doctor_name TEXT,
        specialty   TEXT,
        location    TEXT      DEFAULT '',
        assigned_at TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS referrals (
        id            SERIAL PRIMARY KEY,
        nhs_number    TEXT,
        referral_type TEXT,
        referral_name TEXT,
        urgency       TEXT      DEFAULT '',
        location      TEXT      DEFAULT '',
        created_at    TIMESTAMP DEFAULT NOW(),
        status        TEXT      DEFAULT 'requested'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pathway_stages (
        id           SERIAL PRIMARY KEY,
        nhs_number   TEXT,
        stage_number INTEGER,
        stage_name   TEXT,
        status       TEXT,
        stage_data   TEXT      DEFAULT '{}',
        updated_at   TIMESTAMP DEFAULT NOW(),
        updated_by   TEXT      DEFAULT 'system',
        UNIQUE(nhs_number, stage_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS letters (
        id           SERIAL PRIMARY KEY,
        nhs_number   TEXT,
        letter_type  TEXT,
        content      TEXT      DEFAULT '',
        generated_at TIMESTAMP DEFAULT NOW(),
        emailed_to   TEXT      DEFAULT '',
        emailed_at   TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id           SERIAL PRIMARY KEY,
        nhs_number   TEXT,
        action       TEXT,
        details      TEXT      DEFAULT '',
        performed_by TEXT      DEFAULT 'system',
        created_at   TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ward_logs (
        id          SERIAL PRIMARY KEY,
        nhs_number  TEXT,
        log_date    TEXT,
        shift       TEXT,
        clinician   TEXT,
        role        TEXT,
        subjective  TEXT      DEFAULT '',
        objective   TEXT      DEFAULT '',
        assessment  TEXT      DEFAULT '',
        plan        TEXT      DEFAULT '',
        created_at  TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nurse_observations (
        id               SERIAL PRIMARY KEY,
        nhs_number       TEXT,
        obs_date         TEXT,
        shift            TEXT,
        nurse_name       TEXT,
        temperature      REAL,
        bp_systolic      INTEGER,
        bp_diastolic     INTEGER,
        heart_rate       INTEGER,
        respiratory_rate INTEGER,
        o2_sats          INTEGER,
        avpu             TEXT,
        pain_score       INTEGER   DEFAULT 0,
        fluid_input      INTEGER   DEFAULT 0,
        fluid_output     INTEGER   DEFAULT 0,
        wound_check      TEXT      DEFAULT 'Intact',
        pressure_areas   TEXT      DEFAULT 'Normal',
        news2_score      INTEGER   DEFAULT 0,
        created_at       TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS medications (
        id              SERIAL PRIMARY KEY,
        nhs_number      TEXT,
        med_date        TEXT,
        drug_name       TEXT,
        dose            TEXT,
        route           TEXT,
        frequency       TEXT,
        prescribed_by   TEXT,
        administered_by TEXT,
        status          TEXT      DEFAULT 'Given',
        notes           TEXT      DEFAULT '',
        created_at      TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS safeguarding_flags (
        id               SERIAL PRIMARY KEY,
        nhs_number       TEXT,
        flag_type        TEXT,
        flagged_at       TEXT,
        flagged_by       TEXT,
        details          TEXT      DEFAULT '',
        action_taken     TEXT      DEFAULT '',
        referred_to      TEXT      DEFAULT '',
        reference_number TEXT      DEFAULT '',
        resolved         INTEGER   DEFAULT 0,
        created_at       TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS discharge_checklist (
        id             SERIAL PRIMARY KEY,
        nhs_number     TEXT UNIQUE,
        checklist_data TEXT      DEFAULT '{}',
        updated_at     TIMESTAMP DEFAULT NOW(),
        updated_by     TEXT      DEFAULT 'system'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gp_consultations (
        id                   SERIAL PRIMARY KEY,
        nhs_number           TEXT,
        consultation_date    TEXT,
        gp_name              TEXT,
        gp_email             TEXT      DEFAULT '',
        presenting_complaint TEXT      DEFAULT '',
        examination_findings TEXT      DEFAULT '',
        assessment           TEXT      DEFAULT '',
        plan                 TEXT      DEFAULT '',
        plan_detail          TEXT      DEFAULT '',
        follow_up_date       TEXT      DEFAULT '',
        follow_up_gp         TEXT      DEFAULT '',
        follow_up_surgery    TEXT      DEFAULT '',
        created_at           TIMESTAMP DEFAULT NOW(),
        created_by           TEXT      DEFAULT 'system'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_orders (
        id                   SERIAL PRIMARY KEY,
        nhs_number           TEXT,
        consultation_id      INTEGER   DEFAULT 0,
        test_name            TEXT,
        test_type            TEXT,
        ordered_date         TEXT,
        ordered_by           TEXT,
        status               TEXT      DEFAULT 'pending',
        result_date          TEXT      DEFAULT '',
        result_summary       TEXT      DEFAULT '',
        result_flag          TEXT      DEFAULT 'normal',
        gp_review_notes      TEXT      DEFAULT '',
        action_after_result  TEXT      DEFAULT '',
        notify_nhs_app       INTEGER   DEFAULT 0,
        created_at           TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hospital_admissions (
        id                  SERIAL PRIMARY KEY,
        nhs_number          TEXT,
        admission_date      TEXT,
        hospital_name       TEXT      DEFAULT '',
        ward                TEXT      DEFAULT '',
        consultant          TEXT      DEFAULT '',
        diagnosis           TEXT      DEFAULT '',
        treatment           TEXT      DEFAULT '',
        complications       TEXT      DEFAULT '',
        expected_discharge  TEXT      DEFAULT '',
        created_at          TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS discharge_summaries (
        id                     SERIAL PRIMARY KEY,
        nhs_number             TEXT,
        admission_id           INTEGER   DEFAULT 0,
        discharge_date         TEXT      DEFAULT '',
        discharge_destination  TEXT      DEFAULT '',
        summary_received       INTEGER   DEFAULT 0,
        diagnosis              TEXT      DEFAULT '',
        treatment_given        TEXT      DEFAULT '',
        discharge_medications  TEXT      DEFAULT '',
        follow_up_instructions TEXT      DEFAULT '',
        gp_actions             TEXT      DEFAULT '',
        received_at            TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS case_closures (
        id             SERIAL PRIMARY KEY,
        nhs_number     TEXT UNIQUE,
        closed_date    TEXT,
        closed_by      TEXT,
        closure_reason TEXT      DEFAULT '',
        retention_date TEXT,
        warning_flag   INTEGER   DEFAULT 0,
        case_summary   TEXT      DEFAULT '',
        created_at     TIMESTAMP DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nhs_app_notifications (
        id                    SERIAL PRIMARY KEY,
        nhs_number            TEXT,
        notification_type     TEXT,
        notification_content  TEXT      DEFAULT '',
        sent_at               TIMESTAMP DEFAULT NOW(),
        sent_by               TEXT      DEFAULT 'system',
        patient_acknowledged  INTEGER   DEFAULT 0,
        acknowledged_at       TIMESTAMP
    )
    """,
]

# ---------------------------------------------------------------------------
# DDL — SQLite (fallback)
# ---------------------------------------------------------------------------

_SQLITE_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS login_audit (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email               TEXT,
        user_name                TEXT    DEFAULT '',
        user_role                TEXT    DEFAULT '',
        action                   TEXT,
        alias_used               TEXT    DEFAULT '',
        ip_address               TEXT    DEFAULT 'Not captured',
        timestamp                TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        session_duration_minutes INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shift_handovers (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number     TEXT,
        handed_from    TEXT,
        handed_to      TEXT,
        handover_notes TEXT    DEFAULT '',
        handover_time  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS patients (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number  TEXT    UNIQUE NOT NULL,
        name        TEXT    DEFAULT '',
        age         TEXT    DEFAULT '',
        gender      TEXT    DEFAULT '',
        description TEXT    DEFAULT '',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS triage_sessions (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number            TEXT,
        triage_decision       TEXT,
        urgency               TEXT,
        clinical_reasoning    TEXT,
        red_flags             TEXT,
        confidence            TEXT,
        nice_guideline        TEXT,
        recommended_action    TEXT,
        differentials         TEXT,
        response_time_seconds REAL    DEFAULT 0,
        clinician_override    TEXT,
        override_reason       TEXT,
        created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assignments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number  TEXT,
        doctor_name TEXT,
        specialty   TEXT,
        location    TEXT DEFAULT '',
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS referrals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number    TEXT,
        referral_type TEXT,
        referral_name TEXT,
        urgency       TEXT DEFAULT '',
        location      TEXT DEFAULT '',
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status        TEXT DEFAULT 'requested'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pathway_stages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number   TEXT,
        stage_number INTEGER,
        stage_name   TEXT,
        status       TEXT,
        stage_data   TEXT DEFAULT '{}',
        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by   TEXT DEFAULT 'system',
        UNIQUE(nhs_number, stage_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS letters (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number   TEXT,
        letter_type  TEXT,
        content      TEXT DEFAULT '',
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        emailed_to   TEXT DEFAULT '',
        emailed_at   TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number   TEXT,
        action       TEXT,
        details      TEXT DEFAULT '',
        performed_by TEXT DEFAULT 'system',
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ward_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number  TEXT,
        log_date    TEXT,
        shift       TEXT,
        clinician   TEXT,
        role        TEXT,
        subjective  TEXT DEFAULT '',
        objective   TEXT DEFAULT '',
        assessment  TEXT DEFAULT '',
        plan        TEXT DEFAULT '',
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nurse_observations (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number       TEXT,
        obs_date         TEXT,
        shift            TEXT,
        nurse_name       TEXT,
        temperature      REAL,
        bp_systolic      INTEGER,
        bp_diastolic     INTEGER,
        heart_rate       INTEGER,
        respiratory_rate INTEGER,
        o2_sats          INTEGER,
        avpu             TEXT,
        pain_score       INTEGER DEFAULT 0,
        fluid_input      INTEGER DEFAULT 0,
        fluid_output     INTEGER DEFAULT 0,
        wound_check      TEXT DEFAULT 'Intact',
        pressure_areas   TEXT DEFAULT 'Normal',
        news2_score      INTEGER DEFAULT 0,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS medications (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number      TEXT,
        med_date        TEXT,
        drug_name       TEXT,
        dose            TEXT,
        route           TEXT,
        frequency       TEXT,
        prescribed_by   TEXT,
        administered_by TEXT,
        status          TEXT DEFAULT 'Given',
        notes           TEXT DEFAULT '',
        created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS safeguarding_flags (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number       TEXT,
        flag_type        TEXT,
        flagged_at       TEXT,
        flagged_by       TEXT,
        details          TEXT DEFAULT '',
        action_taken     TEXT DEFAULT '',
        referred_to      TEXT DEFAULT '',
        reference_number TEXT DEFAULT '',
        resolved         INTEGER DEFAULT 0,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS discharge_checklist (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number     TEXT UNIQUE,
        checklist_data TEXT DEFAULT '{}',
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_by     TEXT DEFAULT 'system'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gp_consultations (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number           TEXT,
        consultation_date    TEXT,
        gp_name              TEXT,
        gp_email             TEXT DEFAULT '',
        presenting_complaint TEXT DEFAULT '',
        examination_findings TEXT DEFAULT '',
        assessment           TEXT DEFAULT '',
        plan                 TEXT DEFAULT '',
        plan_detail          TEXT DEFAULT '',
        follow_up_date       TEXT DEFAULT '',
        follow_up_gp         TEXT DEFAULT '',
        follow_up_surgery    TEXT DEFAULT '',
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by           TEXT DEFAULT 'system'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS test_orders (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number          TEXT,
        consultation_id     INTEGER DEFAULT 0,
        test_name           TEXT,
        test_type           TEXT,
        ordered_date        TEXT,
        ordered_by          TEXT,
        status              TEXT DEFAULT 'pending',
        result_date         TEXT DEFAULT '',
        result_summary      TEXT DEFAULT '',
        result_flag         TEXT DEFAULT 'normal',
        gp_review_notes     TEXT DEFAULT '',
        action_after_result TEXT DEFAULT '',
        notify_nhs_app      INTEGER DEFAULT 0,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hospital_admissions (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number         TEXT,
        admission_date     TEXT,
        hospital_name      TEXT DEFAULT '',
        ward               TEXT DEFAULT '',
        consultant         TEXT DEFAULT '',
        diagnosis          TEXT DEFAULT '',
        treatment          TEXT DEFAULT '',
        complications      TEXT DEFAULT '',
        expected_discharge TEXT DEFAULT '',
        created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS discharge_summaries (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number             TEXT,
        admission_id           INTEGER DEFAULT 0,
        discharge_date         TEXT DEFAULT '',
        discharge_destination  TEXT DEFAULT '',
        summary_received       INTEGER DEFAULT 0,
        diagnosis              TEXT DEFAULT '',
        treatment_given        TEXT DEFAULT '',
        discharge_medications  TEXT DEFAULT '',
        follow_up_instructions TEXT DEFAULT '',
        gp_actions             TEXT DEFAULT '',
        received_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS case_closures (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number     TEXT UNIQUE,
        closed_date    TEXT,
        closed_by      TEXT,
        closure_reason TEXT DEFAULT '',
        retention_date TEXT,
        warning_flag   INTEGER DEFAULT 0,
        case_summary   TEXT DEFAULT '',
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nhs_app_notifications (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number           TEXT,
        notification_type    TEXT,
        notification_content TEXT DEFAULT '',
        sent_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sent_by              TEXT DEFAULT 'system',
        patient_acknowledged INTEGER DEFAULT 0,
        acknowledged_at      TIMESTAMP
    )
    """,
]


# ---------------------------------------------------------------------------
# Row helper + datetime serialiser
# ---------------------------------------------------------------------------

def _serialize_value(v):
    """Recursively convert datetime/date objects to ISO-format strings."""
    import datetime as _dt
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_serialize_value(item) for item in v]
    return v


def _row(row) -> dict:
    """Convert a SQLAlchemy Row to a plain dict with all datetime values
    normalised to ISO-format strings so callers never receive bare datetime
    objects (Supabase/psycopg2 returns proper datetime objects; SQLite
    returns strings — this makes behaviour identical for both backends)."""
    return {k: _serialize_value(v) for k, v in dict(row._mapping).items()}


# ---------------------------------------------------------------------------
# SQLite migration helper
# ---------------------------------------------------------------------------

def _sqlite_add_col(conn, table: str, col_name: str, col_def: str) -> None:
    """Add a column to a SQLite table if it does not already exist."""
    try:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"))
    except Exception:
        pass  # Column already exists


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not already exist (idempotent)."""
    # _get_engine() sets _IS_POSTGRES; call it before reading the flag.
    # The DDL list is selected *inside* the with-block so the flag is always set.
    with _conn() as conn:
        ddl = _PG_DDL if _IS_POSTGRES else _SQLITE_DDL
        for stmt in ddl:
            conn.execute(text(stmt))

        # ── Incremental migrations (safe to re-run) ──────────────────────────
        if _IS_POSTGRES:
            conn.execute(text(
                "ALTER TABLE login_audit ADD COLUMN IF NOT EXISTS alias_used TEXT DEFAULT ''"
            ))
            # referrals: extra columns for GP workflow
            for col_def in [
                "referral_category TEXT DEFAULT ''",
                "hospital_name TEXT DEFAULT ''",
                "department TEXT DEFAULT ''",
                "specialty TEXT DEFAULT ''",
                "ereferral_reference TEXT DEFAULT ''",
                "ereferral_status TEXT DEFAULT 'draft'",
                "email_sent INTEGER DEFAULT 0",
                "email_sent_at TEXT DEFAULT ''",
            ]:
                col_name = col_def.split()[0]
                conn.execute(text(
                    f"ALTER TABLE referrals ADD COLUMN IF NOT EXISTS {col_def}"
                ))
        else:
            _sqlite_add_col(conn, "login_audit", "alias_used", "TEXT DEFAULT ''")
            for col_def in [
                "referral_category TEXT DEFAULT ''",
                "hospital_name TEXT DEFAULT ''",
                "department TEXT DEFAULT ''",
                "specialty TEXT DEFAULT ''",
                "ereferral_reference TEXT DEFAULT ''",
                "ereferral_status TEXT DEFAULT 'draft'",
                "email_sent INTEGER DEFAULT 0",
                "email_sent_at TEXT DEFAULT ''",
            ]:
                _sqlite_add_col(conn, "referrals", col_def.split()[0], " ".join(col_def.split()[1:]))

        # ensemble_results column on triage_sessions (Phase 8 — ClinisenseAI)
        if _IS_POSTGRES:
            conn.execute(text(
                "ALTER TABLE triage_sessions ADD COLUMN IF NOT EXISTS "
                "ensemble_results TEXT"
            ))
        else:
            _sqlite_add_col(conn, "triage_sessions", "ensemble_results", "TEXT")

        # name column on patients (added for named demo patients)
        if _IS_POSTGRES:
            conn.execute(text(
                "ALTER TABLE patients ADD COLUMN IF NOT EXISTS name TEXT DEFAULT ''"
            ))
        else:
            _sqlite_add_col(conn, "patients", "name", "TEXT DEFAULT ''")


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def save_patient(nhs_number: str, age: str = "", gender: str = "",
                 description: str = "", name: str = "") -> None:
    """Insert or update a patient record."""
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO patients (nhs_number, name, age, gender, description)
                VALUES (:nhs, :name, :age, :gender, :desc)
                ON CONFLICT(nhs_number) DO UPDATE SET
                    name        = EXCLUDED.name,
                    age         = EXCLUDED.age,
                    gender      = EXCLUDED.gender,
                    description = EXCLUDED.description
            """),
            {"nhs": nhs_number, "name": name, "age": age, "gender": gender, "desc": description},
        )


def save_triage(nhs_number: str, result_dict: dict,
                response_time: float = 0.0,
                ensemble_results: dict | None = None) -> int:
    """Persist a triage session. Returns the new row id.

    Parameters
    ----------
    ensemble_results : dict | None
        ClinisenseAI ensemble result dict — stored as JSON in the
        ensemble_results column when provided.
    """
    ensemble_json = json.dumps(ensemble_results) if ensemble_results else None
    params = {
        "nhs":      nhs_number,
        "dec":      result_dict.get("triage_decision", ""),
        "urg":      result_dict.get("urgency_timeframe", ""),
        "reas":     result_dict.get("clinical_reasoning", ""),
        "flags":    result_dict.get("red_flags", ""),
        "conf":     result_dict.get("confidence", ""),
        "nice":     result_dict.get("nice_guideline", ""),
        "action":   result_dict.get("recommended_action", ""),
        "diff":     result_dict.get("differentials", ""),
        "rt":       response_time,
        "ensemble": ensemble_json,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO triage_sessions
                        (nhs_number, triage_decision, urgency, clinical_reasoning,
                         red_flags, confidence, nice_guideline, recommended_action,
                         differentials, response_time_seconds, ensemble_results)
                    VALUES (:nhs, :dec, :urg, :reas, :flags, :conf, :nice, :action,
                            :diff, :rt, :ensemble)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO triage_sessions
                        (nhs_number, triage_decision, urgency, clinical_reasoning,
                         red_flags, confidence, nice_guideline, recommended_action,
                         differentials, response_time_seconds, ensemble_results)
                    VALUES (:nhs, :dec, :urg, :reas, :flags, :conf, :nice, :action,
                            :diff, :rt, :ensemble)
                """),
                params,
            )
            return result.lastrowid


def save_assignment(nhs_number: str, doctor_name: str, specialty: str,
                    location: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO assignments (nhs_number, doctor_name, specialty, location)
                VALUES (:nhs, :doc, :spec, :loc)
            """),
            {"nhs": nhs_number, "doc": doctor_name, "spec": specialty, "loc": location},
        )


def save_referral(nhs_number: str, referral_type: str, referral_name: str,
                  urgency: str = "", location: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO referrals
                    (nhs_number, referral_type, referral_name, urgency, location)
                VALUES (:nhs, :rtype, :rname, :urg, :loc)
            """),
            {"nhs": nhs_number, "rtype": referral_type, "rname": referral_name,
             "urg": urgency, "loc": location},
        )


def save_pathway_stage(nhs_number: str, stage_number: int, stage_name: str,
                       status: str, data_dict: dict,
                       updated_by: str = "system") -> None:
    """Upsert a single pathway stage row."""
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO pathway_stages
                    (nhs_number, stage_number, stage_name, status,
                     stage_data, updated_at, updated_by)
                VALUES (:nhs, :snum, :sname, :status, :data, :ts, :by)
                ON CONFLICT(nhs_number, stage_number) DO UPDATE SET
                    stage_name = EXCLUDED.stage_name,
                    status     = EXCLUDED.status,
                    stage_data = EXCLUDED.stage_data,
                    updated_at = EXCLUDED.updated_at,
                    updated_by = EXCLUDED.updated_by
            """),
            {
                "nhs":    nhs_number,
                "snum":   stage_number,
                "sname":  stage_name,
                "status": status,
                "data":   json.dumps(data_dict),
                "ts":     datetime.now().isoformat(),
                "by":     updated_by,
            },
        )


def save_letter(nhs_number: str, letter_type: str, content: str,
                emailed_to: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO letters (nhs_number, letter_type, content, emailed_to)
                VALUES (:nhs, :ltype, :content, :email)
            """),
            {"nhs": nhs_number, "ltype": letter_type,
             "content": content, "email": emailed_to},
        )


def save_audit(nhs_number: str, action: str, details: str,
               performed_by: str = "system") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO audit_log (nhs_number, action, details, performed_by)
                VALUES (:nhs, :action, :details, :by)
            """),
            {"nhs": nhs_number, "action": action,
             "details": details, "by": performed_by},
        )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_patient(nhs_number: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            text("SELECT * FROM patients WHERE nhs_number = :nhs"),
            {"nhs": nhs_number},
        ).fetchone()
        return _row(row) if row else None


def get_full_pathway(nhs_number: str) -> list[dict]:
    """Return all stage rows for a patient ordered by stage_number."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM pathway_stages
                WHERE nhs_number = :nhs ORDER BY stage_number
            """),
            {"nhs": nhs_number},
        ).fetchall()
        result = []
        for row in rows:
            d = _row(row)
            d["stage_data"] = json.loads(d["stage_data"] or "{}")
            result.append(d)
        return result


def get_all_patients() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM patients ORDER BY created_at DESC")
        ).fetchall()
        return [_row(r) for r in rows]


def get_all_triage_sessions() -> list[dict]:
    """Return all triage sessions, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM triage_sessions ORDER BY created_at DESC")
        ).fetchall()
        return [_row(r) for r in rows]


def get_dashboard_stats() -> dict:
    """Aggregate stats across all historical triage sessions in the DB."""
    with _conn() as conn:
        total = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions")
        ).fetchone()[0]
        if not total:
            return {}
        red = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='RED'")
        ).fetchone()[0]
        amber = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='AMBER'")
        ).fetchone()[0]
        green = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='GREEN'")
        ).fetchone()[0]
        overrides = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions WHERE clinician_override IS NOT NULL")
        ).fetchone()[0]
        avg_row = conn.execute(
            text("SELECT AVG(response_time_seconds) FROM triage_sessions")
        ).fetchone()
        avg_time = avg_row[0] or 0.0
        total_patients = conn.execute(
            text("SELECT COUNT(*) FROM patients")
        ).fetchone()[0]
        discharged = conn.execute(
            text("""
                SELECT COUNT(DISTINCT nhs_number) FROM pathway_stages
                WHERE stage_number = 10 AND status = 'complete'
            """)
        ).fetchone()[0]
        return {
            "total":            total,
            "red":              red,
            "amber":            amber,
            "green":            green,
            "overrides":        overrides,
            "override_rate_pct": overrides / total * 100 if total else 0,
            "avg_response_s":   avg_time,
            "total_patients":   total_patients,
            "discharged":       discharged,
        }


def get_ensemble_stats() -> dict:
    """Aggregate ClinisenseAI ensemble stats from triage_sessions."""
    with _conn() as conn:
        total_ensemble = conn.execute(
            text("SELECT COUNT(*) FROM triage_sessions WHERE ensemble_results IS NOT NULL")
        ).fetchone()[0]
        if not total_ensemble:
            return {"total_ensemble": 0}

        # Fetch all ensemble JSON blobs for analysis
        rows = conn.execute(
            text(
                "SELECT ensemble_results FROM triage_sessions "
                "WHERE ensemble_results IS NOT NULL"
            )
        ).fetchall()

    scores: list[float] = []
    mandatory_count = 0
    disagreement_pairs: dict[str, int] = {}
    total_times: list[float] = []

    for (blob,) in rows:
        try:
            data = json.loads(blob or "{}")
        except Exception:
            continue
        score = data.get("agreement_score")
        if score is not None:
            scores.append(float(score))
        if data.get("mandatory_review"):
            mandatory_count += 1
        disagreements = data.get("disagreements") or ""
        if disagreements and disagreements.lower() not in ("", "none", "n/a"):
            key = disagreements[:80]
            disagreement_pairs[key] = disagreement_pairs.get(key, 0) + 1
        tt = data.get("total_time")
        if tt is not None:
            total_times.append(float(tt))

    avg_score = sum(scores) / len(scores) if scores else 0.0
    avg_time  = sum(total_times) / len(total_times) if total_times else 0.0
    top_disagreement = (
        max(disagreement_pairs, key=lambda k: disagreement_pairs[k])
        if disagreement_pairs else "None recorded"
    )

    return {
        "total_ensemble":       total_ensemble,
        "avg_agreement_score":  round(avg_score, 1),
        "mandatory_review_count": mandatory_count,
        "top_disagreement":     top_disagreement,
        "avg_response_time_s":  round(avg_time, 2),
    }


def search_patients(query: str) -> list[dict]:
    """Case-insensitive search by NHS number or description."""
    like = f"%{query}%"
    with _conn() as conn:
        # PostgreSQL: ILIKE for case-insensitive; SQLite LIKE is already case-insensitive for ASCII
        like_op = "ILIKE" if _IS_POSTGRES else "LIKE"
        rows = conn.execute(
            text(f"""
                SELECT * FROM patients
                WHERE nhs_number {like_op} :like OR description {like_op} :like
                ORDER BY created_at DESC
            """),
            {"like": like},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Ward log
# ---------------------------------------------------------------------------

def save_ward_log(nhs_number: str, log_date: str, shift: str, clinician: str,
                  role: str, subjective: str, objective: str,
                  assessment: str, plan: str) -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO ward_logs
                    (nhs_number, log_date, shift, clinician, role,
                     subjective, objective, assessment, plan)
                VALUES (:nhs, :ld, :shift, :clin, :role, :subj, :obj, :assess, :plan)
            """),
            {"nhs": nhs_number, "ld": log_date, "shift": shift,
             "clin": clinician, "role": role, "subj": subjective,
             "obj": objective, "assess": assessment, "plan": plan},
        )


def get_ward_logs(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM ward_logs WHERE nhs_number=:nhs ORDER BY created_at DESC"),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Nurse observations
# ---------------------------------------------------------------------------

def save_observation(nhs_number: str, obs_date: str, shift: str,
                     nurse_name: str, temperature: float, bp_systolic: int,
                     bp_diastolic: int, heart_rate: int, respiratory_rate: int,
                     o2_sats: int, avpu: str, pain_score: int,
                     fluid_input: int, fluid_output: int,
                     wound_check: str, pressure_areas: str,
                     news2_score: int) -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO nurse_observations
                    (nhs_number, obs_date, shift, nurse_name, temperature,
                     bp_systolic, bp_diastolic, heart_rate, respiratory_rate,
                     o2_sats, avpu, pain_score, fluid_input, fluid_output,
                     wound_check, pressure_areas, news2_score)
                VALUES (:nhs, :od, :shift, :nurse, :temp, :bps, :bpd, :hr,
                        :rr, :o2, :avpu, :pain, :fi, :fo, :wc, :pa, :news2)
            """),
            {
                "nhs": nhs_number, "od": obs_date, "shift": shift,
                "nurse": nurse_name, "temp": temperature,
                "bps": bp_systolic, "bpd": bp_diastolic,
                "hr": heart_rate, "rr": respiratory_rate,
                "o2": o2_sats, "avpu": avpu, "pain": pain_score,
                "fi": fluid_input, "fo": fluid_output,
                "wc": wound_check, "pa": pressure_areas,
                "news2": news2_score,
            },
        )


def get_observations(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM nurse_observations
                WHERE nhs_number=:nhs ORDER BY created_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

def save_medication(nhs_number: str, med_date: str, drug_name: str,
                    dose: str, route: str, frequency: str,
                    prescribed_by: str, administered_by: str,
                    status: str, notes: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO medications
                    (nhs_number, med_date, drug_name, dose, route, frequency,
                     prescribed_by, administered_by, status, notes)
                VALUES (:nhs, :md, :drug, :dose, :route, :freq,
                        :pby, :aby, :status, :notes)
            """),
            {
                "nhs": nhs_number, "md": med_date, "drug": drug_name,
                "dose": dose, "route": route, "freq": frequency,
                "pby": prescribed_by, "aby": administered_by,
                "status": status, "notes": notes,
            },
        )


def get_medications(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM medications WHERE nhs_number=:nhs ORDER BY created_at DESC"),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Safeguarding flags
# ---------------------------------------------------------------------------

def save_safeguarding_flag(nhs_number: str, flag_type: str, flagged_at: str,
                           flagged_by: str, details: str = "",
                           action_taken: str = "", referred_to: str = "",
                           reference_number: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO safeguarding_flags
                    (nhs_number, flag_type, flagged_at, flagged_by, details,
                     action_taken, referred_to, reference_number)
                VALUES (:nhs, :ft, :fat, :fby, :det, :act, :ref, :refno)
            """),
            {
                "nhs": nhs_number, "ft": flag_type, "fat": flagged_at,
                "fby": flagged_by, "det": details, "act": action_taken,
                "ref": referred_to, "refno": reference_number,
            },
        )


def get_safeguarding_flags(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM safeguarding_flags
                WHERE nhs_number=:nhs ORDER BY created_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Discharge checklist
# ---------------------------------------------------------------------------

def update_discharge_checklist(nhs_number: str, checklist_dict: dict,
                                updated_by: str = "system") -> None:
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO discharge_checklist (nhs_number, checklist_data, updated_at, updated_by)
                VALUES (:nhs, :data, :ts, :by)
                ON CONFLICT(nhs_number) DO UPDATE SET
                    checklist_data = EXCLUDED.checklist_data,
                    updated_at     = EXCLUDED.updated_at,
                    updated_by     = EXCLUDED.updated_by
            """),
            {
                "nhs":  nhs_number,
                "data": json.dumps(checklist_dict),
                "ts":   datetime.now().isoformat(),
                "by":   updated_by,
            },
        )


def get_discharge_checklist(nhs_number: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            text("SELECT checklist_data FROM discharge_checklist WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchone()
        if row:
            return json.loads(row[0] or "{}")
        return {}


# ---------------------------------------------------------------------------
# Ward overview (for dashboard)
# ---------------------------------------------------------------------------

def get_ward_overview_stats() -> dict:
    """Aggregate ward stats for the dashboard ward overview section."""
    with _conn() as conn:
        # Patients admitted but not case-closed (stage 6 = Admission in new workflow)
        admitted = conn.execute(
            text("""
                SELECT COUNT(DISTINCT p6.nhs_number)
                FROM pathway_stages p6
                LEFT JOIN pathway_stages p10
                    ON p6.nhs_number = p10.nhs_number AND p10.stage_number = 10
                WHERE p6.stage_number = 6 AND p6.status = 'complete'
                  AND (p10.status IS NULL OR p10.status != 'complete')
            """)
        ).fetchone()[0]

        # Latest NEWS2 per patient
        obs_rows = conn.execute(
            text("""
                SELECT nhs_number, news2_score
                FROM nurse_observations
                WHERE id IN (
                    SELECT MAX(id) FROM nurse_observations GROUP BY nhs_number
                )
            """)
        ).fetchall()
        news2_scores = [r[1] for r in obs_rows if r[1] is not None]
        avg_news2  = sum(news2_scores) / len(news2_scores) if news2_scores else 0
        red_alerts = sum(1 for s in news2_scores if s >= 7)

        # Unresolved safeguarding flags
        safeguarding = conn.execute(
            text("SELECT COUNT(*) FROM safeguarding_flags WHERE resolved=0")
        ).fetchone()[0]

        # Awaiting case closure: stage 9 complete, stage 10 not complete
        awaiting_dc = conn.execute(
            text("""
                SELECT COUNT(DISTINCT p9.nhs_number)
                FROM pathway_stages p9
                LEFT JOIN pathway_stages p10
                    ON p9.nhs_number = p10.nhs_number AND p10.stage_number = 10
                WHERE p9.stage_number = 9 AND p9.status = 'complete'
                  AND (p10.status IS NULL OR p10.status != 'complete')
            """)
        ).fetchone()[0]

        # Average length of stay — from hospital_admissions table
        los_rows = conn.execute(
            text("""
                SELECT stage_data FROM pathway_stages
                WHERE stage_number = 8 AND status = 'complete'
            """)
        ).fetchall()
        los_values = []
        for row in los_rows:
            data = json.loads(row[0] or "{}")
            los_str = data.get("length_of_stay", "")
            if "day" in str(los_str):
                try:
                    los_values.append(int(str(los_str).split()[0]))
                except (ValueError, IndexError):
                    pass
        avg_los = sum(los_values) / len(los_values) if los_values else 0

        return {
            "current_inpatients": admitted,
            "avg_news2":          round(avg_news2, 1),
            "red_news2_alerts":   red_alerts,
            "safeguarding_flags": safeguarding,
            "awaiting_discharge": awaiting_dc,
            "avg_los_days":       round(avg_los, 1),
        }


# ---------------------------------------------------------------------------
# Timeline helper — all events for a patient in chronological order
# ---------------------------------------------------------------------------

def get_patient_timeline(nhs_number: str) -> list[dict]:
    """Aggregate all datable events for a patient, sorted by timestamp."""
    events: list[dict] = []

    with _conn() as conn:
        # Triage
        for r in conn.execute(
            text("SELECT * FROM triage_sessions WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["created_at"], "stage": "Triage",
                "action": f"AI triage: {d['triage_decision']} -- {d['urgency']}",
                "clinician": "AI System", "category": "triage",
            })

        # Pathway stages
        for r in conn.execute(
            text("""
                SELECT * FROM pathway_stages
                WHERE nhs_number=:nhs AND status='complete'
                ORDER BY stage_number
            """),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            data = json.loads(d["stage_data"] or "{}")
            summary = ", ".join(
                f"{k}: {v}" for k, v in list(data.items())[:2] if v
            )
            events.append({
                "ts": d["updated_at"], "stage": d["stage_name"],
                "action": summary[:120] or d["stage_name"] + " completed",
                "clinician": d["updated_by"], "category": "pathway",
            })

        # Assignments
        for r in conn.execute(
            text("SELECT * FROM assignments WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["assigned_at"], "stage": "Assignment",
                "action": f"Assigned to {d['doctor_name']} ({d['specialty']})",
                "clinician": d["doctor_name"], "category": "assignment",
            })

        # Referrals
        for r in conn.execute(
            text("SELECT * FROM referrals WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["created_at"], "stage": "Referral",
                "action": f"{d['referral_type'].title()}: {d['referral_name']} ({d['urgency']})",
                "clinician": "Referring Clinician", "category": "referral",
            })

        # Ward logs
        for r in conn.execute(
            text("SELECT * FROM ward_logs WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["created_at"], "stage": "Ward Round",
                "action": f"{d['shift']} -- {d['clinician']} ({d['role']}): {d['assessment'][:80]}",
                "clinician": d["clinician"], "category": "ward_log",
            })

        # Observations
        for r in conn.execute(
            text("SELECT * FROM nurse_observations WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            alert = " [RED ALERT]" if (d["news2_score"] or 0) >= 7 else ""
            events.append({
                "ts": d["created_at"], "stage": "Observations",
                "action": (
                    f"{d['shift']} -- {d['nurse_name']}: "
                    f"NEWS2={d['news2_score']}{alert}, "
                    f"T={d['temperature']}C, HR={d['heart_rate']}, "
                    f"RR={d['respiratory_rate']}, SpO2={d['o2_sats']}%"
                ),
                "clinician": d["nurse_name"], "category": "observation",
            })

        # Medications
        for r in conn.execute(
            text("SELECT * FROM medications WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["created_at"], "stage": "Medication",
                "action": f"{d['drug_name']} {d['dose']} {d['route']} {d['frequency']} -- {d['status']}",
                "clinician": d["administered_by"] or d["prescribed_by"],
                "category": "medication",
            })

        # Safeguarding
        for r in conn.execute(
            text("SELECT * FROM safeguarding_flags WHERE nhs_number=:nhs"),
            {"nhs": nhs_number},
        ).fetchall():
            d = _row(r)
            events.append({
                "ts": d["created_at"], "stage": "Safeguarding",
                "action": f"FLAG: {d['flag_type']} -- {d['details'][:80]}",
                "clinician": d["flagged_by"], "category": "safeguarding",
            })

    events.sort(key=lambda e: (e["ts"] or ""), reverse=False)
    return events


# ---------------------------------------------------------------------------
# Session-state loader
# ---------------------------------------------------------------------------

def load_pathways_from_db() -> dict:
    """
    Reconstruct the session-state pathways dict from DB.

    Returns a dict keyed by nhs_number in the same shape that
    pathway_tab.py expects inside st.session_state.pathways.
    """
    with _conn() as conn:
        nhs_rows = conn.execute(
            text("SELECT DISTINCT nhs_number FROM pathway_stages ORDER BY nhs_number")
        ).fetchall()

        pathways: dict = {}
        for nhs_row in nhs_rows:
            nhs = nhs_row[0]

            patient = conn.execute(
                text("SELECT * FROM patients WHERE nhs_number = :nhs"),
                {"nhs": nhs},
            ).fetchone()
            patient_data = _row(patient) if patient else {}
            created_at = patient_data.get("created_at", datetime.now().isoformat())
            name    = patient_data.get("name", "")
            age     = patient_data.get("age", "")
            gender  = patient_data.get("gender", "")

            stage_rows = conn.execute(
                text("""
                    SELECT * FROM pathway_stages
                    WHERE nhs_number = :nhs ORDER BY stage_number
                """),
                {"nhs": nhs},
            ).fetchall()

            # Initialise all 10 stages as pending
            stages = {
                i: {"status": "pending", "timestamp": None, "data": {}}
                for i in range(1, 11)
            }
            for row in stage_rows:
                d = _row(row)
                snum = d["stage_number"]
                if 1 <= snum <= 10:
                    stages[snum] = {
                        "status":    d["status"],
                        "timestamp": d["updated_at"],
                        "data":      json.loads(d["stage_data"] or "{}"),
                    }

            # Current stage = first non-complete stage
            current_stage = 10
            for i in range(1, 11):
                if stages[i].get("status") != "complete":
                    current_stage = i
                    break

            pathways[nhs] = {
                "nhs_number":      nhs,
                "created_at":      created_at,
                "name":            name,
                "age":             age,
                "gender":          gender,
                "triage_case_idx": None,
                "current_stage":   current_stage,
                "stages":          stages,
            }

    return pathways


# ---------------------------------------------------------------------------
# Full patient summary
# ---------------------------------------------------------------------------

def get_patient_full_summary(nhs_number: str) -> dict:
    """Return a complete patient summary dict with nhs_number as the top-level key.

    Gathers all tables for the patient into a single serialisable dict
    suitable for JSON export or FHIR bundle generation.
    """
    from config import format_nhs_number, nhs_reference  # noqa: PLC0415
    from datetime import datetime as _dt               # noqa: PLC0415

    patient       = get_patient(nhs_number) or {}
    triage_rows   = [s for s in get_all_triage_sessions()
                     if s.get("nhs_number") == nhs_number]
    consultations = get_consultations(nhs_number)
    test_orders   = get_test_orders(nhs_number)
    referrals     = get_referrals(nhs_number)
    observations  = get_observations(nhs_number)
    medications   = get_medications(nhs_number)
    safeguarding  = get_safeguarding_flags(nhs_number)
    ward_logs_    = get_ward_logs(nhs_number)
    admissions    = get_hospital_admissions(nhs_number)
    discharges    = get_discharge_summaries(nhs_number)
    closure       = get_case_closure(nhs_number)
    pathway_stages_raw = []
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM pathway_stages WHERE nhs_number=:nhs ORDER BY stage_number"),
            {"nhs": nhs_number},
        ).fetchall()
        pathway_stages_raw = [_row(r) for r in rows]

    audit_rows: list[dict] = []
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM audit_log WHERE nhs_number=:nhs ORDER BY created_at"),
            {"nhs": nhs_number},
        ).fetchall()
        audit_rows = [_row(r) for r in rows]

    nhs_app_notifs: list[dict] = []
    try:
        with _conn() as conn:
            rows = conn.execute(
                text("SELECT * FROM nhs_app_notifications WHERE nhs_number=:nhs "
                     "ORDER BY sent_at DESC"),
                {"nhs": nhs_number},
            ).fetchall()
            nhs_app_notifs = [_row(r) for r in rows]
    except Exception:
        pass

    return {
        "nhs_number":        nhs_number,
        "nhs_number_formatted": format_nhs_number(nhs_number),
        "nhs_reference":     nhs_reference(nhs_number),
        "export_timestamp":  _dt.now().isoformat(),
        "standard":          "ISB0149 — NHS Number",
        "patient": {
            "name":        patient.get("name", ""),
            "age":         patient.get("age", ""),
            "gender":      patient.get("gender", ""),
            "description": patient.get("description", ""),
            "created_at":  patient.get("created_at", ""),
        },
        "triage_sessions":     triage_rows,
        "gp_consultations":    consultations,
        "test_orders":         test_orders,
        "referrals":           referrals,
        "hospital_admissions": admissions,
        "ward_logs":           ward_logs_,
        "observations":        observations,
        "medications":         medications,
        "safeguarding_flags":  safeguarding,
        "discharge_summaries": discharges,
        "pathway_stages":      pathway_stages_raw,
        "case_closure":        closure or {},
        "nhs_app_notifications": nhs_app_notifs,
        "audit_trail":         audit_rows,
    }


# ---------------------------------------------------------------------------
# Login audit
# ---------------------------------------------------------------------------

def save_login_audit(user_email: str, user_name: str = "", user_role: str = "",
                     action: str = "login_success", alias_used: str = "",
                     session_duration_minutes: int = 0) -> None:
    """Record a login / logout / failure event."""
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO login_audit
                    (user_email, user_name, user_role, action,
                     alias_used, ip_address, session_duration_minutes)
                VALUES (:email, :name, :role, :action, :alias, :ip, :dur)
            """),
            {
                "email": user_email, "name": user_name, "role": user_role,
                "action": action, "alias": alias_used or "",
                "ip": "Not captured", "dur": session_duration_minutes,
            },
        )


def get_login_audit(limit: int = 50) -> list[dict]:
    """Return recent login audit rows, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM login_audit
                ORDER BY timestamp DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Shift handovers
# ---------------------------------------------------------------------------

def save_shift_handover(nhs_number: str, handed_from: str,
                        handed_to: str, handover_notes: str = "") -> None:
    """Record a shift handover for a patient."""
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO shift_handovers
                    (nhs_number, handed_from, handed_to, handover_notes)
                VALUES (:nhs, :from_, :to_, :notes)
            """),
            {"nhs": nhs_number, "from_": handed_from,
             "to_": handed_to, "notes": handover_notes},
        )


def get_shift_handovers(nhs_number: str) -> list[dict]:
    """Return all shift handovers for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM shift_handovers
                WHERE nhs_number = :nhs
                ORDER BY handover_time DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# GP Consultations
# ---------------------------------------------------------------------------

def save_consultation(nhs_number: str, consultation_date: str, gp_name: str,
                      gp_email: str = "", presenting_complaint: str = "",
                      examination_findings: str = "", assessment: str = "",
                      plan: str = "", plan_detail: str = "",
                      follow_up_date: str = "", follow_up_gp: str = "",
                      follow_up_surgery: str = "",
                      created_by: str = "system") -> int:
    """Insert a GP consultation record. Returns the new row id."""
    params = {
        "nhs": nhs_number, "cdate": consultation_date, "gp": gp_name,
        "email": gp_email, "complaint": presenting_complaint,
        "exam": examination_findings, "assess": assessment,
        "plan": plan, "detail": plan_detail,
        "fudate": follow_up_date, "fugp": follow_up_gp,
        "fusurg": follow_up_surgery, "by": created_by,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO gp_consultations
                        (nhs_number, consultation_date, gp_name, gp_email,
                         presenting_complaint, examination_findings, assessment,
                         plan, plan_detail, follow_up_date, follow_up_gp,
                         follow_up_surgery, created_by)
                    VALUES (:nhs, :cdate, :gp, :email, :complaint, :exam,
                            :assess, :plan, :detail, :fudate, :fugp, :fusurg, :by)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO gp_consultations
                        (nhs_number, consultation_date, gp_name, gp_email,
                         presenting_complaint, examination_findings, assessment,
                         plan, plan_detail, follow_up_date, follow_up_gp,
                         follow_up_surgery, created_by)
                    VALUES (:nhs, :cdate, :gp, :email, :complaint, :exam,
                            :assess, :plan, :detail, :fudate, :fugp, :fusurg, :by)
                """),
                params,
            )
            return result.lastrowid


def get_consultations(nhs_number: str) -> list[dict]:
    """Return all GP consultations for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM gp_consultations
                WHERE nhs_number = :nhs ORDER BY consultation_date DESC, created_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Test orders
# ---------------------------------------------------------------------------

def save_test_order(nhs_number: str, test_name: str, test_type: str,
                    ordered_date: str, ordered_by: str,
                    consultation_id: int = 0,
                    notify_nhs_app: bool = False) -> int:
    """Insert a test order. Returns the new row id."""
    params = {
        "nhs": nhs_number, "cid": consultation_id, "name": test_name,
        "ttype": test_type, "odate": ordered_date, "oby": ordered_by,
        "notify": 1 if notify_nhs_app else 0,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO test_orders
                        (nhs_number, consultation_id, test_name, test_type,
                         ordered_date, ordered_by, notify_nhs_app)
                    VALUES (:nhs, :cid, :name, :ttype, :odate, :oby, :notify)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO test_orders
                        (nhs_number, consultation_id, test_name, test_type,
                         ordered_date, ordered_by, notify_nhs_app)
                    VALUES (:nhs, :cid, :name, :ttype, :odate, :oby, :notify)
                """),
                params,
            )
            return result.lastrowid


def update_test_result(test_id: int, result_date: str, result_summary: str,
                       result_flag: str = "normal", gp_review_notes: str = "",
                       action_after_result: str = "") -> None:
    """Record results for an existing test order and mark as resulted."""
    with _conn() as conn:
        conn.execute(
            text("""
                UPDATE test_orders SET
                    status              = 'resulted',
                    result_date         = :rdate,
                    result_summary      = :rsumm,
                    result_flag         = :rflag,
                    gp_review_notes     = :notes,
                    action_after_result = :action
                WHERE id = :tid
            """),
            {
                "tid": test_id, "rdate": result_date, "rsumm": result_summary,
                "rflag": result_flag, "notes": gp_review_notes,
                "action": action_after_result,
            },
        )


def get_test_orders(nhs_number: str) -> list[dict]:
    """Return all test orders for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM test_orders
                WHERE nhs_number = :nhs ORDER BY ordered_date DESC, created_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Hospital admissions
# ---------------------------------------------------------------------------

def save_hospital_admission(nhs_number: str, admission_date: str,
                             hospital_name: str = "", ward: str = "",
                             consultant: str = "", diagnosis: str = "",
                             treatment: str = "", complications: str = "",
                             expected_discharge: str = "") -> int:
    """Insert a hospital admission record. Returns the new row id."""
    params = {
        "nhs": nhs_number, "adate": admission_date, "hosp": hospital_name,
        "ward": ward, "cons": consultant, "diag": diagnosis,
        "treat": treatment, "comp": complications, "exp": expected_discharge,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO hospital_admissions
                        (nhs_number, admission_date, hospital_name, ward,
                         consultant, diagnosis, treatment, complications, expected_discharge)
                    VALUES (:nhs, :adate, :hosp, :ward, :cons, :diag, :treat, :comp, :exp)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO hospital_admissions
                        (nhs_number, admission_date, hospital_name, ward,
                         consultant, diagnosis, treatment, complications, expected_discharge)
                    VALUES (:nhs, :adate, :hosp, :ward, :cons, :diag, :treat, :comp, :exp)
                """),
                params,
            )
            return result.lastrowid


def get_hospital_admissions(nhs_number: str) -> list[dict]:
    """Return all hospital admissions for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM hospital_admissions
                WHERE nhs_number = :nhs ORDER BY admission_date DESC, created_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Discharge summaries
# ---------------------------------------------------------------------------

def save_discharge_summary(nhs_number: str, discharge_date: str = "",
                            discharge_destination: str = "",
                            admission_id: int = 0,
                            diagnosis: str = "", treatment_given: str = "",
                            discharge_medications: str = "",
                            follow_up_instructions: str = "",
                            gp_actions: str = "") -> int:
    """Insert a discharge summary received from hospital. Returns new row id."""
    params = {
        "nhs": nhs_number, "aid": admission_id, "ddate": discharge_date,
        "dest": discharge_destination, "diag": diagnosis,
        "treat": treatment_given, "meds": discharge_medications,
        "fuinstr": follow_up_instructions, "gpact": gp_actions,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO discharge_summaries
                        (nhs_number, admission_id, discharge_date, discharge_destination,
                         summary_received, diagnosis, treatment_given, discharge_medications,
                         follow_up_instructions, gp_actions)
                    VALUES (:nhs, :aid, :ddate, :dest, 1, :diag, :treat, :meds, :fuinstr, :gpact)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO discharge_summaries
                        (nhs_number, admission_id, discharge_date, discharge_destination,
                         summary_received, diagnosis, treatment_given, discharge_medications,
                         follow_up_instructions, gp_actions)
                    VALUES (:nhs, :aid, :ddate, :dest, 1, :diag, :treat, :meds, :fuinstr, :gpact)
                """),
                params,
            )
            return result.lastrowid


def get_discharge_summaries(nhs_number: str) -> list[dict]:
    """Return all discharge summaries for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM discharge_summaries
                WHERE nhs_number = :nhs ORDER BY received_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Enhanced referrals (updated save_referral with extra fields)
# ---------------------------------------------------------------------------

def save_referral_full(nhs_number: str, referral_category: str,
                       referral_type: str, referral_name: str,
                       urgency: str = "", hospital_name: str = "",
                       department: str = "", specialty: str = "",
                       location: str = "", ereferral_reference: str = "",
                       ereferral_status: str = "draft",
                       email_sent: bool = False) -> None:
    """Insert a referral with full NHS GP workflow fields."""
    params = {
        "nhs": nhs_number, "cat": referral_category, "rtype": referral_type,
        "rname": referral_name, "urg": urgency, "hosp": hospital_name,
        "dept": department, "spec": specialty, "loc": location,
        "eref": ereferral_reference, "estat": ereferral_status,
        "esent": 1 if email_sent else 0,
        "esentat": datetime.now().isoformat() if email_sent else "",
    }
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO referrals
                    (nhs_number, referral_category, referral_type, referral_name,
                     urgency, hospital_name, department, specialty, location,
                     ereferral_reference, ereferral_status, email_sent, email_sent_at)
                VALUES (:nhs, :cat, :rtype, :rname, :urg, :hosp, :dept, :spec,
                        :loc, :eref, :estat, :esent, :esentat)
            """),
            params,
        )


def get_referrals(nhs_number: str) -> list[dict]:
    """Return all referrals for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("SELECT * FROM referrals WHERE nhs_number=:nhs ORDER BY created_at DESC"),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Case closures + retention
# ---------------------------------------------------------------------------

def calculate_retention_date(dob_str: str | None, closure_date_str: str) -> str:
    """Calculate NHS record retention date.

    Adults:   10 years from closure date.
    Children: Until 25th birthday, or 10 years from closure, whichever is longer.
    If dob_str is None/empty, defaults to adult retention (10 years).
    """
    from config import (          # noqa: PLC0415
        RETENTION_ADULT_YEARS, RETENTION_CHILD_MIN_AGE,
    )
    import datetime as _dt
    try:
        closure = _dt.date.fromisoformat(closure_date_str[:10])
    except (ValueError, TypeError):
        closure = _dt.date.today()

    ten_years = closure.replace(year=closure.year + RETENTION_ADULT_YEARS)

    if dob_str:
        try:
            dob = _dt.date.fromisoformat(str(dob_str)[:10])
            # Age at closure
            age_at_closure = (closure - dob).days / 365.25
            if age_at_closure < 18:
                # Child: 25th birthday
                birthday_25 = dob.replace(year=dob.year + RETENTION_CHILD_MIN_AGE)
                return max(birthday_25, ten_years).isoformat()
        except (ValueError, TypeError):
            pass

    return ten_years.isoformat()


def save_case_closure(nhs_number: str, closed_by: str,
                      closure_reason: str = "",
                      retention_date: str = "", case_summary: str = "",
                      dob_str: str | None = None) -> None:
    """Record case closure and compute retention date if not provided."""
    closed_date = datetime.now().date().isoformat()
    if not retention_date:
        retention_date = calculate_retention_date(dob_str, closed_date)

    from config import RETENTION_WARNING_MONTHS  # noqa: PLC0415
    import datetime as _dt
    try:
        ret_d = _dt.date.fromisoformat(retention_date)
        today = _dt.date.today()
        months_to_ret = (ret_d - today).days / 30.44
        warning_flag = 1 if months_to_ret <= RETENTION_WARNING_MONTHS else 0
    except (ValueError, TypeError):
        warning_flag = 0

    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO case_closures
                    (nhs_number, closed_date, closed_by, closure_reason,
                     retention_date, warning_flag, case_summary)
                VALUES (:nhs, :cdate, :cby, :reason, :retd, :wflag, :summ)
                ON CONFLICT(nhs_number) DO UPDATE SET
                    closed_date    = EXCLUDED.closed_date,
                    closed_by      = EXCLUDED.closed_by,
                    closure_reason = EXCLUDED.closure_reason,
                    retention_date = EXCLUDED.retention_date,
                    warning_flag   = EXCLUDED.warning_flag,
                    case_summary   = EXCLUDED.case_summary
            """),
            {
                "nhs": nhs_number, "cdate": closed_date, "cby": closed_by,
                "reason": closure_reason, "retd": retention_date,
                "wflag": warning_flag, "summ": case_summary,
            },
        )


def get_case_closure(nhs_number: str) -> dict | None:
    """Return the case closure record for a patient, or None."""
    with _conn() as conn:
        row = conn.execute(
            text("SELECT * FROM case_closures WHERE nhs_number = :nhs"),
            {"nhs": nhs_number},
        ).fetchone()
        return _row(row) if row else None


def get_retention_alerts() -> list[dict]:
    """Return all cases where retention warning_flag = 1."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM case_closures
                WHERE warning_flag = 1 ORDER BY retention_date ASC
            """)
        ).fetchall()
        return [_row(r) for r in rows]


# ---------------------------------------------------------------------------
# NHS App notifications
# ---------------------------------------------------------------------------

def save_nhs_app_notification(nhs_number: str, notification_type: str,
                               notification_content: str,
                               sent_by: str = "system") -> int:
    """Log a simulated NHS App notification. Returns new row id."""
    params = {
        "nhs": nhs_number, "ntype": notification_type,
        "content": notification_content, "by": sent_by,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO nhs_app_notifications
                        (nhs_number, notification_type, notification_content, sent_by)
                    VALUES (:nhs, :ntype, :content, :by)
                    RETURNING id
                """),
                params,
            ).fetchone()
            return row[0]
        else:
            result = conn.execute(
                text("""
                    INSERT INTO nhs_app_notifications
                        (nhs_number, notification_type, notification_content, sent_by)
                    VALUES (:nhs, :ntype, :content, :by)
                """),
                params,
            )
            return result.lastrowid


def get_nhs_app_notifications(nhs_number: str) -> list[dict]:
    """Return all NHS App notifications for a patient, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            text("""
                SELECT * FROM nhs_app_notifications
                WHERE nhs_number = :nhs ORDER BY sent_at DESC
            """),
            {"nhs": nhs_number},
        ).fetchall()
        return [_row(r) for r in rows]
