"""
scripts/create_demo_users.py — Create demo users in Supabase Auth.

Run ONCE manually after setting up Supabase. Never imported by the app.

Requirements in .env:
    SUPABASE_URL         = https://<project>.supabase.co
    SUPABASE_SERVICE_KEY = <service_role key from Project Settings -> API>

The service_role key is required — the anon key cannot create users.

Usage:
    python scripts/create_demo_users.py
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL         = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

DEMO_PASSWORD = "HandoverAI2026!"

ALIAS_MAP = {
    "dennis.ehiobu@sutatscode.com":   "admin1",
    "dr.ehiobu@holmhurst.nhs.uk":     "gp1",
    "dr.waketrent@eastsurrey.nhs.uk": "cons1",
    "nurse.jones@holmhurst.nhs.uk":   "nurse1",
    "manager@holmhurst.nhs.uk":       "mgr1",
}

DEMO_USERS = [
    {"email": "dennis.ehiobu@sutatscode.com",   "metadata": {"name": "Dennis Ehiobu",    "role": "admin"}},
    {"email": "dr.ehiobu@holmhurst.nhs.uk",      "metadata": {"name": "Dr D. Ehiobu",     "role": "gp"}},
    {"email": "dr.waketrent@eastsurrey.nhs.uk",  "metadata": {"name": "Dr Wake-Trent",    "role": "consultant"}},
    {"email": "nurse.jones@holmhurst.nhs.uk",    "metadata": {"name": "Nurse Jones",      "role": "nurse"}},
    {"email": "manager@holmhurst.nhs.uk",        "metadata": {"name": "Practice Manager", "role": "manager"}},
]


def main() -> None:
    # ── Pre-flight checks ────────────────────────────────────────────────────
    errors = []
    if not SUPABASE_URL:
        errors.append("SUPABASE_URL is not set in .env")
    if not SUPABASE_SERVICE_KEY:
        errors.append(
            "SUPABASE_SERVICE_KEY is not set in .env\n"
            "  Get it from: Supabase dashboard -> Project Settings -> API -> service_role key\n"
            "  It is different from the anon/public key."
        )
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)

    try:
        from supabase import create_client
    except ImportError:
        print("[ERROR] supabase package not installed. Run: pip install supabase")
        sys.exit(1)

    print(f"[INFO] Supabase URL : {SUPABASE_URL}")
    print(f"[INFO] Service key  : {SUPABASE_SERVICE_KEY[:12]}... (length {len(SUPABASE_SERVICE_KEY)})")
    print()

    try:
        client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as exc:
        print(f"[ERROR] Could not create Supabase client: {exc}")
        sys.exit(1)

    print(f"[INFO] Creating {len(DEMO_USERS)} demo users...")
    print()

    created = skipped = failed = 0

    for user in DEMO_USERS:
        email = user["email"]
        try:
            client.auth.admin.create_user({
                "email":         email,
                "password":      DEMO_PASSWORD,
                "user_metadata": user["metadata"],
                "email_confirm": True,
            })
            print(f"[SUCCESS] Created  : {email}  (role: {user['metadata']['role']})")
            created += 1
        except Exception as exc:
            err = str(exc)
            if "already" in err.lower():
                print(f"[SKIP]    Exists    : {email}")
                # Refresh metadata so role is always current
                try:
                    for u in client.auth.admin.list_users():
                        if u.email == email:
                            client.auth.admin.update_user_by_id(
                                u.id, {"user_metadata": user["metadata"]}
                            )
                            print(f"           Metadata refreshed for {email}")
                            break
                except Exception:
                    pass
                skipped += 1
            else:
                print(f"[ERROR]   Failed    : {email}  -> {exc}")
                failed += 1

    print()
    print(f"[INFO] Done — created: {created}, skipped: {skipped}, failed: {failed}")
    print()
    print("  Alias       Email                                          Role")
    print("  ----------  ---------------------------------------------  -----------")
    for u in DEMO_USERS:
        alias = ALIAS_MAP.get(u["email"], "—")
        print(f"  {alias:<10}  {u['email']:<45}  {u['metadata']['role']}")
    print()
    print(f"  Password for all accounts: {DEMO_PASSWORD}")
    print()
    print("[INFO] Login with alias (e.g. admin1) OR full email + password above.")
    print("[INFO] Add SUPABASE_URL + SUPABASE_KEY (anon) to Streamlit Cloud secrets.")


if __name__ == "__main__":
    main()
