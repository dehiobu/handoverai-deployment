"""
GP Triage POC — NHS Showcase Edition v0.3.0  (HandoverAI)

Phases implemented
------------------
  Phase 1-9 — all previous phases (see CLAUDE.md)
  Phase 10  — Supabase Auth: multi-user login, role-based access,
               session timeout, shift handover, login audit
"""
import os
from datetime import datetime

import streamlit as st


# ---------------------------------------------------------------------------
# Secrets helper — must run before any other import that reads os.environ
# ---------------------------------------------------------------------------

def get_secret(section: str, key: str, env_key: str | None = None,
               default: str | None = None) -> str | None:
    """Return a secret from st.secrets (Streamlit Cloud) then os.getenv (.env)."""
    env_k = env_key or key.upper()
    try:
        val = st.secrets[section][key]
        if val:
            os.environ.setdefault(env_k, str(val))
            return str(val)
    except Exception:
        pass
    return os.getenv(env_k, default)


# Sync all known secrets into os.environ before any module-level reads
for (_sec, _key), _env in {
    ("database",  "url"):      "DATABASE_URL",
    ("openai",    "api_key"):  "OPENAI_API_KEY",
    ("smtp",      "email"):    "SMTP_EMAIL",
    ("smtp",      "password"): "SMTP_PASSWORD",
    ("supabase",  "url"):      "SUPABASE_URL",
    ("supabase",  "key"):      "SUPABASE_KEY",
}.items():
    get_secret(_sec, _key, _env)


import config  # noqa: E402
from src.database import init_db, load_pathways_from_db, save_login_audit
from src.vector_store import vector_store
from src.rag_pipeline import RAGPipeline
from src.auth import (
    is_authenticated, login, logout,
    get_current_user, get_user_name, get_user_email, get_user_role,
    check_session_timeout, touch_activity,
)
from ui.sidebar import render_sidebar
from tabs.triage_tab import render_triage
from tabs.dashboard_tab import render_executive_dashboard
from tabs.governance_tab import render_governance_panel
from tabs.pathway_tab import render_pathway

# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="HandoverAI — GP Triage Assistant",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# Global CSS (NHS Design System)
# ──────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* ── Global ── */
    html, body, [class*="css"] { font-family: "Arial", "Helvetica Neue", sans-serif; }
    .stApp { background-color: #F0F4F5; border-top: 5px solid #005EB8; }

    /* ── Safety banner ── */
    .safety-banner {
        background-color: #003087;
        color: #ffffff;
        padding: 0.6rem 1.4rem;
        border-radius: 0.4rem;
        border-left: 5px solid #FFB81C;
        font-size: 0.95rem;
        font-weight: 600;
        margin-bottom: 1rem;
        text-align: center;
        letter-spacing: 0.025em;
    }

    /* ── NHS hero header ── */
    .nhs-hero {
        background-color: #005EB8;
        color: #ffffff;
        border-radius: 0.5rem;
        padding: 1.1rem 1.6rem;
        margin-bottom: 0.5rem;
    }
    .nhs-hero h1 {
        font-size: 1.75rem; font-weight: 700;
        margin: 0 0 0.2rem 0; color: #ffffff;
    }
    .nhs-hero p { font-size: 0.95rem; margin: 0; opacity: 0.88; }

    /* ── Login page ── */
    .login-left {
        background: linear-gradient(160deg, #003087 0%, #005EB8 100%);
        border-radius: 0.75rem;
        padding: 2.5rem 2rem;
        min-height: 520px;
        color: #ffffff;
    }
    .login-left h1 { color: #ffffff; font-size: 2rem; margin: 0.5rem 0 0.2rem 0; }
    .login-left p  { color: rgba(255,255,255,0.85); font-size: 0.95rem; margin: 0 0 1.5rem 0; }
    .login-nhs-badge {
        display: inline-block;
        background: #ffffff;
        color: #003087;
        font-weight: 800;
        font-size: 1.3rem;
        padding: 4px 14px;
        border-radius: 4px;
        margin-bottom: 1rem;
        letter-spacing: 0.05em;
    }
    .login-feature {
        display: flex; align-items: flex-start;
        margin-bottom: 0.9rem;
        font-size: 0.9rem;
        color: rgba(255,255,255,0.9);
    }
    .login-feature-icon {
        font-size: 1.1rem; margin-right: 0.7rem; flex-shrink: 0;
    }
    .login-footer {
        margin-top: 2rem;
        font-size: 0.78rem;
        color: rgba(255,255,255,0.55);
        border-top: 1px solid rgba(255,255,255,0.2);
        padding-top: 0.75rem;
    }
    .login-right {
        background: #ffffff;
        border-radius: 0.75rem;
        padding: 2.5rem 2.5rem;
        min-height: 520px;
        border: 1px solid #dde3ec;
    }
    .login-right h2 { color: #003087; font-size: 1.6rem; margin: 0 0 0.2rem 0; }
    .login-right p  { color: #4a5568; font-size: 0.9rem; margin: 0 0 1.5rem 0; }
    .login-amber-box {
        background: #FFF8E1;
        border-left: 4px solid #FFB81C;
        border-radius: 4px;
        padding: 0.6rem 0.9rem;
        font-size: 0.85rem;
        color: #5a4200;
        margin-top: 1rem;
    }

    /* ── Global selectbox / multiselect ── */
    [data-baseweb="select"] > div:first-child {
        border: 2px solid #005EB8 !important;
        border-radius: 5px !important;
        background-color: #ffffff !important;
    }
    [data-baseweb="select"] > div:first-child:hover { border-color: #003087 !important; }
    [data-baseweb="multiselect"] > div:first-child {
        border: 2px solid #005EB8 !important;
        border-radius: 5px !important;
        background-color: #ffffff !important;
    }
    [data-baseweb="multiselect"] > div:first-child:hover { border-color: #003087 !important; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] { background-color: #005EB8 !important; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    [data-testid="stSidebar"] .stAlert {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
    }
    [data-testid="stSidebar"] .stButton button {
        background-color: #003087 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border: 2px solid #ffffff !important;
        width: 100%;
    }
    [data-testid="stSidebar"] .stButton button:hover { background-color: #002060 !important; }
    [data-testid="stSidebar"] [data-testid="stMetric"] {
        background-color: rgba(255,255,255,0.15);
        border-radius: 0.4rem;
        padding: 0.3rem 0.5rem;
    }
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div:first-child {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.5) !important;
    }
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] span,
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] div {
        color: #ffffff !important;
    }
    [data-baseweb="popover"] [role="option"],
    [data-baseweb="popover"] [data-baseweb="menu"] li {
        color: #1a1a1a !important;
        background-color: #ffffff !important;
    }
    [data-baseweb="popover"] [role="option"]:hover,
    [data-baseweb="popover"] [aria-selected="true"] {
        background-color: #E8EEF8 !important;
        color: #003087 !important;
    }

    /* ── Triage result cards ── */
    .triage-red {
        background-color: #FDECEA; padding: 1.4rem 1.8rem;
        border-radius: 0.5rem; border-left: 8px solid #DA291C; margin-bottom: 1rem;
    }
    .triage-red h2 { color: #DA291C !important; font-size: 1.7rem !important; margin: 0; }
    .triage-red h3 { color: #8B0000 !important; font-size: 1.05rem !important; margin-top: 0.3rem; }
    .triage-amber {
        background-color: #FFF8E1; padding: 1.4rem 1.8rem;
        border-radius: 0.5rem; border-left: 8px solid #FFB81C; margin-bottom: 1rem;
    }
    .triage-amber h2 { color: #7A5A00 !important; font-size: 1.7rem !important; margin: 0; }
    .triage-amber h3 { color: #9A6F00 !important; font-size: 1.05rem !important; margin-top: 0.3rem; }
    .triage-green {
        background-color: #E8F5E9; padding: 1.4rem 1.8rem;
        border-radius: 0.5rem; border-left: 8px solid #009639; margin-bottom: 1rem;
    }
    .triage-green h2 { color: #005C22 !important; font-size: 1.7rem !important; margin: 0; }
    .triage-green h3 { color: #007A30 !important; font-size: 1.05rem !important; margin-top: 0.3rem; }

    /* ── Section headings ── */
    .section-heading {
        color: #003087; font-size: 1.15rem; font-weight: 700;
        border-bottom: 2px solid #005EB8;
        padding-bottom: 0.25rem; margin: 1.1rem 0 0.7rem 0;
    }

    /* ── Governance cards ── */
    .gov-card {
        background-color: #ffffff; border-radius: 0.5rem;
        border: 1px solid #AEB7BD; padding: 1.1rem 1.4rem; margin-bottom: 0.8rem;
    }
    .gov-card h3 { color: #005EB8; margin-top: 0; font-size: 1.05rem; }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px; background-color: #E8EEF8;
        padding: 0.55rem 0.75rem; border-radius: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem !important; font-weight: 600 !important;
        padding: 0.55rem 1.4rem !important; border-radius: 0.4rem !important;
        background-color: #ffffff !important; color: #333 !important; border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #005EB8 !important; color: #ffffff !important;
    }

    /* ── Buttons ── */
    [data-testid="stButton"] button[kind="primary"] {
        background-color: #005EB8 !important; font-size: 1.05rem !important;
        font-weight: 700 !important; padding: 0.7rem 2rem !important;
        border-radius: 0.4rem !important;
    }

    /* ── Form selectboxes ── */
    [data-testid="stForm"] .stSelectbox label p {
        color: #003087 !important; font-weight: 700 !important;
    }
    [data-testid="stForm"] .stSelectbox [data-baseweb="select"] > div:first-child {
        background-color: #F0F4FF !important;
        border: 2px solid #005EB8 !important;
        border-radius: 4px !important;
    }
    [data-testid="stForm"] .stSelectbox [data-baseweb="select"] span,
    [data-testid="stForm"] .stSelectbox [data-baseweb="select"] > div:first-child div {
        color: #003087 !important; font-size: 1.05rem !important; font-weight: 500 !important;
    }
    [data-testid="stFormSubmitButton"] button {
        background-color: #005EB8 !important; color: #ffffff !important;
        font-weight: 700 !important; border: none !important;
        border-radius: 0.4rem !important; padding: 0.5rem 2rem !important;
        font-size: 1rem !important;
    }
    [data-testid="stFormSubmitButton"] button:hover { background-color: #003087 !important; }

    p, li { font-size: 1rem !important; }
    h2 { font-size: 1.35rem !important; }
    h3 { font-size: 1.15rem !important; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Login page
# ──────────────────────────────────────────────────────────────────────────────

def _render_login_page() -> None:
    """Full NHS-branded two-panel login screen."""
    left_col, right_col = st.columns([2, 3], gap="medium")

    with left_col:
        st.markdown("""
<div style="background:linear-gradient(160deg,#003087 0%,#005EB8 100%);
            border-radius:0.75rem;padding:2.5rem 2rem;min-height:520px;color:#fff">

  <div style="display:inline-block;background:#fff;color:#003087;font-weight:800;
              font-size:1.3rem;padding:4px 14px;border-radius:4px;
              margin-bottom:1rem;letter-spacing:0.05em">NHS</div>

  <h1 style="color:#fff;font-size:2rem;margin:0.5rem 0 0.2rem 0">HandoverAI</h1>

  <p style="color:rgba(255,255,255,0.85);font-size:0.95rem;margin:0 0 1.5rem 0">
    Supporting NHS clinical teams with safe, explainable,
    evidence-based triage decisions
  </p>

  <div style="display:flex;align-items:flex-start;margin-bottom:0.9rem;
              font-size:0.9rem;color:rgba(255,255,255,0.9)">
    <span style="font-size:1.1rem;margin-right:0.7rem;flex-shrink:0">&#9889;</span>
    <span>AI-powered triage in under 10 seconds</span>
  </div>
  <div style="display:flex;align-items:flex-start;margin-bottom:0.9rem;
              font-size:0.9rem;color:rgba(255,255,255,0.9)">
    <span style="font-size:1.1rem;margin-right:0.7rem;flex-shrink:0">&#128269;</span>
    <span>Full explainability and audit trail</span>
  </div>
  <div style="display:flex;align-items:flex-start;margin-bottom:0.9rem;
              font-size:0.9rem;color:rgba(255,255,255,0.9)">
    <span style="font-size:1.1rem;margin-right:0.7rem;flex-shrink:0">&#128203;</span>
    <span>10-stage patient pathway tracking</span>
  </div>
  <div style="display:flex;align-items:flex-start;margin-bottom:0.9rem;
              font-size:0.9rem;color:rgba(255,255,255,0.9)">
    <span style="font-size:1.1rem;margin-right:0.7rem;flex-shrink:0">&#128260;</span>
    <span>Multi-user shift handover</span>
  </div>
  <div style="display:flex;align-items:flex-start;margin-bottom:0.9rem;
              font-size:0.9rem;color:rgba(255,255,255,0.9)">
    <span style="font-size:1.1rem;margin-right:0.7rem;flex-shrink:0">&#127973;</span>
    <span>Role-based access for GPs, nurses, managers</span>
  </div>

  <div style="margin-top:2rem;font-size:0.78rem;color:rgba(255,255,255,0.55);
              border-top:1px solid rgba(255,255,255,0.2);padding-top:0.75rem">
    Sutatscode Ltd &nbsp;|&nbsp; Synthetic Data Only &nbsp;|&nbsp; POC v0.3.0
  </div>
</div>
""", unsafe_allow_html=True)

    with right_col:
        st.markdown(
            '<h2 style="color:#003087;font-size:1.8rem;margin:0 0 0.1rem 0">Welcome back</h2>'
            '<p style="color:#4a5568;font-size:0.95rem;margin:0 0 1.2rem 0">'
            'Sign in to HandoverAI</p>',
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            email    = st.text_input("Username or Email",
                                     placeholder="e.g. gp1  or  you@nhs.uk")
            password = st.text_input("Password", type="password",
                                     placeholder="Enter your password")
            submitted = st.form_submit_button("Sign in", type="primary",
                                              use_container_width=True)

        st.caption("Forgot password? Contact dennis.ehiobu@sutatscode.com")

        st.markdown(
            '<div style="background:#FFF8E1;border-left:4px solid #FFB81C;'
            'border-radius:4px;padding:0.6rem 0.9rem;font-size:0.85rem;color:#5a4200;'
            'margin-top:0.75rem">'
            '&#9888;&#65039; <strong>Safety notice:</strong> This system uses '
            '<strong>synthetic data only</strong> — not for use with real patient data.'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            "<br><center><small>Authorised users only — Sutatscode Ltd</small></center>",
            unsafe_allow_html=True,
        )

        # Surface any Supabase configuration errors before the user even tries
        cfg_err = st.session_state.pop("_auth_config_error", None)
        if cfg_err:
            st.error(f"Configuration error: {cfg_err}")

        if submitted:
            if not email or not password:
                st.error("Please enter your username/email and password.")
                return

            with st.spinner("Signing in..."):
                result = login(email.strip(), password)

            # Re-check config error that may have been set during the login attempt
            cfg_err = st.session_state.pop("_auth_config_error", None)
            if cfg_err:
                st.error(f"Configuration error: {cfg_err}")
                return

            if result["success"]:
                user = result["user"]
                st.session_state["auth_user"]       = user
                st.session_state["auth_login_time"] = datetime.now()
                touch_activity()

                # Audit success
                try:
                    save_login_audit(
                        user_email=user["email"],
                        user_name=user["name"],
                        user_role=user["role"],
                        action="login_success",
                        alias_used=result.get("alias_used") or "",
                    )
                except Exception:
                    pass

                st.rerun()
            else:
                st.error(result["error"])
                # Audit failure
                try:
                    save_login_audit(
                        user_email=email.strip(),
                        action="login_failed",
                        alias_used=result.get("alias_used") or "",
                    )
                except Exception:
                    pass


# ──────────────────────────────────────────────────────────────────────────────
# Session state init
# ──────────────────────────────────────────────────────────────────────────────

if "app_initialized" not in st.session_state:
    init_db()
    st.session_state.app_initialized  = True
    st.session_state.initialized      = False
    st.session_state.triage_history   = []
    st.session_state.audit_log        = []
    st.session_state.last_result      = None
    st.session_state.pathways         = load_pathways_from_db()
    st.session_state.show_new_pathway_form = False


# ──────────────────────────────────────────────────────────────────────────────
# System initialisation
# ──────────────────────────────────────────────────────────────────────────────

def initialize_system() -> None:
    with st.spinner("Initialising GP Triage Assistant..."):
        chroma_path = config.CHROMA_DIR / "chroma.sqlite3"
        if not chroma_path.exists():
            st.info("First-time setup — building clinical vector store...")
            if not config.DATASET_FILE.exists():
                st.error(
                    f"Training data not found at {config.DATASET_FILE}. "
                    "Run `python scripts/setup_vectorstore.py` first."
                )
                st.stop()
            try:
                vector_store.initialize_from_json(str(config.DATASET_FILE))
            except Exception as exc:
                st.error(f"Error building vector store: {exc}")
                st.stop()
        else:
            try:
                vector_store.load_existing()
            except Exception as exc:
                st.error(f"Error loading vector store: {exc}")
                st.stop()
        st.session_state.rag_pipeline = RAGPipeline(vector_store)
        st.session_state.initialized  = True


# ──────────────────────────────────────────────────────────────────────────────
# Main layout (authenticated)
# ──────────────────────────────────────────────────────────────────────────────

def _render_role_notice() -> None:
    """Show a subtle role badge in the main area."""
    role  = get_user_role()
    name  = get_user_name()
    badge = {
        "admin":      ("#003087", "Admin"),
        "gp":         ("#005EB8", "GP"),
        "consultant": ("#005EB8", "Consultant"),
        "nurse":      ("#009639", "Nurse"),
        "manager":    ("#7A5A00", "Manager"),
    }.get(role, ("#555", role.title()))
    st.markdown(
        f'<div style="text-align:right;margin-bottom:0.3rem">'
        f'<span style="background:{badge[0]};color:#fff;border-radius:4px;'
        f'padding:3px 10px;font-size:0.8rem;font-weight:700">'
        f'{name} — {badge[1]}</span></div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    # Session timeout check — auto-logout if idle 60 min
    if check_session_timeout():
        login_time = st.session_state.get("auth_login_time")
        dur = 0
        if login_time:
            dur = int((datetime.now() - login_time).total_seconds() / 60)
        user = get_current_user() or {}
        try:
            save_login_audit(
                user_email=user.get("email", ""),
                user_name=user.get("name", ""),
                user_role=user.get("role", ""),
                action="session_timeout",
                session_duration_minutes=dur,
            )
        except Exception:
            pass
        logout()
        st.warning("Your session has expired due to inactivity. Please sign in again.")
        st.rerun()

    # NHS header
    logo_col, title_col = st.columns([1, 5])
    with logo_col:
        try:
            st.image("images/Logo.png", width=120)
        except Exception:
            st.markdown(
                '<div style="background:#005EB8;color:white;font-weight:700;'
                'font-size:1.4rem;padding:12px;border-radius:4px;text-align:center">'
                'NHS</div>',
                unsafe_allow_html=True,
            )
    with title_col:
        st.markdown(
            '<div class="nhs-hero">'
            "<h1>GP Triage Assistant — HandoverAI</h1>"
            "<p>Supporting NHS clinical teams with safe, explainable, "
            "evidence-based triage decisions</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    # Safety banner
    st.markdown(
        '<div class="safety-banner">'
        "AI assists clinicians — the final triage decision always rests with the "
        "clinician. &nbsp;|&nbsp; "
        "This system is a Proof of Concept and must not be used with real patient data."
        "</div>",
        unsafe_allow_html=True,
    )

    _render_role_notice()
    render_sidebar()

    if not st.session_state.initialized:
        initialize_system()
        st.success("System ready.")

    # ── Role-gated tabs ──────────────────────────────────────────────────────
    from src.auth import can_access  # noqa: PLC0415

    role = get_user_role()
    st.markdown("---")

    # Build tab list based on role
    tab_specs: list[tuple[str, str]] = []
    if can_access("triage"):
        tab_specs.append(("Triage", "triage"))
    tab_specs.append(("Patient Pathway", "pathway"))      # all roles
    if can_access("dashboard"):
        tab_specs.append(("Dashboard", "dashboard"))
    tab_specs.append(("About & Governance", "governance"))  # all roles

    tab_labels  = [t[0] for t in tab_specs]
    tab_keys    = [t[1] for t in tab_specs]
    rendered_tabs = st.tabs(tab_labels)

    for tab_obj, key in zip(rendered_tabs, tab_keys):
        with tab_obj:
            if key == "triage":
                render_triage()
            elif key == "pathway":
                render_pathway()
            elif key == "dashboard":
                render_executive_dashboard()
            elif key == "governance":
                render_governance_panel()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point — auth gate
# ──────────────────────────────────────────────────────────────────────────────

if is_authenticated():
    main()
else:
    _render_login_page()
