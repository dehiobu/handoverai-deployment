"""
scripts/create_demo_users.py — Create demo users in Supabase Auth.

Run once after configuring SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_KEY).

Usage:
    python scripts/create_demo_users.py

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY (service_role key, not anon key)
in .env or environment — the service key bypasses email confirmation.
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SUPABASE_URL = os.getenv("SUPABASE_URL")
# Use the service_role key so we can create users without email confirmation
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
)

DEMO_PASSWORD = "HandoverAI2026!"

DEMO_USERS = [
    {
        "email":    "dennis.ehiobu@sutatscode.com",
        "password": DEMO_PASSWORD,
        "metadata": {"name": "Dennis Ehiobu", "role": "admin"},
    },
    {
        "email":    "dr.ehiobu@holmhurst.nhs.uk",
        "password": DEMO_PASSWORD,
        "metadata": {"name": "Dr D. Ehiobu", "role": "gp"},
    },
    {
        "email":    "dr.waketrent@eastsurrey.nhs.uk",
        "password": DEMO_PASSWORD,
        "metadata": {"name": "Dr Wake-Trent", "role": "consultant"},
    },
    {
        "email":    "nurse.jones@holmhurst.nhs.uk",
        "password": DEMO_PASSWORD,
        "metadata": {"name": "Nurse Jones", "role": "nurse"},
    },
    {
        "email":    "manager@holmhurst.nhs.uk",
        "password": DEMO_PASSWORD,
        "metadata": {"name": "Practice Manager", "role": "manager"},
    },
]


def main() -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[ERROR] SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    try:
        from supabase import create_client
    except ImportError:
        print("[ERROR] supabase package not installed. Run: pip install supabase")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    print(f"[INFO] Connecting to Supabase: {SUPABASE_URL}")
    print(f"[INFO] Creating {len(DEMO_USERS)} demo users...")
    print()

    for user in DEMO_USERS:
        email = user["email"]
        try:
            # admin.create_user is available with service_role key
            response = client.auth.admin.create_user({
                "email":            email,
                "password":         user["password"],
                "user_metadata":    user["metadata"],
                "email_confirm":    True,   # skip email confirmation
            })
            print(f"[SUCCESS] Created: {email} | role: {user['metadata']['role']}")
        except Exception as exc:
            err = str(exc)
            if "already been registered" in err or "already exists" in err.lower():
                print(f"[SKIP]    Already exists: {email}")
                # Update metadata in case role changed
                try:
                    # List users and find by email to update
                    users_resp = client.auth.admin.list_users()
                    for u in users_resp:
                        if u.email == email:
                            client.auth.admin.update_user_by_id(
                                u.id,
                                {"user_metadata": user["metadata"]},
                            )
                            print(f"         Metadata updated for {email}")
                            break
                except Exception:
                    pass
            else:
                print(f"[ERROR]   Failed to create {email}: {exc}")

    print()
    print("[INFO] Done.")
    print()
    print("Demo credentials:")
    print(f"  Password for all accounts: {DEMO_PASSWORD}")
    print()
    for u in DEMO_USERS:
        print(f"  {u['email']:<45} role: {u['metadata']['role']}")
    print()
    print("[INFO] Users can change their password after first login.")
    print("[INFO] Add SUPABASE_URL and SUPABASE_KEY to Streamlit Cloud secrets.")


if __name__ == "__main__":
    main()
