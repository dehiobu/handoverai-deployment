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
    CREATE TABLE IF NOT EXISTS patients (
        id          SERIAL PRIMARY KEY,
        nhs_number  TEXT   UNIQUE NOT NULL,
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
]

# ---------------------------------------------------------------------------
# DDL — SQLite (fallback)
# ---------------------------------------------------------------------------

_SQLITE_DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS patients (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nhs_number  TEXT    UNIQUE NOT NULL,
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
]


# ---------------------------------------------------------------------------
# Row helper
# ---------------------------------------------------------------------------

def _row(row) -> dict:
    """Convert a SQLAlchemy Row to a plain dict."""
    return dict(row._mapping)


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


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def save_patient(nhs_number: str, age: str = "", gender: str = "",
                 description: str = "") -> None:
    """Insert or update a patient record."""
    with _conn() as conn:
        conn.execute(
            text("""
                INSERT INTO patients (nhs_number, age, gender, description)
                VALUES (:nhs, :age, :gender, :desc)
                ON CONFLICT(nhs_number) DO UPDATE SET
                    age         = EXCLUDED.age,
                    gender      = EXCLUDED.gender,
                    description = EXCLUDED.description
            """),
            {"nhs": nhs_number, "age": age, "gender": gender, "desc": description},
        )


def save_triage(nhs_number: str, result_dict: dict,
                response_time: float = 0.0) -> int:
    """Persist a triage session. Returns the new row id."""
    params = {
        "nhs":    nhs_number,
        "dec":    result_dict.get("triage_decision", ""),
        "urg":    result_dict.get("urgency_timeframe", ""),
        "reas":   result_dict.get("clinical_reasoning", ""),
        "flags":  result_dict.get("red_flags", ""),
        "conf":   result_dict.get("confidence", ""),
        "nice":   result_dict.get("nice_guideline", ""),
        "action": result_dict.get("recommended_action", ""),
        "diff":   result_dict.get("differentials", ""),
        "rt":     response_time,
    }
    with _conn() as conn:
        if _IS_POSTGRES:
            row = conn.execute(
                text("""
                    INSERT INTO triage_sessions
                        (nhs_number, triage_decision, urgency, clinical_reasoning,
                         red_flags, confidence, nice_guideline, recommended_action,
                         differentials, response_time_seconds)
                    VALUES (:nhs, :dec, :urg, :reas, :flags, :conf, :nice, :action, :diff, :rt)
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
                         differentials, response_time_seconds)
                    VALUES (:nhs, :dec, :urg, :reas, :flags, :conf, :nice, :action, :diff, :rt)
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
        # Patients admitted but not discharged
        admitted = conn.execute(
            text("""
                SELECT COUNT(DISTINCT p5.nhs_number)
                FROM pathway_stages p5
                LEFT JOIN pathway_stages p10
                    ON p5.nhs_number = p10.nhs_number AND p10.stage_number = 10
                WHERE p5.stage_number = 5 AND p5.status = 'complete'
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

        # Awaiting discharge: stage 9 complete, stage 10 not complete
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

        # Average length of stay
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
            created_at = (
                _row(patient)["created_at"]
                if patient else datetime.now().isoformat()
            )

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
                "nhs_number":     nhs,
                "created_at":     created_at,
                "triage_case_idx": None,
                "current_stage":  current_stage,
                "stages":         stages,
            }

    return pathways
