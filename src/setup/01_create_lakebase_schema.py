# Databricks notebook source
# DBTITLE 1,Install Postgres driver
# MAGIC %pip install pg8000

# COMMAND ----------

# DBTITLE 1,Cell 1
# Databricks notebook source
# MAGIC %md
# MAGIC # Setup: Create Lakebase Database Schema
# MAGIC 
# MAGIC Creates the schema directly in **Lakebase Postgres**. The DDL is Postgres dialect
# MAGIC (SERIAL, TEXT[], ON CONFLICT ...), so it cannot be run as a notebook SQL cell — those
# MAGIC execute on Spark, which rejects these types (the previous "Unsupported data type SERIAL" error).
# MAGIC 
# MAGIC This cell:
# MAGIC 1. Finds the Lakebase project `job-hunting-copilot` via the Databricks SDK
# MAGIC 2. Connects to its production branch with a short-lived OAuth credential (pg8000, a pure-Python Postgres driver)
# MAGIC 3. Executes the DDL below, one statement at a time
# MAGIC 
# MAGIC If the project does not exist yet: go to **Lakebase** in the Databricks UI, create a
# MAGIC project named `job-hunting-copilot`, then re-run this cell.

# COMMAND ----------

from databricks.sdk import WorkspaceClient

PROJECT_NAME = "job-hunting-copilot"

w = WorkspaceClient()

# --- 1. Find the Lakebase project (create it from the Lakebase UI if missing) ---
project = next(
    (
        p
        for p in w.postgres.list_projects()
        if (p.spec.display_name if p.spec else None) == PROJECT_NAME
        or p.name == f"projects/{PROJECT_NAME}"
    ),
    None,
)

if project is None:
    print(f"❌ Lakebase project '{PROJECT_NAME}' not found.")
    print("   1. Go to Lakebase in the Databricks UI")
    print("   2. Create a project named job-hunting-copilot")
    print("   3. Re-run this cell")
else:
    # --- 2. Production branch, its read-write endpoint, and the database ---
    branch = next(
        (
            b
            for b in w.postgres.list_branches(parent=project.name)
            if b.name.endswith("/branches/production")
        ),
        None,
    ) or next(w.postgres.list_branches(parent=project.name))

    endpoints = list(w.postgres.list_endpoints(parent=branch.name))
    endpoint = next(
        (e for e in endpoints if e.spec and "READ_WRITE" in str(e.spec.endpoint_type)),
        endpoints[0],
    )

    # (the actual database name is discovered below after connecting — the resource id
    # is not necessarily the database name inside the Postgres instance)

    host = endpoint.status.hosts.host if (endpoint.status and endpoint.status.hosts) else None
    if not host:
        state = endpoint.status.current_state if endpoint.status else "UNKNOWN"
        raise RuntimeError(f"Endpoint {endpoint.name} is not ready yet (state: {state}). Re-run this cell once it is ACTIVE.")

    token = w.postgres.generate_database_credential(endpoint=endpoint.name).token
    username = w.current_user.me().user_name

    # Postgres driver (pure Python — no compiled extensions) — run the %pip install cell above first
    import pg8000.native

    # Discover the actual database name: connect to the system "postgres" database and
    # list what really exists (e.g. "databricks-postgres" resource id → "postgres" db).
    _sys = pg8000.native.Connection(
        user=username, host=host, database="postgres", password=token, ssl_context=True
    )
    _available = [r[0] for r in _sys.run("SELECT datname FROM pg_database WHERE datistemplate = false")]
    _sys.close()
    dbname = (
        "databricks_postgres"
        if "databricks_postgres" in _available
        else next((d for d in _available if d != "postgres"), "postgres")
    )

    # --- 3. Schema DDL (Postgres dialect) — executed one statement at a time ---
    DDL_STATEMENTS = [
        """CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        """CREATE TABLE IF NOT EXISTS profiles (
    profile_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    target_roles TEXT[],
    location_preferences TEXT[],
    remote_preference VARCHAR(50),
    salary_min INTEGER,
    salary_max INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        """CREATE TABLE IF NOT EXISTS skills (
    skill_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    skill_name VARCHAR(255),
    proficiency_level VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        """CREATE TABLE IF NOT EXISTS job_postings (
    job_id VARCHAR(255) PRIMARY KEY,
    source VARCHAR(50),
    title VARCHAR(500),
    company VARCHAR(255),
    location VARCHAR(255),
    country VARCHAR(100),
    remote_type VARCHAR(50),
    description TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency VARCHAR(10),
    url TEXT,
    posted_date TIMESTAMP,
    contract_type_fr VARCHAR(50),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
        """CREATE TABLE IF NOT EXISTS applications (
    application_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    job_id VARCHAR(255) REFERENCES job_postings(job_id),
    status VARCHAR(50),
    applied_date TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
)""",
        "CREATE INDEX IF NOT EXISTS idx_job_postings_posted_date ON job_postings(posted_date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_applications_user_status ON applications(user_id, status)",
        # Insert test user (edit email/name to yours)
        """INSERT INTO users (email, name)
VALUES ('el.hadji.mboup.pro.email@gmail.com', 'El Hadji')
ON CONFLICT (email) DO NOTHING""",
    ]

    # --- 4. Execute against Lakebase Postgres ---
    conn = pg8000.native.Connection(
        user=username, host=host, database=dbname, password=token, ssl_context=True
    )
    try:
        for stmt in DDL_STATEMENTS:
            conn.run(stmt)
    finally:
        conn.close()

    print(f"✅ Schema created in Lakebase Postgres (project {PROJECT_NAME}, database {dbname}).")