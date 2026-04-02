"""
GP Triage POC — NHS Showcase Edition v0.2.0

Designed for three audiences: Executives, GPs/Clinicians, IT/IG teams.

Phases implemented
------------------
  Phase 1 — NHS UI redesign (colour palette, typography, safety banner)
  Phase 2 — Explainability panel (top-3 matched cases, confidence in plain English)
  Phase 3 — Enhanced audit log (CSV export, override reason dropdown, summary stats)
  Phase 4 — Demo scenarios (sidebar dropdown, auto-fill)
  Phase 5 — Executive metrics dashboard (KPIs, charts, time-saved estimate)
  Phase 6 — Governance panel (how it works, data handling, FHIR placeholder)
"""
import streamlit as st

import config
from src.vector_store import vector_store
from src.rag_pipeline import RAGPipeline
from ui.sidebar import render_sidebar
from tabs.triage_tab import render_triage
from tabs.dashboard_tab import render_executive_dashboard
from tabs.governance_tab import render_governance_panel

# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GP Triage Assistant - AI Powered",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — NHS Design System CSS
# NHS palette: #005EB8 blue | #DA291C red | #FFB81C amber | #009639 green
#              #003087 dark blue | #AEB7BD grey | #F0F4F5 page bg
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

    /* ── Sidebar ── */
    [data-testid="stSidebar"] { background-color: #005EB8 !important; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    [data-testid="stSidebar"] .stAlert {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
    }
    /* Load Scenario button — NHS blue with white text */
    [data-testid="stSidebar"] .stButton button {
        background-color: #003087 !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        border: 2px solid #ffffff !important;
        width: 100%;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        background-color: #002060 !important;
    }
    [data-testid="stSidebar"] [data-testid="stMetric"] {
        background-color: rgba(255,255,255,0.15);
        border-radius: 0.4rem;
        padding: 0.3rem 0.5rem;
    }
    /* Sidebar selectbox — fix label visibility (white text on blue hides on white input) */
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div:first-child {
        background-color: rgba(255,255,255,0.15) !important;
        border: 1px solid rgba(255,255,255,0.5) !important;
    }
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] span,
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] div {
        color: #ffffff !important;
    }
    /* Dropdown option list renders outside sidebar — ensure readable text */
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

    /* ── Triage result cards — exact NHS colours ── */
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

    /* ── Primary button ── */
    [data-testid="stButton"] button[kind="primary"] {
        background-color: #005EB8 !important; font-size: 1.05rem !important;
        font-weight: 700 !important; padding: 0.7rem 2rem !important;
        border-radius: 0.4rem !important;
    }

    p, li { font-size: 1rem !important; }
    h2 { font-size: 1.35rem !important; }
    h3 { font-size: 1.15rem !important; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────────────────────

if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.triage_history = []
    st.session_state.audit_log = []
    st.session_state.last_result = None


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
        st.session_state.initialized = True


# ──────────────────────────────────────────────────────────────────────────────
# Main layout
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Phase 1 — NHS header
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
            "<h1>GP Triage Assistant — AI Powered</h1>"
            "<p>Supporting NHS clinical teams with safe, explainable, "
            "evidence-based triage decisions</p>"
            "</div>",
            unsafe_allow_html=True,
        )

    # Phase 1 — Clinician safety banner
    st.markdown(
        '<div class="safety-banner">'
        "AI assists clinicians — the final triage decision always rests with the "
        "clinician. &nbsp;|&nbsp; "
        "This system is a Proof of Concept and must not be used with real patient data."
        "</div>",
        unsafe_allow_html=True,
    )

    # Sidebar
    render_sidebar()

    # Initialise system on first load
    if not st.session_state.initialized:
        initialize_system()
        st.success("System ready.")

    # ── Tabs ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs([
        "Triage",
        "Dashboard",
        "About & Governance",
    ])
    with tab1:
        render_triage()
    with tab2:
        render_executive_dashboard()
    with tab3:
        render_governance_panel()


if __name__ == "__main__":
    main()
