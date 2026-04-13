"""
src/database.py -- SQLite persistence layer for GP Triage POC.

Uses Python's built-in sqlite3 module only (no extra packages).
Database file: gp_triage.db in project root.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "gp_triage.db"


def _conn() -> sqlite3.Connection:
    """Open a WAL-mode connection with Row row_factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create all tables if they do not already exist (idempotent)."""
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number  TEXT    UNIQUE NOT NULL,
                age         TEXT    DEFAULT '',
                gender      TEXT    DEFAULT '',
                description TEXT    DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

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
                response_time_seconds REAL DEFAULT 0,
                clinician_override    TEXT,
                override_reason       TEXT,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number  TEXT,
                doctor_name TEXT,
                specialty   TEXT,
                location    TEXT DEFAULT '',
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number    TEXT,
                referral_type TEXT,
                referral_name TEXT,
                urgency       TEXT DEFAULT '',
                location      TEXT DEFAULT '',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status        TEXT DEFAULT 'requested'
            );

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
            );

            CREATE TABLE IF NOT EXISTS letters (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number   TEXT,
                letter_type  TEXT,
                content      TEXT DEFAULT '',
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                emailed_to   TEXT DEFAULT '',
                emailed_at   TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number   TEXT,
                action       TEXT,
                details      TEXT DEFAULT '',
                performed_by TEXT DEFAULT 'system',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def save_patient(nhs_number: str, age: str = "", gender: str = "",
                 description: str = "") -> None:
    """Insert or update a patient record."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO patients (nhs_number, age, gender, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(nhs_number) DO UPDATE SET
                age         = excluded.age,
                gender      = excluded.gender,
                description = excluded.description
            """,
            (nhs_number, age, gender, description),
        )


def save_triage(nhs_number: str, result_dict: dict,
                response_time: float = 0.0) -> int:
    """Persist a triage session. Returns the new row id."""
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO triage_sessions
                (nhs_number, triage_decision, urgency, clinical_reasoning,
                 red_flags, confidence, nice_guideline, recommended_action,
                 differentials, response_time_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nhs_number,
                result_dict.get("triage_decision", ""),
                result_dict.get("urgency_timeframe", ""),
                result_dict.get("clinical_reasoning", ""),
                result_dict.get("red_flags", ""),
                result_dict.get("confidence", ""),
                result_dict.get("nice_guideline", ""),
                result_dict.get("recommended_action", ""),
                result_dict.get("differentials", ""),
                response_time,
            ),
        )
        return cur.lastrowid


def save_assignment(nhs_number: str, doctor_name: str, specialty: str,
                    location: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO assignments (nhs_number, doctor_name, specialty, location)
            VALUES (?, ?, ?, ?)
            """,
            (nhs_number, doctor_name, specialty, location),
        )


def save_referral(nhs_number: str, referral_type: str, referral_name: str,
                  urgency: str = "", location: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO referrals
                (nhs_number, referral_type, referral_name, urgency, location)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nhs_number, referral_type, referral_name, urgency, location),
        )


def save_pathway_stage(nhs_number: str, stage_number: int, stage_name: str,
                       status: str, data_dict: dict,
                       updated_by: str = "system") -> None:
    """Upsert a single pathway stage row."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO pathway_stages
                (nhs_number, stage_number, stage_name, status,
                 stage_data, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nhs_number, stage_number) DO UPDATE SET
                stage_name = excluded.stage_name,
                status     = excluded.status,
                stage_data = excluded.stage_data,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                nhs_number,
                stage_number,
                stage_name,
                status,
                json.dumps(data_dict),
                datetime.now().isoformat(),
                updated_by,
            ),
        )


def save_letter(nhs_number: str, letter_type: str, content: str,
                emailed_to: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO letters (nhs_number, letter_type, content, emailed_to)
            VALUES (?, ?, ?, ?)
            """,
            (nhs_number, letter_type, content, emailed_to),
        )


def save_audit(nhs_number: str, action: str, details: str,
               performed_by: str = "system") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (nhs_number, action, details, performed_by)
            VALUES (?, ?, ?, ?)
            """,
            (nhs_number, action, details, performed_by),
        )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_patient(nhs_number: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE nhs_number = ?", (nhs_number,)
        ).fetchone()
        return dict(row) if row else None


def get_full_pathway(nhs_number: str) -> list[dict]:
    """Return all stage rows for a patient ordered by stage_number."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pathway_stages WHERE nhs_number = ? ORDER BY stage_number",
            (nhs_number,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["stage_data"] = json.loads(d["stage_data"] or "{}")
            result.append(d)
        return result


def get_all_patients() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM patients ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_triage_sessions() -> list[dict]:
    """Return all triage sessions, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM triage_sessions ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_dashboard_stats() -> dict:
    """Aggregate stats across all historical triage sessions in the DB."""
    with _conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM triage_sessions"
        ).fetchone()[0]
        if not total:
            return {}
        red   = conn.execute(
            "SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='RED'"
        ).fetchone()[0]
        amber = conn.execute(
            "SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='AMBER'"
        ).fetchone()[0]
        green = conn.execute(
            "SELECT COUNT(*) FROM triage_sessions WHERE triage_decision='GREEN'"
        ).fetchone()[0]
        overrides = conn.execute(
            "SELECT COUNT(*) FROM triage_sessions WHERE clinician_override IS NOT NULL"
        ).fetchone()[0]
        avg_row = conn.execute(
            "SELECT AVG(response_time_seconds) FROM triage_sessions"
        ).fetchone()
        avg_time = avg_row[0] or 0.0
        total_patients = conn.execute(
            "SELECT COUNT(*) FROM patients"
        ).fetchone()[0]
        discharged = conn.execute(
            """
            SELECT COUNT(DISTINCT nhs_number) FROM pathway_stages
            WHERE stage_number = 10 AND status = 'complete'
            """
        ).fetchone()[0]
        return {
            "total": total,
            "red": red,
            "amber": amber,
            "green": green,
            "overrides": overrides,
            "override_rate_pct": overrides / total * 100 if total else 0,
            "avg_response_s": avg_time,
            "total_patients": total_patients,
            "discharged": discharged,
        }


def search_patients(query: str) -> list[dict]:
    """Case-insensitive search by NHS number or description."""
    like = f"%{query}%"
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM patients
            WHERE nhs_number LIKE ? OR description LIKE ?
            ORDER BY created_at DESC
            """,
            (like, like),
        ).fetchall()
        return [dict(r) for r in rows]


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
            "SELECT DISTINCT nhs_number FROM pathway_stages ORDER BY nhs_number"
        ).fetchall()

        pathways: dict = {}
        for nhs_row in nhs_rows:
            nhs = nhs_row["nhs_number"]

            patient = conn.execute(
                "SELECT * FROM patients WHERE nhs_number = ?", (nhs,)
            ).fetchone()
            created_at = (
                patient["created_at"] if patient else datetime.now().isoformat()
            )

            stage_rows = conn.execute(
                """
                SELECT * FROM pathway_stages
                WHERE nhs_number = ? ORDER BY stage_number
                """,
                (nhs,),
            ).fetchall()

            # Initialise all 10 stages as pending
            stages = {
                i: {"status": "pending", "timestamp": None, "data": {}}
                for i in range(1, 11)
            }
            for row in stage_rows:
                snum = row["stage_number"]
                if 1 <= snum <= 10:
                    stages[snum] = {
                        "status": row["status"],
                        "timestamp": row["updated_at"],
                        "data": json.loads(row["stage_data"] or "{}"),
                    }

            # Current stage = first non-complete stage, terminus = 10
            current_stage = 10
            for i in range(1, 11):
                if stages[i].get("status") != "complete":
                    current_stage = i
                    break

            pathways[nhs] = {
                "nhs_number": nhs,
                "created_at": created_at,
                "triage_case_idx": None,
                "current_stage": current_stage,
                "stages": stages,
            }

    return pathways
