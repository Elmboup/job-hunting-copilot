import asyncio

import nest_asyncio
import streamlit as st

nest_asyncio.apply()  # allow loop.run_until_complete inside Streamlit's own event loop


def run_async(coro):
    """Run a coroutine from synchronous Streamlit code."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def _cv_rows_from_editor(df, fields):
    """Convert a data_editor DataFrame back to clean rows (drop empty lines)."""
    rows = []
    if df is None:
        return rows
    for record in df.to_dict("records"):
        row = {f: str(record.get(f) or "").strip() for f in fields}
        if any(row.values()):
            rows.append(row)
    return rows

# Page config
st.set_page_config(
    page_title="Copilote IA Recherche d'Emploi",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS — clean, professional design system
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
    --ink: #0F172A;
    --ink-2: #334155;
    --muted: #64748B;
    --border: #E2E8F0;
    --accent: #0E7490;
    --accent-strong: #0C6377;
    --accent-soft: #F0F7FA;
    --radius: 8px;
}

/* ---------- Base ---------- */
html, body, .stApp, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    font-feature-settings: 'tnum' 1;
}
.stApp { background: #F8F9FB; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1100px; }
.stApp h1, .stApp h2, .stApp h3 {
    color: var(--ink);
    letter-spacing: -0.01em;
}
hr { border-color: var(--border); }

/* ---------- Masthead ---------- */
.masthead {
    display: flex;
    align-items: center;
    gap: 14px;
    padding-bottom: 18px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 14px;
}
.masthead-mark {
    width: 38px; height: 38px;
    border-radius: 10px;
    background: var(--accent);
    color: #ffffff;
    font-weight: 700; font-size: 15px;
    display: flex; align-items: center; justify-content: center;
    flex: none;
}
.masthead h1 {
    font-size: 1.25rem; font-weight: 700;
    margin: 0; line-height: 1.25; color: var(--ink);
}
.masthead p {
    font-size: 0.875rem; color: var(--muted); margin: 2px 0 0;
}

/* ---------- Tabs (underline) ---------- */
.stTabs [data-baseweb="tab-list"] {
    border-bottom: 1px solid var(--border);
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 8px 6px;
    margin-right: 20px;
    font-weight: 500; font-size: 0.9rem;
    color: var(--muted);
    box-shadow: none;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--ink-2); background: transparent; }
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: var(--ink);
    border-bottom-color: var(--accent);
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ---------- Buttons ---------- */
.stButton > button, .stButton a {
    background: #ffffff;
    color: var(--ink-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-weight: 500; font-size: 0.875rem;
    padding: 0.3rem 1rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    text-decoration: none;
}
.stButton > button:hover, .stButton a:hover {
    background: #F8FAFC;
    border-color: #CBD5E1;
    color: var(--ink);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
    transform: none;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: var(--accent);
    border-color: var(--accent);
    color: #ffffff;
}
.stButton > button[kind="primary"]:hover {
    background: var(--accent-strong);
    border-color: var(--accent-strong);
    color: #ffffff;
}

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {
    border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] .stMarkdown h3 {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 0.75rem;
}
[data-testid="stSidebar"] hr { margin: 1rem 0; }

/* ---------- Cards & rows ---------- */
.job-card {
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.95rem 1.1rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.15s ease;
}
.job-card:hover { border-color: #CBD5E1; }
a.job-card {
    display: block;
    text-decoration: none;
    color: inherit;
}
a.job-card:hover { background: #FCFDFE; }
.external { color: var(--muted); font-size: 0.75em; margin-left: 3px; }
.job-card:hover .external { color: var(--accent); }
.job-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
}
.job-title {
    font-size: 0.95rem; font-weight: 600;
    color: var(--ink); line-height: 1.35;
}
.job-company { font-size: 0.85rem; color: var(--muted); margin-top: 2px; }
.job-meta {
    display: flex; flex-wrap: wrap;
    font-size: 0.8rem; color: var(--muted);
    margin-top: 0.55rem;
}
.job-meta span + span::before {
    content: "·";
    margin: 0 0.5rem;
    color: #CBD5E1;
}
.match-badge {
    background: var(--accent-soft);
    color: #0C5C74;
    border: 1px solid #D7E9EF;
    border-radius: 6px;
    font-weight: 600; font-size: 0.8rem;
    padding: 0.3rem 0.6rem;
    white-space: nowrap;
    flex: none;
}

.application-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
}
.status-pill {
    font-size: 0.75rem; font-weight: 600;
    padding: 0.25rem 0.65rem;
    border-radius: 999px;
    white-space: nowrap;
}
.status-pending    { background: #FFF7ED; color: #9A3412; border: 1px solid #FED7AA; }
.status-interview { background: #F0F9FF; color: #075985; border: 1px solid #BAE6FD; }
.status-rejected  { background: #FEF2F2; color: #991B1B; border: 1px solid #FECACA; }
.status-offer     { background: #F0FDF4; color: #166534; border: 1px solid #BBF7D0; }

/* ---------- Metrics, chat, expanders ---------- */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.75rem 0.9rem;
}
[data-testid="stMetricLabel"] p {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
}
[data-testid="stMetricValue"] { font-weight: 600; }
[data-testid="stChatMessage"] {
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: none;
}
[data-testid="stExpander"] {
    border: 1px solid var(--border);
    border-radius: var(--radius);
}

/* ---------- Scrollbar & footer ---------- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: #D6DBE1; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #B8C0C9; }
.app-footer {
    text-align: center;
    color: #94A3B8;
    font-size: 0.78rem;
    padding: 1.6rem 0 0.5rem 0;
}
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'agent' not in st.session_state:
    st.session_state.agent = None
if 'tools' not in st.session_state:
    st.session_state.tools = None
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'user_profile' not in st.session_state:
    st.session_state.user_profile = {
        'name': 'Utilisateur',
        'skills': ['Python', 'SQL', 'Spark'],
        'experience': '3 ans',
        'location': 'Paris',
        'target_roles': ['Data Engineer', 'ML Engineer'],
        'contract_preference': 'CDI',
        'remote_preference': 'Hybride',
        'current_title': '',
        'summary': '',
        'experiences': [],
        'education': [],
        'languages': [],
        'certifications': [],
        'phone': '',
        'soft_skills': [],
        'motivations': '',
        'photo': ''
    }
if 'resume_text' not in st.session_state:
    st.session_state.resume_text = None
if 'resume_parsed' not in st.session_state:
    st.session_state.resume_parsed = None
if 'profile_loaded' not in st.session_state:
    st.session_state.profile_loaded = False

# Initialize agent + UC function tools (cached, lazy — see components/chat.py:
# ChatOpenAI on the Unity Gateway /ai-gateway/mlflow/v1 Chat Completions API
# because ChatDatabricks 404s on system.ai.* model services; one MCP server
# entry per UC function; prompt= instead of state_modifier — langgraph 1.x
# rename; no Vector Search endpoint — the UC TVFs already do semantic search).
@st.cache_resource
def get_agent_and_tools_cached():
    # Imported lazily so the UI renders even if the heavy LangChain/MCP stack
    # fails to import in the Apps runtime (the failure then surfaces as a
    # chat error instead of killing the whole app).
    from components.chat import get_agent_and_tools
    return get_agent_and_tools()


def ensure_agent():
    """Lazily initialize the agent + tools (first chat message or search)."""
    if st.session_state.agent is None:
        st.session_state.agent, st.session_state.tools = get_agent_and_tools_cached()
    return st.session_state.agent, st.session_state.tools
    

    

    

    

    




# Sidebar - User Profile
with st.sidebar:
    st.markdown("### Profil")

    # Load the saved profile from Lakebase once per session (silently keeps
    # local defaults when Lakebase is not reachable yet).
    if not st.session_state.profile_loaded:
        st.session_state.profile_loaded = True
        try:
            from components import db as db_mod
            saved = db_mod.load_profile(db_mod.current_user_email())
            if saved:
                for key in ('name', 'experience', 'remote_preference', 'contract_preference'):
                    if saved.get(key):
                        st.session_state.user_profile[key] = saved[key]
                if saved.get('location_preferences'):
                    st.session_state.user_profile['location'] = saved['location_preferences'][0]
                if saved.get('target_roles'):
                    st.session_state.user_profile['target_roles'] = saved['target_roles']
                if saved.get('skills'):
                    st.session_state.user_profile['skills'] = list(saved['skills'])
                if saved.get('current_title'):
                    st.session_state.user_profile['current_title'] = saved['current_title']
                if saved.get('summary'):
                    st.session_state.user_profile['summary'] = saved['summary']
                for _cv_key in ('experiences', 'education', 'languages', 'certifications'):
                    if saved.get(_cv_key):
                        st.session_state.user_profile[_cv_key] = list(saved[_cv_key])
                if saved.get('phone'):
                    st.session_state.user_profile['phone'] = saved['phone']
                if saved.get('soft_skills'):
                    st.session_state.user_profile['soft_skills'] = list(saved['soft_skills'])
                if saved.get('motivations'):
                    st.session_state.user_profile['motivations'] = saved['motivations']
                if saved.get('photo'):
                    st.session_state.user_profile['photo'] = saved['photo']
                if saved.get('resume_text'):
                    st.session_state.resume_text = saved['resume_text']
        except Exception:
            pass  # Lakebase unavailable — local defaults stay in place

    # Editable profile
    with st.expander("Modifier le profil", expanded=False):
        st.caption("Identité, critères de recherche et CV structuré — sauvegardé dans Lakebase.")
        st.session_state.user_profile['name'] = st.text_input(
            "Nom", 
            value=st.session_state.user_profile['name']
        )
        st.session_state.user_profile['current_title'] = st.text_input(
            "Titre actuel (ex: Data Engineer)",
            value=st.session_state.user_profile.get('current_title', '')
        )
        st.session_state.user_profile['summary'] = st.text_area(
            "Résumé professionnel",
            value=st.session_state.user_profile.get('summary', ''),
            height=100,
        )
        
        st.session_state.user_profile['experience'] = st.text_input(
            "Expérience",
            value=st.session_state.user_profile['experience']
        )
        
        cities = ['Paris', 'Lyon', 'Marseille', 'Toulouse', 'Nantes', 'Bordeaux', 'Lille', 'Nice']
        st.session_state.user_profile['location'] = st.selectbox(
            "Localisation",
            cities,
            index=cities.index(st.session_state.user_profile['location'])
            if st.session_state.user_profile['location'] in cities else 0
        )
        
        st.session_state.user_profile['contract_preference'] = st.selectbox(
            "Type de contrat",
            ['CDI', 'CDD', 'Freelance', 'Stage', 'Alternance'],
            index=0
        )
        
        st.session_state.user_profile['remote_preference'] = st.selectbox(
            "Télétravail",
            ['Remote', 'Hybride', 'Sur site'],
            index=1
        )
        
        skills_input = st.text_area(
            "Compétences (séparées par des virgules)",
            value=', '.join(st.session_state.user_profile['skills'])
        )
        st.session_state.user_profile['skills'] = [s.strip() for s in skills_input.split(',')]

        import pandas as pd

        st.markdown("**Expériences professionnelles**")
        exp_df = st.data_editor(
            pd.DataFrame(
                st.session_state.user_profile.get('experiences') or [],
                columns=['title', 'company', 'start_date', 'end_date', 'description'],
            ),
            column_config={
                'title': st.column_config.TextColumn('Poste'),
                'company': st.column_config.TextColumn('Entreprise'),
                'start_date': st.column_config.TextColumn('Début'),
                'end_date': st.column_config.TextColumn('Fin'),
                'description': st.column_config.TextColumn('Description'),
            },
            num_rows='dynamic',
            use_container_width=True,
            key='exp_editor',
        )
        st.session_state.user_profile['experiences'] = _cv_rows_from_editor(
            exp_df, ('title', 'company', 'start_date', 'end_date', 'description'))

        st.markdown("**Formations**")
        edu_df = st.data_editor(
            pd.DataFrame(
                st.session_state.user_profile.get('education') or [],
                columns=['degree', 'school', 'year'],
            ),
            column_config={
                'degree': st.column_config.TextColumn('Diplôme'),
                'school': st.column_config.TextColumn('École / Université'),
                'year': st.column_config.TextColumn('Année'),
            },
            num_rows='dynamic',
            use_container_width=True,
            key='edu_editor',
        )
        st.session_state.user_profile['education'] = _cv_rows_from_editor(
            edu_df, ('degree', 'school', 'year'))

        st.markdown("**Langues**")
        lang_df = st.data_editor(
            pd.DataFrame(
                st.session_state.user_profile.get('languages') or [],
                columns=['name', 'level'],
            ),
            column_config={
                'name': st.column_config.TextColumn('Langue'),
                'level': st.column_config.TextColumn('Niveau (A1-C2, Courant…)'),
            },
            num_rows='dynamic',
            use_container_width=True,
            key='lang_editor',
        )
        st.session_state.user_profile['languages'] = _cv_rows_from_editor(
            lang_df, ('name', 'level'))

        st.markdown("**Certifications**")
        cert_df = st.data_editor(
            pd.DataFrame(
                st.session_state.user_profile.get('certifications') or [],
                columns=['name', 'issuer', 'year'],
            ),
            column_config={
                'name': st.column_config.TextColumn('Certification'),
                'issuer': st.column_config.TextColumn('Organisme'),
                'year': st.column_config.TextColumn('Année'),
            },
            num_rows='dynamic',
            use_container_width=True,
            key='cert_editor',
        )
        st.session_state.user_profile['certifications'] = _cv_rows_from_editor(
            cert_df, ('name', 'issuer', 'year'))

        # Resume upload — parsing fills the profile fields automatically
        resume_file = st.file_uploader(
            "CV (PDF, DOCX, TXT) — extraction automatique des compétences",
            type=["pdf", "docx", "doc", "txt", "md"],
        )
        if resume_file is not None and st.session_state.resume_parsed != resume_file.name:
            from components import resume as resume_mod  # lazy import
            with st.spinner("Analyse du CV en cours…"):
                try:
                    text = resume_mod.extract_resume_text(
                        resume_file.getvalue(), resume_file.name
                    )
                    extracted = resume_mod.extract_profile_from_resume(text)
                    st.session_state.resume_text = text
                    st.session_state.resume_parsed = resume_file.name
                    if extracted['skills']:
                        st.session_state.user_profile['skills'] = extracted['skills']
                    if extracted['name']:
                        st.session_state.user_profile['name'] = extracted['name']
                    if extracted['years_experience']:
                        st.session_state.user_profile['experience'] = extracted['years_experience']
                    if extracted.get('current_title'):
                        st.session_state.user_profile['current_title'] = extracted['current_title']
                    if extracted.get('summary'):
                        st.session_state.user_profile['summary'] = extracted['summary']
                    for _cv_key in ('experiences', 'education', 'languages', 'certifications'):
                        if extracted.get(_cv_key):
                            st.session_state.user_profile[_cv_key] = extracted[_cv_key]
                    st.success(
                        f"CV analysé — {len(extracted['skills'])} compétences, "
                        f"{len(extracted.get('experiences', []))} expériences, "
                        f"{len(extracted.get('education', []))} formations, "
                        f"{len(extracted.get('languages', []))} langues, "
                        f"{len(extracted.get('certifications', []))} certifications extraites. "
                        "Vérifiez et complétez les sections ci-dessus."
                    )
                except Exception as e:
                    st.error(f"Analyse du CV impossible : {e}")
    
    # Persist the profile (and parsed resume) to Lakebase
    if st.button("Sauvegarder le profil"):
        try:
            from components import db as db_mod
            email = db_mod.current_user_email()
            user_id = db_mod.get_user_id(email, st.session_state.user_profile['name'])
            profile = {
                'name': st.session_state.user_profile['name'],
                'experience': st.session_state.user_profile['experience'],
                'target_roles': st.session_state.user_profile.get('target_roles') or [],
                'location_preferences': [st.session_state.user_profile['location']],
                'remote_preference': st.session_state.user_profile['remote_preference'],
                'contract_preference': st.session_state.user_profile['contract_preference'],
                'resume_text': st.session_state.resume_text,
                'current_title': st.session_state.user_profile.get('current_title', ''),
                'summary': st.session_state.user_profile.get('summary', ''),
                'experiences': st.session_state.user_profile.get('experiences') or [],
                'education': st.session_state.user_profile.get('education') or [],
                'languages': st.session_state.user_profile.get('languages') or [],
                'certifications': st.session_state.user_profile.get('certifications') or [],
                'phone': st.session_state.user_profile.get('phone', ''),
                'soft_skills': st.session_state.user_profile.get('soft_skills') or [],
                'motivations': st.session_state.user_profile.get('motivations', ''),
                'photo': st.session_state.user_profile.get('photo', ''),
            }
            db_mod.save_profile(
                user_id, profile,
                st.session_state.user_profile['skills'],
                source='resume' if st.session_state.resume_text else 'manual',
            )
            st.success("Profil sauvegardé dans Lakebase.")
        except Exception as e:
            st.error(f"Sauvegarde impossible : {e}")

    # Display current profile
    st.markdown("---")
    st.write(f"**Nom:** {st.session_state.user_profile['name']}")
    st.write(f"**Expérience:** {st.session_state.user_profile['experience']}")
    st.write(f"**Localisation:** {st.session_state.user_profile['location']}")
    st.write(f"**Contrat:** {st.session_state.user_profile['contract_preference']}")
    st.write(f"**Télétravail:** {st.session_state.user_profile['remote_preference']}")
    if st.session_state.user_profile.get('current_title'):
        st.write(f"**Titre actuel:** {st.session_state.user_profile['current_title']}")
    if st.session_state.user_profile.get('experiences'):
        st.write(f"**Expériences détaillées:** {len(st.session_state.user_profile['experiences'])}")
    if st.session_state.user_profile.get('education'):
        st.write(f"**Formations:** {len(st.session_state.user_profile['education'])}")
    if st.session_state.user_profile.get('languages'):
        st.write(f"**Langues:** {len(st.session_state.user_profile['languages'])}")
    if st.session_state.user_profile.get('certifications'):
        st.write(f"**Certifications:** {len(st.session_state.user_profile['certifications'])}")
    
    st.markdown("**Compétences:**")
    for skill in st.session_state.user_profile['skills'][:5]:
        st.write(f"• {skill}")
    
    st.markdown("---")
    
    # Quick stats — static for now: the get_market_stats TVF still has a
    # duplicate-companies aggregation quirk (recorded in project memory), so
    # showing its output would be misleading. Switch to the UC tool once
    # fixed. The old VectorSearchClient block always failed (no endpoint or
    # index is provisioned in this workspace).
    st.markdown("### Statistiques")
    st.metric("Offres disponibles", "264+")
        

        


# Main content
st.markdown("""
<div class="masthead">
    <div class="masthead-mark">JC</div>
    <div>
        <h1>Copilote Recherche d'Emploi</h1>
        <p>Assistant IA pour trouver, analyser et décrocher votre prochain poste — propulsé par Databricks.</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["Chat", "Recherche d'offres", "Candidatures", "Mon Profil"])

# Tab 1: Chat Interface
with tab1:
    st.markdown("### Discutez avec votre assistant IA")
    st.markdown("*Posez des questions sur les offres d'emploi, demandez des conseils, ou générez des lettres de motivation.*")
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Posez votre question... (ex: 'Trouve-moi des postes de data engineer à Paris')"):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get agent response
        with st.chat_message("assistant"):
            with st.spinner("Réflexion en cours…"):
                try:
                    # Initialize agent + tools if needed
                    agent, _tools = ensure_agent()
                    
                    # Build context from user profile
                    context = f"\n\nProfil utilisateur: {st.session_state.user_profile['experience']}, "
                    context += f"compétences: {', '.join(st.session_state.user_profile['skills'][:5])}, "
                    context += f"localisation: {st.session_state.user_profile['location']}"
                    
                    full_prompt = prompt + context
                    
                    # Run agent
                    result = run_async(agent.ainvoke({
                        "messages": [{"role": "user", "content": full_prompt}]
                    }))
                    
                    response = result["messages"][-1].content
                    
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    
                except Exception as e:
                    error_msg = f"Erreur : {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

# Tab 2: Job Search
with tab2:
    st.markdown("### Recherche d'offres")
    
    # Search filters
    col1, col2, col3 = st.columns(3)
    
    with col1:
        search_query = st.text_input(
            "Mots-clés",
            value="data engineer",
            placeholder="Ex: data engineer, développeur python..."
        )
    
    with col2:
        location_filter = st.selectbox(
            "Ville",
            ['Toutes', 'Paris', 'Lyon', 'Marseille', 'Toulouse', 'Nantes', 'Bordeaux', 'Lille']
        )
    
    with col3:
        contract_filter = st.selectbox(
            "Type de contrat",
            ['Tous', 'CDI', 'CDD', 'Freelance', 'Stage', 'Alternance']
        )
    
    col4, col5 = st.columns(2)
    
    with col4:
        remote_only = st.checkbox("Remote uniquement")
    
    with col5:
        num_results = st.slider("Nombre de résultats", 5, 20, 10)
    
    # Search button
    if st.button("Rechercher", type="primary"):
        with st.spinner("Recherche en cours..."):
            try:
                # Direct call to the search_jobs UC function (no LLM in the
                # loop): the TVF embeds the query and scores jobs with cosine
                # similarity. Results are stored in session_state so they
                # survive the rerun triggered by the inner buttons below.
                _agent, tools = ensure_agent()
                from components.search import search_jobs  # lazy import — see note above
                st.session_state.search_results = run_async(search_jobs(
                    tools,
                    user_query=search_query,
                    location=None if location_filter == 'Toutes' else location_filter,
                    contract_type=None if contract_filter == 'Tous' else contract_filter,
                    remote_only=remote_only,
                    max_results=num_results,
                ))
                

                

                

                

                

                
            except Exception as e:
                st.error(f"Erreur lors de la recherche : {str(e)}")

    # Render stored results — kept in session_state so they survive the rerun
    # triggered by the inner buttons (letter generation is an LLM call).
    jobs = st.session_state.get('search_results')
    if jobs:
        st.success(f"{len(jobs)} offres trouvées")
        for i, job in enumerate(jobs, 1):
            with st.container():
                url = job.get('url')
                card_open = (
                    f'<a class="job-card" href="{url}" target="_blank" rel="noopener noreferrer">'
                    if url else '<div class="job-card">'
                )
                card_close = '</a>' if url else '</div>'
                st.markdown(f"""
                {card_open}
                    <div class="job-card-header">
                        <div>
                            <div class="job-title">{i}. {job.get('title') or 'Poste'}{' <span class="external">↗</span>' if url else ''}</div>
                            <div class="job-company">{job.get('company') or 'Entreprise non spécifiée'}</div>
                        </div>
                        <span class="match-badge" title="Score de correspondance">{job.get('match_score', 0):.0%}</span>
                    </div>
                    <div class="job-meta">
                        <span>{job.get('location') or '—'}</span>
                        <span>{job.get('contract_type_fr') or '—'}</span>
                        <span>{job.get('remote_type') or '—'}</span>
                        {f'<span>{job["salary_min"]:,} - {job["salary_max"]:,} €</span>' if job.get('salary_min') else ''}
                    </div>
                {card_close}
                """, unsafe_allow_html=True)
                        
                # Expandable details
                with st.expander("Détails"):
                    st.markdown(f"**Score de correspondance:** {job.get('match_score', 0):.2f}")
                            
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        if st.button("Sauvegarder", key=f"save_{job['job_id']}"):
                            try:
                                from components import db as db_mod
                                user_id = db_mod.get_user_id(
                                    db_mod.current_user_email(),
                                    st.session_state.user_profile['name'],
                                )
                                is_new = db_mod.save_application(user_id, job)
                                st.success(
                                    "Candidature sauvegardée." if is_new
                                    else "Candidature déjà suivie — mise à jour."
                                )
                            except Exception as e:
                                st.error(f"Sauvegarde impossible : {e}")
                    with col_b:
                        if st.button("Lettre de motivation", key=f"letter_{job['job_id']}"):
                            # Generate via the draft_cover_letter UC function (LLM call)
                            from components.search import draft_cover_letter  # lazy import
                            with st.spinner("Rédaction en cours..."):
                                letter = run_async(draft_cover_letter(
                                    st.session_state.tools,
                                    job_title=job.get('title') or 'Data Engineer',
                                    company=job.get('company') or '',
                                    job_description=(
                                        f"{job.get('title')} — {job.get('location')} "
                                        f"({job.get('contract_type_fr')})"
                                    ),
                                    user_background=(
                                        f"{st.session_state.user_profile['experience']}, "
                                        f"compétences: {', '.join(st.session_state.user_profile['skills'][:5])}"
                                    ),
                                ))
                            if letter:
                                st.markdown(letter)
                                st.session_state[f'letter_{job["job_id"]}'] = letter
                                try:
                                    from components import db as _db_doc
                                    _uid = _db_doc.get_user_id(
                                        _db_doc.current_user_email(),
                                        st.session_state.user_profile['name'],
                                    )
                                    _db_doc.save_document(
                                        _uid, 'lettre',
                                        f"Lettre — {job.get('title') or 'Poste'} @ {job.get('company') or ''}",
                                        letter,
                                    )
                                    st.success("Lettre enregistrée dans Mon Profil → Documents.")
                                except Exception as e:
                                    st.warning(f"Lettre générée mais non enregistrée : {e}")
                            else:
                                st.warning("Impossible de générer la lettre — demandez-la dans le chat.")
                    with col_c:
                        if job.get('url'):
                            st.link_button("Postuler", job['url'], type="primary")
                


# Tab 3: Applications
with tab3:
    st.markdown("### Mes candidatures")
    
    # Applications are persisted in Lakebase (app_data.applications)
    db_mod = None
    try:
        from components import db as _db
        db_mod = _db
    except Exception as e:
        st.error(f"Module base de données indisponible : {e}")

    user_id = None
    applications = []
    if db_mod:
        try:
            user_id = db_mod.get_user_id(
                db_mod.current_user_email(),
                st.session_state.user_profile['name'],
            )
            applications = db_mod.list_applications(user_id)
        except Exception as e:
            st.warning(f"Lakebase indisponible : {e}")
    
    if applications:
        st.markdown(f"#### {len(applications)} candidature(s) suivie(s)")
        status_class = {
            "En cours": "status-pending",
            "Entretien": "status-interview",
            "Offre": "status-offer",
            "Rejeté": "status-rejected",
        }
        for app_row in applications:
            status = app_row['status'] or "En cours"
            date_str = str(app_row['applied_date'] or '')
            st.markdown(f"""
            <div class="application-row">
                <div>
                    <div class="job-title">{app_row['title'] or app_row['job_id']}</div>
                    <div class="job-company">{app_row['company'] or '—'} · {date_str}</div>
                </div>
                <span class="status-pill {status_class.get(status, 'status-pending')}">{status}</span>
            </div>
            """, unsafe_allow_html=True)
            with st.expander("Gérer"):
                col_s, col_u, col_l = st.columns(3)
                with col_s:
                    new_status = st.selectbox(
                        "Statut",
                        db_mod.APPLICATION_STATUSES,
                        index=(db_mod.APPLICATION_STATUSES.index(status)
                               if status in db_mod.APPLICATION_STATUSES else 0),
                        key=f"status_{app_row['application_id']}",
                    )
                with col_u:
                    if st.button("Mettre à jour", key=f"upd_{app_row['application_id']}"):
                        try:
                            db_mod.update_application(
                                app_row['application_id'],
                                status=new_status,
                                notes=st.session_state.get(
                                    f"notes_{app_row['application_id']}_input"
                                ),
                            )
                            st.success("Candidature mise à jour.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Mise à jour impossible : {e}")
                with col_l:
                    if app_row.get('url'):
                        st.link_button("Voir l'offre", app_row['url'])
                st.text_area(
                    "Notes",
                    value=app_row.get('notes') or "",
                    key=f"notes_{app_row['application_id']}_input",
                    height=100,
                )
                col_m, col_i = st.columns(2)
                with col_m:
                    if st.button("✉️ Mail de relance", key=f"relance_{app_row['application_id']}"):
                        from components import generators  # lazy import
                        with st.spinner("Rédaction du mail de relance…"):
                            try:
                                mail = generators.generate_followup_email(
                                    st.session_state.user_profile, app_row)
                                st.markdown(mail)
                                db_mod.save_document(
                                    user_id, 'mail_relance',
                                    f"Relance — {app_row['title'] or 'Poste'} @ {app_row['company'] or ''}",
                                    mail,
                                )
                                st.success("Mail enregistré dans Mon Profil → Documents.")
                            except Exception as e:
                                st.error(f"Génération impossible : {e}")
                with col_i:
                    if st.button("🎤 Préparer l'entretien", key=f"prep_{app_row['application_id']}"):
                        from components import generators  # lazy import
                        with st.spinner("Préparation de l'entretien (RH + technique)…"):
                            try:
                                prep = generators.generate_interview_prep(
                                    st.session_state.user_profile, app_row)
                                st.markdown(prep)
                                db_mod.save_document(
                                    user_id, 'prep_entretien',
                                    f"Préparation — {app_row['title'] or 'Poste'} @ {app_row['company'] or ''}",
                                    prep,
                                )
                                st.success("Guide enregistré dans Mon Profil → Documents.")
                            except Exception as e:
                                st.error(f"Génération impossible : {e}")
    elif user_id is not None:
        st.info(
            "Aucune candidature pour l'instant. Sauvegardez des offres depuis "
            "l'onglet « Recherche d'offres » → Détails → Sauvegarder."
        )

# Tab 4: Mon Profil — photo, coordonnées, documents, générations de l'Agent
with tab4:
    st.markdown("### 👤 Mon Profil")
    st.caption(
        "Votre espace carrière : photo, coordonnées, documents et créations de l'Agent. "
        "Les sections détaillées (expériences, formations, langues, certifications) "
        "s'éditent dans « Modifier le profil » de la barre latérale."
    )

    col_photo, col_id = st.columns([1, 3])
    with col_photo:
        st.markdown("**📸 Photo**")
        photo_file = st.file_uploader(
            "Photo de profil (optionnel)", type=["png", "jpg", "jpeg"],
            key="photo_uploader",
        )
        if photo_file is not None and st.session_state.get('photo_name') != photo_file.name:
            import base64 as _b64
            _ext = photo_file.name.rsplit('.', 1)[-1].lower()
            st.session_state.user_profile['photo'] = (
                f"data:image/{_ext};base64,"
                + _b64.b64encode(photo_file.getvalue()).decode()
            )
            st.session_state.photo_name = photo_file.name
        _photo = st.session_state.user_profile.get('photo') or ''
        if _photo.startswith('data:'):
            import base64 as _b64
            st.image(_b64.b64decode(_photo.split(',', 1)[1]), width=180)
        elif _photo:
            st.caption("Photo enregistrée — sauvegardez pour l'afficher au prochain chargement.")
        if _photo and st.button("Retirer la photo"):
            st.session_state.user_profile['photo'] = ''
            st.session_state.photo_name = None
            st.rerun()

    with col_id:
        st.markdown("**👤 Informations personnelles**")
        cc1, cc2 = st.columns(2)
        with cc1:
            st.session_state.user_profile['phone'] = st.text_input(
                "Téléphone", value=st.session_state.user_profile.get('phone', ''),
                key="phone_input",
            )
        with cc2:
            st.session_state.user_profile['name'] = st.text_input(
                "Nom complet", value=st.session_state.user_profile['name'],
                key="name_input",
            )
        st.session_state.user_profile['motivations'] = st.text_area(
            "📝 À propos — pitch personnel, motivations",
            value=st.session_state.user_profile.get('motivations', ''),
            height=100, key="motivations_input",
        )
        soft_input = st.text_input(
            "💪 Soft skills (séparées par des virgules)",
            value=', '.join(st.session_state.user_profile.get('soft_skills') or []),
            key="soft_input",
        )
        st.session_state.user_profile['soft_skills'] = [
            s.strip() for s in soft_input.split(',') if s.strip()
        ]
        st.caption("💡 Pensez à « Sauvegarder le profil » dans la barre latérale.")

    # --- Documents ---
    st.markdown("---")
    st.markdown("### 📄 CV & Documents")
    try:
        from components import db as db_pro
        uid_pro = db_pro.get_user_id(
            db_pro.current_user_email(),
            st.session_state.user_profile['name'],
        )
        docs = db_pro.list_documents(uid_pro)
    except Exception as e:
        db_pro, uid_pro, docs = None, None, []
        st.info(f"Documents indisponibles : {e}")

    DOC_LABELS = {
        'cv': 'CV téléversés',
        'lettre': 'Lettres de motivation',
        'cv_genere': "CV générés par l'Agent",
        'mail_relance': 'Mails de relance',
        'prep_entretien': "Préparations d'entretien",
    }
    if docs:
        from collections import OrderedDict
        grouped = OrderedDict()
        for d in docs:
            grouped.setdefault(d['doc_type'], []).append(d)
        for dtype, rows in grouped.items():
            st.markdown(f"**{DOC_LABELS.get(dtype, dtype)} ({len(rows)})**")
            for d in rows:
                with st.expander(
                    f"📄 {d['title'] or 'Document'} — {str(d['created_at'])[:10]}"
                ):
                    if d.get('content'):
                        st.markdown(d['content'])
                    dcol1, dcol2 = st.columns(2)
                    with dcol1:
                        if d.get('content'):
                            st.download_button(
                                "⬇️ Télécharger (.md)",
                                data=d['content'],
                                file_name=(
                                    (d['file_name'] or (d['title'] or 'document'))
                                    .replace(' ', '_') + '.md'
                                ),
                                key=f"dl_{d['document_id']}",
                            )
                    with dcol2:
                        if st.button("🗑️ Supprimer", key=f"del_{d['document_id']}"):
                            db_pro.delete_document(d['document_id'])
                            st.rerun()
    else:
        st.info(
            "Aucun document pour l'instant. Générez une lettre depuis « Recherche "
            "d'offres », un mail de relance ou une préparation d'entretien depuis "
            "« Candidatures », ou un CV adapté ci-dessous."
        )

    # --- CV generator ---
    st.markdown("---")
    st.markdown("### ✨ Générer un CV avec l'Agent")
    gen_title = st.text_input(
        "Poste visé",
        value=', '.join(st.session_state.user_profile.get('target_roles') or [])
        or 'Data Engineer',
    )
    gen_desc = st.text_area("Description de l'offre (optionnel)", height=80)
    if st.button("✨ Générer le CV adapté", type="primary"):
        if not (
            st.session_state.user_profile.get('experiences')
            or st.session_state.user_profile.get('skills')
        ):
            st.warning(
                "Complétez d'abord votre profil (expériences / compétences) dans "
                "la barre latérale, puis réessayez."
            )
        else:
            from components import generators  # lazy import
            with st.spinner("Rédaction du CV…"):
                try:
                    cv_md = generators.generate_tailored_cv(
                        st.session_state.user_profile, gen_title, gen_desc)
                    st.session_state['generated_cv'] = cv_md
                    if uid_pro is not None:
                        db_pro.save_document(
                            uid_pro, 'cv_genere', f"CV adapté — {gen_title}", cv_md)
                        st.success("CV enregistré dans Documents.")
                except Exception as e:
                    st.error(f"Génération impossible : {e}")
    if st.session_state.get('generated_cv'):
        st.markdown(st.session_state['generated_cv'])
        st.download_button(
            "⬇️ Télécharger le CV (.md)",
            data=st.session_state['generated_cv'],
            file_name="cv_genere.md",
            key="dl_gen_cv",
        )

# Footer
st.markdown("---")
st.markdown("""
<div class="app-footer">
    Copilote Recherche d'Emploi · Propulsé par Databricks · Made in France
</div>
""", unsafe_allow_html=True)