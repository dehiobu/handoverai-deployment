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
            );

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
            );

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
            );

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
            );

            CREATE TABLE IF NOT EXISTS discharge_checklist (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                nhs_number     TEXT UNIQUE,
                checklist_data TEXT DEFAULT '{}',
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_by     TEXT DEFAULT 'system'
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

# ---------------------------------------------------------------------------
# Ward log
# ---------------------------------------------------------------------------

def save_ward_log(nhs_number: str, log_date: str, shift: str, clinician: str,
                  role: str, subjective: str, objective: str,
                  assessment: str, plan: str) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO ward_logs
                (nhs_number, log_date, shift, clinician, role,
                 subjective, objective, assessment, plan)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nhs_number, log_date, shift, clinician, role,
             subjective, objective, assessment, plan),
        )


def get_ward_logs(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ward_logs WHERE nhs_number=? ORDER BY created_at DESC",
            (nhs_number,),
        ).fetchall()
        return [dict(r) for r in rows]


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
            """
            INSERT INTO nurse_observations
                (nhs_number, obs_date, shift, nurse_name, temperature,
                 bp_systolic, bp_diastolic, heart_rate, respiratory_rate,
                 o2_sats, avpu, pain_score, fluid_input, fluid_output,
                 wound_check, pressure_areas, news2_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nhs_number, obs_date, shift, nurse_name, temperature,
             bp_systolic, bp_diastolic, heart_rate, respiratory_rate,
             o2_sats, avpu, pain_score, fluid_input, fluid_output,
             wound_check, pressure_areas, news2_score),
        )


def get_observations(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM nurse_observations
            WHERE nhs_number=? ORDER BY created_at DESC
            """,
            (nhs_number,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

def save_medication(nhs_number: str, med_date: str, drug_name: str,
                    dose: str, route: str, frequency: str,
                    prescribed_by: str, administered_by: str,
                    status: str, notes: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO medications
                (nhs_number, med_date, drug_name, dose, route, frequency,
                 prescribed_by, administered_by, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nhs_number, med_date, drug_name, dose, route, frequency,
             prescribed_by, administered_by, status, notes),
        )


def get_medications(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM medications WHERE nhs_number=? ORDER BY created_at DESC",
            (nhs_number,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Safeguarding flags
# ---------------------------------------------------------------------------

def save_safeguarding_flag(nhs_number: str, flag_type: str, flagged_at: str,
                           flagged_by: str, details: str = "",
                           action_taken: str = "", referred_to: str = "",
                           reference_number: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO safeguarding_flags
                (nhs_number, flag_type, flagged_at, flagged_by, details,
                 action_taken, referred_to, reference_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nhs_number, flag_type, flagged_at, flagged_by, details,
             action_taken, referred_to, reference_number),
        )


def get_safeguarding_flags(nhs_number: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM safeguarding_flags
            WHERE nhs_number=? ORDER BY created_at DESC
            """,
            (nhs_number,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Discharge checklist
# ---------------------------------------------------------------------------

def update_discharge_checklist(nhs_number: str, checklist_dict: dict,
                                updated_by: str = "system") -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO discharge_checklist (nhs_number, checklist_data, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(nhs_number) DO UPDATE SET
                checklist_data = excluded.checklist_data,
                updated_at     = excluded.updated_at,
                updated_by     = excluded.updated_by
            """,
            (nhs_number, json.dumps(checklist_dict),
             datetime.now().isoformat(), updated_by),
        )


def get_discharge_checklist(nhs_number: str) -> dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT checklist_data FROM discharge_checklist WHERE nhs_number=?",
            (nhs_number,),
        ).fetchone()
        if row:
            return json.loads(row["checklist_data"] or "{}")
        return {}


# ---------------------------------------------------------------------------
# Ward overview (for dashboard)
# ---------------------------------------------------------------------------

def get_ward_overview_stats() -> dict:
    """Aggregate ward stats for the dashboard ward overview section."""
    with _conn() as conn:
        # Patients admitted but not discharged = have stage 5 complete, stage 10 not complete
        admitted = conn.execute(
            """
            SELECT COUNT(DISTINCT p5.nhs_number)
            FROM pathway_stages p5
            LEFT JOIN pathway_stages p10
                ON p5.nhs_number = p10.nhs_number AND p10.stage_number = 10
            WHERE p5.stage_number = 5 AND p5.status = 'complete'
              AND (p10.status IS NULL OR p10.status != 'complete')
            """
        ).fetchone()[0]

        # Latest NEWS2 per patient — count RED alerts (score >= 7)
        obs_rows = conn.execute(
            """
            SELECT nhs_number, news2_score
            FROM nurse_observations
            WHERE id IN (
                SELECT MAX(id) FROM nurse_observations GROUP BY nhs_number
            )
            """
        ).fetchall()
        news2_scores = [r["news2_score"] for r in obs_rows if r["news2_score"] is not None]
        avg_news2    = sum(news2_scores) / len(news2_scores) if news2_scores else 0
        red_alerts   = sum(1 for s in news2_scores if s >= 7)

        # Safeguarding flags count (unresolved)
        safeguarding = conn.execute(
            "SELECT COUNT(*) FROM safeguarding_flags WHERE resolved=0"
        ).fetchone()[0]

        # Awaiting discharge: stage 9 complete, stage 10 pending
        awaiting_dc = conn.execute(
            """
            SELECT COUNT(DISTINCT p9.nhs_number)
            FROM pathway_stages p9
            LEFT JOIN pathway_stages p10
                ON p9.nhs_number = p10.nhs_number AND p10.stage_number = 10
            WHERE p9.stage_number = 9 AND p9.status = 'complete'
              AND (p10.status IS NULL OR p10.status != 'complete')
            """
        ).fetchone()[0]

        # Average length of stay for discharged patients
        los_rows = conn.execute(
            """
            SELECT stage_data FROM pathway_stages
            WHERE stage_number = 8 AND status = 'complete'
            """
        ).fetchall()
        los_values = []
        for row in los_rows:
            data = json.loads(row["stage_data"] or "{}")
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
            "SELECT * FROM triage_sessions WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["created_at"], "stage": "Triage",
                "action": f"AI triage: {r['triage_decision']} -- {r['urgency']}",
                "clinician": "AI System", "category": "triage",
            })

        # Pathway stages
        for r in conn.execute(
            "SELECT * FROM pathway_stages WHERE nhs_number=? AND status='complete' ORDER BY stage_number",
            (nhs_number,),
        ).fetchall():
            data = json.loads(r["stage_data"] or "{}")
            summary = ", ".join(
                f"{k}: {v}" for k, v in list(data.items())[:2] if v
            )
            events.append({
                "ts": r["updated_at"], "stage": r["stage_name"],
                "action": summary[:120] or r["stage_name"] + " completed",
                "clinician": r["updated_by"], "category": "pathway",
            })

        # Assignments
        for r in conn.execute(
            "SELECT * FROM assignments WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["assigned_at"], "stage": "Assignment",
                "action": f"Assigned to {r['doctor_name']} ({r['specialty']})",
                "clinician": r["doctor_name"], "category": "assignment",
            })

        # Referrals
        for r in conn.execute(
            "SELECT * FROM referrals WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["created_at"], "stage": "Referral",
                "action": f"{r['referral_type'].title()}: {r['referral_name']} ({r['urgency']})",
                "clinician": "Referring Clinician", "category": "referral",
            })

        # Ward logs
        for r in conn.execute(
            "SELECT * FROM ward_logs WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["created_at"], "stage": "Ward Round",
                "action": f"{r['shift']} -- {r['clinician']} ({r['role']}): {r['assessment'][:80]}",
                "clinician": r["clinician"], "category": "ward_log",
            })

        # Observations
        for r in conn.execute(
            "SELECT * FROM nurse_observations WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            alert = " [RED ALERT]" if r["news2_score"] >= 7 else ""
            events.append({
                "ts": r["created_at"], "stage": "Observations",
                "action": (
                    f"{r['shift']} -- {r['nurse_name']}: "
                    f"NEWS2={r['news2_score']}{alert}, "
                    f"T={r['temperature']}C, HR={r['heart_rate']}, "
                    f"RR={r['respiratory_rate']}, SpO2={r['o2_sats']}%"
                ),
                "clinician": r["nurse_name"], "category": "observation",
            })

        # Medications
        for r in conn.execute(
            "SELECT * FROM medications WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["created_at"], "stage": "Medication",
                "action": f"{r['drug_name']} {r['dose']} {r['route']} {r['frequency']} -- {r['status']}",
                "clinician": r["administered_by"] or r["prescribed_by"],
                "category": "medication",
            })

        # Safeguarding
        for r in conn.execute(
            "SELECT * FROM safeguarding_flags WHERE nhs_number=?", (nhs_number,)
        ).fetchall():
            events.append({
                "ts": r["created_at"], "stage": "Safeguarding",
                "action": f"FLAG: {r['flag_type']} -- {r['details'][:80]}",
                "clinician": r["flagged_by"], "category": "safeguarding",
            })

    events.sort(key=lambda e: (e["ts"] or ""), reverse=False)
    return events


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
