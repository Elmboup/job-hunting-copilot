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

import os
from contextlib import contextmanager

import psycopg

from components.auth import get_workspace_client

SCHEMA = "app_data"

APPLICATION_STATUSES = ["En cours", "Entretien", "Offre", "Rejeté"]

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
"""

_initialized = False


@contextmanager
def lakebase_connection():
    """Open a short-lived Lakebase connection with a freshly minted OAuth token."""
    endpoint = os.environ.get("LAKEBASE_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "LAKEBASE_ENDPOINT n'est pas défini — la base Lakebase doit être "
            "attachée à l'app (resource `postgres` dans app.yaml) puis l'app "
            "redéployée."
        )
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
                        contract_preference, resume_text
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        experience = EXCLUDED.experience,
                        target_roles = EXCLUDED.target_roles,
                        location_preferences = EXCLUDED.location_preferences,
                        remote_preference = EXCLUDED.remote_preference,
                        contract_preference = EXCLUDED.contract_preference,
                        resume_text = EXCLUDED.resume_text,
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
                         p.contract_preference, p.resume_text
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
