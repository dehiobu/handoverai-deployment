"""
tabs/governance_tab.py — About & Governance tab (Phase 6).
"""
import streamlit as st


def render_governance_panel() -> None:
    """Render the About & Governance tab."""
    st.markdown(
        '<div class="section-heading">About This System & Governance Information</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "This panel is intended for NHS IT leads, Information Governance officers, "
        "and executive stakeholders evaluating this system."
    )

    g1, g2 = st.columns(2)

    with g1:
        st.markdown("""<div class="gov-card">
<h3>How the AI Works</h3>
<p>This system uses <strong>Retrieval-Augmented Generation (RAG)</strong> — a two-stage approach:</p>
<ol>
<li><strong>Retrieval:</strong> The patient description is converted to a numerical embedding
and compared against 447 AI-validated clinical cases in a vector database (ChromaDB).
The 5 most similar cases are retrieved.</li>
<li><strong>Generation:</strong> GPT-4o receives the retrieved cases as clinical context
alongside the patient description and synthesises a structured triage recommendation
aligned with NHS and NICE guidelines.</li>
</ol>
<p>The system always errs on the side of caution — when in doubt, it escalates to a
higher acuity level.</p>
</div>""", unsafe_allow_html=True)

        st.markdown("""<div class="gov-card">
<h3>Limitations &amp; Intended Use</h3>
<ul>
<li>This is a <strong>Proof of Concept only</strong> — not validated for clinical use</li>
<li>Training corpus: 447 cases. Broader clinical coverage requires more data</li>
<li>AI recommendations may be inconsistent across similar presentations</li>
<li>Cannot replace physical examination or full clinical history-taking</li>
<li>Must not be used with real patient data in its current state</li>
<li>All AI recommendations require clinician review before any action is taken</li>
</ul>
</div>""", unsafe_allow_html=True)

    with g2:
        st.markdown("""<div class="gov-card">
<h3>Data Handling &amp; Privacy</h3>
<ul>
<li><strong>No persistent patient storage:</strong> All session data is held in memory
only and cleared on reset. Nothing is written to disk.</li>
<li><strong>Audit log:</strong> Session-only. Exportable by the clinician on demand.
No automatic transmission or logging.</li>
<li><strong>OpenAI API:</strong> Patient descriptions are sent to OpenAI for processing.
Production deployment would require a Data Processing Agreement (DPA) and NHS IG sign-off.</li>
<li><strong>Embeddings model:</strong> OpenAI text-embedding-3-small. Subject to OpenAI
zero data retention policy (per API agreement).</li>
<li><strong>No PII should be entered</strong> during this POC evaluation.</li>
</ul>
</div>""", unsafe_allow_html=True)

        st.markdown("""<div class="gov-card">
<h3>Audit Capabilities</h3>
<ul>
<li>Every triage decision is timestamped and logged in-session</li>
<li>Clinician overrides captured with reason category and free-text detail</li>
<li>Response times recorded per case for performance monitoring</li>
<li>Full session audit downloadable as JSON or CSV</li>
<li>Production deployment would integrate with NHS Audit Trail requirements</li>
</ul>
</div>""", unsafe_allow_html=True)

    st.markdown("""<div class="gov-card">
<h3>FHIR &amp; NHS Integration Roadmap (Placeholder)</h3>
<p>A production version of this system could integrate with NHS infrastructure:</p>
<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:0.92rem">
<tr style="background:#005EB8;color:white">
<th style="padding:8px;text-align:left">Integration</th>
<th style="padding:8px;text-align:left">Capability</th>
<th style="padding:8px;text-align:left">Status</th>
</tr>
<tr style="background:#f4f8ff">
<td style="padding:8px"><strong>FHIR R4 API</strong></td>
<td style="padding:8px">Export triage results as FHIR Encounter resources; HL7 compatible output</td>
<td style="padding:8px">Planned</td>
</tr>
<tr>
<td style="padding:8px"><strong>NHS Spine / PDS</strong></td>
<td style="padding:8px">Patient demographics lookup; structured referral to 111/999 pathways</td>
<td style="padding:8px">Planned</td>
</tr>
<tr style="background:#f4f8ff">
<td style="padding:8px"><strong>EPR Systems</strong></td>
<td style="padding:8px">EMIS/SystmOne integration via MESH/API; auto-populate clinical notes</td>
<td style="padding:8px">Planned</td>
</tr>
<tr>
<td style="padding:8px"><strong>NHS Login</strong></td>
<td style="padding:8px">Clinician identity and role-based access control</td>
<td style="padding:8px">Planned</td>
</tr>
</table>
</div>""", unsafe_allow_html=True)

    st.markdown("""<div class="gov-card" style="border-left:4px solid #FFB81C">
<h3>NHS Approvals Required for Clinical Deployment</h3>
<p>Before this system could be used clinically, it would require:</p>
<ul>
<li><strong>DTAC</strong> (Digital Technology Assessment Criteria) assessment</li>
<li><strong>DCB0129 / DCB0160</strong> clinical risk management compliance</li>
<li><strong>Data Security &amp; Protection Toolkit</strong> (DSPT) review</li>
<li><strong>Information Governance sign-off</strong> and DPA with OpenAI</li>
<li><strong>Clinical Safety Officer</strong> designation and clinical safety case</li>
<li><strong>CE / UKCA marking</strong> assessment under UK MDR if classified as a medical device</li>
<li><strong>NHS AI Lab</strong> algorithmic transparency and bias review</li>
</ul>
</div>""", unsafe_allow_html=True)
