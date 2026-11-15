"""Lakebase Postgres persistence — profiles, skills, and application tracking.

Connection model (Databricks Apps + Lakebase):
- app.yaml attaches the Lakebase database as a `postgres` app resource, which
  injects PGHOST / PGPORT / PGDATABASE / PGUSER / PGSSLMODE into the runtime,
  plus LAKEBASE_ENDPOINT (declared via `valueFrom: postgres`) — the endpoint
  resource path that w.postgres.generate_database_credential needs.
- OAuth tokens expire after ~1 hour: a fresh credential is minted for every
  new connection (never cached longer than the connection itself).
- The app's service principal has CAN_CONNECT_AND_CREATE: it can create new
  objects but cannot access existing schemas, so the app owns its own schema
  (app_data) and creates its tables on first use.
"""

import json
import os
from contextlib import contextmanager

import psycopg

from components.auth import get_workspace_client

SCHEMA = "app_data"

# Endpoint resource path (verified via postgres list-endpoints). LAKEBASE_ENDPOINT
# is injected from app.yaml (env: valueFrom: postgres) once the Lakebase resource
# is attached to the app; this fallback keeps connections working if the builder
# does not propagate that env var.
_DEFAULT_ENDPOINT = "projects/job-hunting-copilot/branches/production/endpoints/primary"

APPLICATION_STATUSES = ["En cours", "Entretien", "Offre", "Rejeté"]

# Recruiter Intelligence — ESN recruitment tracking vocabulary
PROCESS_STAGES = [
    "Prospect", "Premier contact", "Entretien RH", "Entretien technique",
    "Business Manager", "Présentation client", "Entretien client",
    "Offre", "Accepté", "Rejeté",
]
PROCESS_STATUSES = ["Actif", "En pause", "Abandonné", "Conclu"]
RECRUITMENT_TYPES = [
    "Mission existante", "Vivier", "Recrutement interne",
    "Opportunité future", "Pré-vente", "Accord-cadre",
]
CONTACT_ROLES = [
    "Recruteur", "Talent Acquisition", "Business Manager",
    "Delivery Manager", "Practice Lead", "Autre",
]
INTERACTION_TYPES = ["Appel", "Email", "Teams", "LinkedIn", "Autre"]
INTERACTION_DIRECTIONS = ["envoyé", "reçu", "mutuel"]

# Recruiter Intelligence — metric ownership
# Objective metrics: AI computes a value the user may override (a row in
# metric_overrides = manual lock; no row = automatic mode).
# Subjective metrics: user-owned, they exist ONLY in metric_overrides —
# the AI may suggest values but never writes them without a user action.
OBJECTIVE_METRICS = ["mission_fit", "communication_score", "offer_probability"]
SUBJECTIVE_METRICS = ["attractiveness", "interest_level", "priority", "personal_notes"]

_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};
CREATE TABLE IF NOT EXISTS {SCHEMA}.users (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.profiles (
    profile_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES {SCHEMA}.users(user_id),
    name VARCHAR(255),
    experience TEXT,
    target_roles TEXT[],
    location_preferences TEXT[],
    remote_preference VARCHAR(50),
    contract_preference VARCHAR(50),
    salary_min INTEGER,
    salary_max INTEGER,
    resume_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.skills (
    skill_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    skill_name VARCHAR(255),
    source VARCHAR(20) DEFAULT 'manual',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.applications (
    application_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    job_id VARCHAR(255) NOT NULL,
    title VARCHAR(500),
    company VARCHAR(255),
    location VARCHAR(255),
    contract_type_fr VARCHAR(50),
    remote_type VARCHAR(50),
    salary_min INTEGER,
    salary_max INTEGER,
    url TEXT,
    match_score DOUBLE PRECISION,
    status VARCHAR(50) DEFAULT 'En cours',
    notes TEXT,
    applied_date DATE,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, job_id)
);

-- Apec-style structured profile (added on existing deployments too)
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS current_title VARCHAR(255);
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS experiences JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS education JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS languages JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS certifications JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS phone VARCHAR(50);
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS soft_skills TEXT[] DEFAULT '{{}}';
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS motivations TEXT;
ALTER TABLE {SCHEMA}.profiles ADD COLUMN IF NOT EXISTS photo TEXT;

-- Career documents: uploaded CVs, agent-generated letters/CVs, follow-up
-- emails, interview prep guides.
CREATE TABLE IF NOT EXISTS {SCHEMA}.documents (
    document_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    doc_type VARCHAR(50) NOT NULL,
    title VARCHAR(500),
    content TEXT,
    file_name VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Recruiter Intelligence: ESN recruitment tracking
CREATE TABLE IF NOT EXISTS {SCHEMA}.consulting_companies (
    company_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    name VARCHAR(200) NOT NULL,
    specialization VARCHAR(500),
    sectors TEXT[] DEFAULT '{{}}',
    technologies TEXT[] DEFAULT '{{}}',
    salary_min INTEGER,
    salary_max INTEGER,
    remote_policy VARCHAR(100),
    hiring_model VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.contacts (
    contact_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    company_id INTEGER NOT NULL REFERENCES {SCHEMA}.consulting_companies(company_id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    role VARCHAR(100),
    email VARCHAR(255),
    linkedin VARCHAR(500),
    phone VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.recruitment_processes (
    process_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    company_id INTEGER NOT NULL REFERENCES {SCHEMA}.consulting_companies(company_id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES {SCHEMA}.contacts(contact_id) ON DELETE SET NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'Prospect',
    status VARCHAR(30) NOT NULL DEFAULT 'Actif',
    recruitment_type VARCHAR(50),
    expected_salary INTEGER,
    mission TEXT,
    technologies TEXT[] DEFAULT '{{}}',
    client VARCHAR(200),
    location VARCHAR(100),
    remote VARCHAR(50),
    next_followup DATE,
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS {SCHEMA}.interactions (
    interaction_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    process_id INTEGER REFERENCES {SCHEMA}.recruitment_processes(process_id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES {SCHEMA}.contacts(contact_id) ON DELETE SET NULL,
    interaction_date DATE NOT NULL DEFAULT CURRENT_DATE,
    interaction_type VARCHAR(30) NOT NULL,
    direction VARCHAR(10),
    summary TEXT,
    action_items TEXT,
    sentiment VARCHAR(20),
    next_followup DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Metric overrides: manual values set by the user.
-- Objective metrics (mission_fit, communication_score, offer_probability,
-- value on a 0-100 scale) fall back to the AI heuristic when no row exists;
-- a row = manual lock until the user deletes it (switch back to Auto).
-- Subjective metrics (attractiveness, interest_level, priority on 0-100;
-- personal_notes as text) live ONLY here — user-owned; AI suggestions are
-- applied solely through an explicit user action in the UI, and `rationale`
-- keeps the explanation attached to the value.
CREATE TABLE IF NOT EXISTS {SCHEMA}.metric_overrides (
    override_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES {SCHEMA}.users(user_id),
    entity_type VARCHAR(20) NOT NULL,
    entity_id INTEGER NOT NULL,
    metric_key VARCHAR(50) NOT NULL,
    value NUMERIC,
    value_text TEXT,
    rationale TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, entity_type, entity_id, metric_key)
);
"""

_initialized = False


@contextmanager
def lakebase_connection():
    """Open a short-lived Lakebase connection with a freshly minted OAuth token."""
    endpoint = os.environ.get("LAKEBASE_ENDPOINT") or _DEFAULT_ENDPOINT
    w = get_workspace_client()
    cred = w.postgres.generate_database_credential(endpoint=endpoint)
    conn = psycopg.connect(
        host=os.environ["PGHOST"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        port=int(os.environ.get("PGPORT", "5432")),
        password=cred.token,
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )
    try:
        _ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn):
    """Create the app-owned schema and tables once per app process."""
    global _initialized
    if not _initialized:
        with conn.cursor() as cur:
            cur.execute(_DDL)
        conn.commit()
        _initialized = True


def current_user_email():
    """Identity of the logged-in user (Apps gateway header), with a local fallback."""
    try:
        import streamlit as st

        email = (st.context.headers.get("X-Forwarded-Email") or "").strip()
        if email:
            return email
    except Exception:
        pass
    return "local@job-hunting.app"


def get_user_id(email, name=None):
    """Return the user's id, creating the row on first use (idempotent)."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.users (email, name)
                VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE
                SET name = COALESCE(EXCLUDED.name, {SCHEMA}.users.name)
                RETURNING user_id
                """,
                (email, name or "Utilisateur"),
            )
            user_id = cur.fetchone()[0]
        conn.commit()
        return user_id


def save_profile(user_id, profile, skills, source="manual"):
    """Upsert the profile and replace the skills list."""
    with lakebase_connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.profiles (
                        user_id, name, experience, target_roles,
                        location_preferences, remote_preference,
                        contract_preference, resume_text,
                        summary, current_title,
                        experiences, education, languages, certifications,
                        phone, soft_skills, motivations, photo
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        experience = EXCLUDED.experience,
                        target_roles = EXCLUDED.target_roles,
                        location_preferences = EXCLUDED.location_preferences,
                        remote_preference = EXCLUDED.remote_preference,
                        contract_preference = EXCLUDED.contract_preference,
                        resume_text = EXCLUDED.resume_text,
                        summary = EXCLUDED.summary,
                        current_title = EXCLUDED.current_title,
                        experiences = EXCLUDED.experiences,
                        education = EXCLUDED.education,
                        languages = EXCLUDED.languages,
                        certifications = EXCLUDED.certifications,
                        phone = EXCLUDED.phone,
                        soft_skills = EXCLUDED.soft_skills,
                        motivations = EXCLUDED.motivations,
                        photo = EXCLUDED.photo,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        user_id,
                        profile.get("name"),
                        profile.get("experience"),
                        profile.get("target_roles") or [],
                        profile.get("location_preferences") or [],
                        profile.get("remote_preference"),
                        profile.get("contract_preference"),
                        profile.get("resume_text"),
                        profile.get("summary"),
                        profile.get("current_title"),
                        json.dumps(profile.get("experiences") or []),
                        json.dumps(profile.get("education") or []),
                        json.dumps(profile.get("languages") or []),
                        json.dumps(profile.get("certifications") or []),
                        profile.get("phone"),
                        profile.get("soft_skills") or [],
                        profile.get("motivations"),
                        profile.get("photo"),
                    ),
                )
                cur.execute(
                    f"DELETE FROM {SCHEMA}.skills WHERE user_id = %s", (user_id,)
                )
                for skill in skills:
                    if skill and skill.strip():
                        cur.execute(
                            f"INSERT INTO {SCHEMA}.skills (user_id, skill_name, source) "
                            "VALUES (%s, %s, %s)",
                            (user_id, skill.strip(), source),
                        )


def load_profile(email):
    """Load the saved profile + skills for an email, or None if never saved."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT p.name, p.experience, p.target_roles, p.location_preferences,
                       p.remote_preference, p.contract_preference, p.resume_text,
                       p.summary, p.current_title,
                       p.experiences, p.education, p.languages, p.certifications,
                       p.phone, p.soft_skills, p.motivations, p.photo,
                       COALESCE(
                           ARRAY_AGG(s.skill_name) FILTER (WHERE s.skill_name IS NOT NULL),
                           '{{}}'
                       ) AS skills
                FROM {SCHEMA}.profiles p
                JOIN {SCHEMA}.users u ON u.user_id = p.user_id
                LEFT JOIN {SCHEMA}.skills s ON s.user_id = p.user_id
                WHERE u.email = %s
                GROUP BY p.profile_id, p.name, p.experience, p.target_roles,
                         p.location_preferences, p.remote_preference,
                         p.contract_preference, p.resume_text, p.summary,
                         p.current_title, p.experiences, p.education,
                         p.languages, p.certifications, p.phone, p.soft_skills,
                         p.motivations, p.photo
                """,
                (email,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            columns = [d.name for d in cur.description]
            return dict(zip(columns, row))


def save_application(user_id, job):
    """Track a job posting. Returns True when newly saved, False when updated."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.applications (
                    user_id, job_id, title, company, location, contract_type_fr,
                    remote_type, salary_min, salary_max, url, match_score,
                    status, applied_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
                ON CONFLICT (user_id, job_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    company = EXCLUDED.company,
                    location = EXCLUDED.location,
                    contract_type_fr = EXCLUDED.contract_type_fr,
                    remote_type = EXCLUDED.remote_type,
                    salary_min = EXCLUDED.salary_min,
                    salary_max = EXCLUDED.salary_max,
                    url = EXCLUDED.url,
                    match_score = EXCLUDED.match_score,
                    last_updated = CURRENT_TIMESTAMP
                RETURNING (xmax = 0) AS is_new
                """,
                (
                    user_id,
                    str(job.get("job_id")),
                    job.get("title"),
                    job.get("company"),
                    job.get("location"),
                    job.get("contract_type_fr"),
                    job.get("remote_type"),
                    job.get("salary_min"),
                    job.get("salary_max"),
                    job.get("url"),
                    job.get("match_score"),
                    job.get("status", "En cours"),
                ),
            )
            is_new = cur.fetchone()[0]
        conn.commit()
        return bool(is_new)


def list_applications(user_id):
    """All tracked applications for a user, most recently updated first."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT application_id, job_id, title, company, location,
                       contract_type_fr, remote_type, salary_min, salary_max,
                       url, match_score, status, notes, applied_date, last_updated
                FROM {SCHEMA}.applications
                WHERE user_id = %s
                ORDER BY last_updated DESC
                """,
                (user_id,),
            )
            columns = [d.name for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def update_application(application_id, status=None, notes=None):
    """Update an application's status and/or notes (column names whitelisted)."""
    sets, params = [], []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if notes is not None:
        sets.append("notes = %s")
        params.append(notes)
    if not sets:
        return
    sets.append("last_updated = CURRENT_TIMESTAMP")
    params.append(application_id)
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.applications SET {', '.join(sets)} "
                "WHERE application_id = %s",
                params,
            )
        conn.commit()


def save_document(user_id, doc_type, title, content, file_name=None):
    """Store a career document (cv, lettre, cv_genere, mail_relance,
    prep_entretien...). Returns the new document id."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.documents (user_id, doc_type, title, content, file_name)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING document_id
                """,
                (user_id, doc_type, title, content, file_name),
            )
            doc_id = cur.fetchone()[0]
        conn.commit()
        return doc_id


def list_documents(user_id, doc_type=None):
    """Documents for a user, newest first; optionally filtered by type."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            if doc_type:
                cur.execute(
                    f"""
                    SELECT document_id, doc_type, title, content, file_name, created_at
                    FROM {SCHEMA}.documents
                    WHERE user_id = %s AND doc_type = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id, doc_type),
                )
            else:
                cur.execute(
                    f"""
                    SELECT document_id, doc_type, title, content, file_name, created_at
                    FROM {SCHEMA}.documents
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user_id,),
                )
            columns = [d.name for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def delete_document(document_id):
    """Remove a stored document."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {SCHEMA}.documents WHERE document_id = %s",
                (document_id,),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Recruiter Intelligence — ESN recruitment tracking
# ---------------------------------------------------------------------------

def _fetch_dicts(cur, sql, params):
    """Run a SELECT and return dict rows (shared by the recruiting queries)."""
    cur.execute(sql, params)
    columns = [d.name for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def list_consulting_companies(user_id):
    """ESN companies tracked by the user, alphabetical."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            return _fetch_dicts(
                cur,
                f"""
                SELECT company_id, name, specialization, sectors, technologies,
                       salary_min, salary_max, remote_policy, hiring_model, notes,
                       created_at
                FROM {SCHEMA}.consulting_companies
                WHERE user_id = %s
                ORDER BY name
                """,
                (user_id,),
            )


def save_consulting_company(user_id, company):
    """Upsert an ESN company by name. Returns the company id."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.consulting_companies (
                    user_id, name, specialization, sectors, technologies,
                    salary_min, salary_max, remote_policy, hiring_model, notes
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, name) DO UPDATE SET
                    specialization = EXCLUDED.specialization,
                    sectors = EXCLUDED.sectors,
                    technologies = EXCLUDED.technologies,
                    salary_min = EXCLUDED.salary_min,
                    salary_max = EXCLUDED.salary_max,
                    remote_policy = EXCLUDED.remote_policy,
                    hiring_model = EXCLUDED.hiring_model,
                    notes = EXCLUDED.notes
                RETURNING company_id
                """,
                (
                    user_id,
                    company.get("name"),
                    company.get("specialization"),
                    company.get("sectors") or [],
                    company.get("technologies") or [],
                    company.get("salary_min"),
                    company.get("salary_max"),
                    company.get("remote_policy"),
                    company.get("hiring_model"),
                    company.get("notes"),
                ),
            )
            company_id = cur.fetchone()[0]
        conn.commit()
        return company_id


def delete_consulting_company(company_id):
    """Remove a company (cascades to its contacts and processes)."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {SCHEMA}.consulting_companies WHERE company_id = %s",
                (company_id,),
            )
        conn.commit()


def list_contacts(user_id, company_id=None):
    """Recruiter contacts, optionally filtered by company."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            if company_id:
                return _fetch_dicts(
                    cur,
                    f"""
                    SELECT contact_id, company_id, name, role, email, linkedin,
                           phone, notes, created_at
                    FROM {SCHEMA}.contacts
                    WHERE user_id = %s AND company_id = %s
                    ORDER BY name
                    """,
                    (user_id, company_id),
                )
            return _fetch_dicts(
                cur,
                f"""
                SELECT contact_id, company_id, name, role, email, linkedin,
                       phone, notes, created_at
                FROM {SCHEMA}.contacts
                WHERE user_id = %s
                ORDER BY name
                """,
                (user_id,),
            )


def save_contact(user_id, contact):
    """Insert or update a contact by contact_id. Returns the contact id."""
    contact_id = contact.get("contact_id")
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            if contact_id:
                cur.execute(
                    f"""
                    UPDATE {SCHEMA}.contacts SET
                        company_id = %s, name = %s, role = %s, email = %s,
                        linkedin = %s, phone = %s, notes = %s
                    WHERE contact_id = %s AND user_id = %s
                    RETURNING contact_id
                    """,
                    (
                        contact.get("company_id"),
                        contact.get("name"),
                        contact.get("role"),
                        contact.get("email"),
                        contact.get("linkedin"),
                        contact.get("phone"),
                        contact.get("notes"),
                        contact_id,
                        user_id,
                    ),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.contacts (
                        user_id, company_id, name, role, email, linkedin, phone, notes
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING contact_id
                    """,
                    (
                        user_id,
                        contact.get("company_id"),
                        contact.get("name"),
                        contact.get("role"),
                        contact.get("email"),
                        contact.get("linkedin"),
                        contact.get("phone"),
                        contact.get("notes"),
                    ),
                )
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def delete_contact(contact_id):
    """Remove a contact."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {SCHEMA}.contacts WHERE contact_id = %s",
                (contact_id,),
            )
        conn.commit()


def list_processes(user_id, active_only=False):
    """Recruitment processes, most recently updated first."""
    where = "AND status = 'Actif'" if active_only else ""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            return _fetch_dicts(
                cur,
                f"""
                SELECT process_id, company_id, contact_id, stage, status,
                       recruitment_type, expected_salary, mission, technologies,
                       client, location, remote, next_followup, comments,
                       created_at, updated_at
                FROM {SCHEMA}.recruitment_processes
                WHERE user_id = %s {where}
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )


def save_process(user_id, process):
    """Insert or update a recruitment process by process_id. Returns its id."""
    process_id = process.get("process_id")
    fields = (
        process.get("company_id"),
        process.get("contact_id"),
        process.get("stage") or "Prospect",
        process.get("status") or "Actif",
        process.get("recruitment_type"),
        process.get("expected_salary"),
        process.get("mission"),
        process.get("technologies") or [],
        process.get("client"),
        process.get("location"),
        process.get("remote"),
        process.get("next_followup"),
        process.get("comments"),
    )
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            if process_id:
                cur.execute(
                    f"""
                    UPDATE {SCHEMA}.recruitment_processes SET
                        company_id = %s, contact_id = %s, stage = %s, status = %s,
                        recruitment_type = %s, expected_salary = %s, mission = %s,
                        technologies = %s, client = %s, location = %s, remote = %s,
                        next_followup = %s, comments = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE process_id = %s AND user_id = %s
                    RETURNING process_id
                    """,
                    fields + (process_id, user_id),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.recruitment_processes (
                        user_id, company_id, contact_id, stage, status,
                        recruitment_type, expected_salary, mission, technologies,
                        client, location, remote, next_followup, comments
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING process_id
                    """,
                    (user_id,) + fields,
                )
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def update_process(process_id, **fields):
    """Patch selected process columns (names whitelisted)."""
    allowed = {
        "stage", "status", "recruitment_type", "expected_salary", "mission",
        "technologies", "client", "location", "remote", "next_followup",
        "comments", "contact_id",
    }
    sets, params = [], []
    for key, value in fields.items():
        if key in allowed and value is not None:
            sets.append(f"{key} = %s")
            params.append(value)
    if not sets:
        return
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(process_id)
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.recruitment_processes SET {', '.join(sets)} "
                "WHERE process_id = %s",
                params,
            )
        conn.commit()


def delete_process(process_id):
    """Remove a process (cascades to its interactions)."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {SCHEMA}.recruitment_processes WHERE process_id = %s",
                (process_id,),
            )
        conn.commit()


def list_interactions(user_id, process_id=None, contact_id=None):
    """Interactions, newest first; filterable by process or contact."""
    where, params = ["user_id = %s"], [user_id]
    if process_id is not None:
        where.append("process_id = %s")
        params.append(process_id)
    if contact_id is not None:
        where.append("contact_id = %s")
        params.append(contact_id)
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            return _fetch_dicts(
                cur,
                f"""
                SELECT interaction_id, process_id, contact_id, interaction_date,
                       interaction_type, direction, summary, action_items,
                       sentiment, next_followup, created_at
                FROM {SCHEMA}.interactions
                WHERE {' AND '.join(where)}
                ORDER BY interaction_date DESC, created_at DESC
                """,
                tuple(params),
            )


def save_interaction(user_id, interaction):
    """Insert or update an interaction by interaction_id. Returns its id."""
    interaction_id = interaction.get("interaction_id")
    fields = (
        interaction.get("process_id"),
        interaction.get("contact_id"),
        interaction.get("interaction_date"),
        interaction.get("interaction_type") or "Email",
        interaction.get("direction") or "envoyé",
        interaction.get("summary"),
        interaction.get("action_items"),
        interaction.get("sentiment"),
        interaction.get("next_followup"),
    )
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            if interaction_id:
                cur.execute(
                    f"""
                    UPDATE {SCHEMA}.interactions SET
                        process_id = %s, contact_id = %s, interaction_date = %s,
                        interaction_type = %s, direction = %s, summary = %s,
                        action_items = %s, sentiment = %s, next_followup = %s
                    WHERE interaction_id = %s AND user_id = %s
                    RETURNING interaction_id
                    """,
                    fields + (interaction_id, user_id),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.interactions (
                        user_id, process_id, contact_id, interaction_date,
                        interaction_type, direction, summary, action_items,
                        sentiment, next_followup
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING interaction_id
                    """,
                    (user_id,) + fields,
                )
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id


def delete_interaction(interaction_id):
    """Remove an interaction."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {SCHEMA}.interactions WHERE interaction_id = %s",
                (interaction_id,),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Recruiter Intelligence — metric overrides (manual / user-owned values)
# ---------------------------------------------------------------------------

def list_metric_overrides(user_id):
    """All manual metric overrides (objective locks + subjective values)."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            return _fetch_dicts(
                cur,
                f"""
                SELECT override_id, entity_type, entity_id, metric_key,
                       value, value_text, rationale, updated_at
                FROM {SCHEMA}.metric_overrides
                WHERE user_id = %s
                """,
                (user_id,),
            )


def save_metric_override(user_id, override):
    """Upsert one metric value by (entity_type, entity_id, metric_key)."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.metric_overrides (
                    user_id, entity_type, entity_id, metric_key,
                    value, value_text, rationale
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, entity_type, entity_id, metric_key) DO UPDATE SET
                    value = EXCLUDED.value,
                    value_text = EXCLUDED.value_text,
                    rationale = EXCLUDED.rationale,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING override_id
                """,
                (
                    user_id,
                    override.get("entity_type"),
                    override.get("entity_id"),
                    override.get("metric_key"),
                    override.get("value"),
                    override.get("value_text"),
                    override.get("rationale"),
                ),
            )
            override_id = cur.fetchone()[0]
        conn.commit()
        return override_id


def delete_metric_override(user_id, entity_type, entity_id, metric_key):
    """Remove a manual override — the metric returns to automatic mode."""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                DELETE FROM {SCHEMA}.metric_overrides
                WHERE user_id = %s AND entity_type = %s AND entity_id = %s
                  AND metric_key = %s
                """,
                (user_id, entity_type, entity_id, metric_key),
            )
        conn.commit()
