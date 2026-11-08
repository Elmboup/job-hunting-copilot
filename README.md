# job-hunting-copilot

A personal job-hunting copilot on Databricks: it ingests job postings from
**Adzuna** (France) and **RemoteOK**, stores them in **Lakebase Postgres**,
embeds descriptions into **Vector Search**, and exposes an agent + app that
match postings to your profile and track your applications.

## Repository structure

```text
job-hunting-copilot/
├── README.md               # this file
├── .gitignore              # excludes legacy workspace folders, secrets, local state
├── databricks.yml          # Declarative Automation Bundle (jobs, schedules)
├── src/
│   ├── setup/              # one-time setup: secrets, Lakebase schema, API tests
│   ├── ingestion/          # fetch → transform → load pipelines
│   ├── embeddings/          # embeddings + Vector Search index
│   ├── agent/              # UC functions and the copilot agent
│   ├── workflows/          # notebooks run by the scheduled jobs
│   ├── testing/            # data quality, agent & search evaluation
│   └── analytics/          # SQL notebooks for user/market/agent metrics
└── app/                    # Databricks App (UI): entry point + components
```

## Setup (already done in the workspace)

1. **Secrets** — Adzuna credentials stored in the `job-hunting` scope
   (see `src/setup/00_create_secrets.py`; App ID is 8 hex chars, API key 32).
2. **Lakebase** — project `job-hunting-copilot`, production branch, database
   `databricks_postgres`. Schema: users, profiles, skills, job_postings,
   applications (+ indexes). Created by `src/setup/01_create_lakebase_schema.py`.
   ⚠️ Connect with **pg8000** (pure Python). psycopg-binary crashes the
   serverless kernel on import — do not use it in this workspace.
3. **APIs** — verified working (Adzuna 200, RemoteOK 200) via
   `src/setup/02_test_apis.py`.

## Version control

The files in `src/` and `app/` are Git-ready source files (notebook source
format: `.py` files open as notebooks in a Git folder). To put the project
under version control:

1. Create an empty repository on your Git provider (GitHub/GitLab/Azure DevOps).
2. In Databricks: **Repos → Add repo**, clone it (Git credentials are set up
   once, per provider).
3. Copy the contents of this folder into the repo and commit + push from the
   repo UI — or push from a local clone after downloading the folder.

Alternatively, deploy the scheduled jobs without Git:

```bash
databricks bundle validate
databricks bundle deploy
```

## Status

* [x] Secrets, Lakebase schema, API tests
* [ ] Ingestion pipelines (`src/ingestion/`)
* [ ] Embeddings + Vector Search (`src/embeddings/`)
* [ ] Agent (`src/agent/`)
* [ ] App UI (`app/`)
* [ ] Schedules live (`databricks.yml` — jobs created paused)