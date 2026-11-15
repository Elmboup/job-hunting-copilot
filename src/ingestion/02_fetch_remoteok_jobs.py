# Databricks notebook source
# MAGIC %md
# MAGIC # Ingestion: Fetch RemoteOK Jobs
# MAGIC
# MAGIC Fetches remote job postings from the RemoteOK public API
# MAGIC (https://remoteok.com/api) and persists the raw JSON to a staging
# MAGIC Delta table. No authentication required — RemoteOK only asks for an
# MAGIC honest `User-Agent` header (default python-requests UA is blocked).

# COMMAND ----------

import json
import requests
from datetime import datetime

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

API_URL = "https://remoteok.com/api"

# RemoteOK blocks the default python-requests User-Agent — declare who we are.
HEADERS = {
    "User-Agent": "job-hunting-copilot/1.0 (+https://github.com; personal job search project)",
    "Accept": "application/json",
}

# Keep only postings relevant to the app's data-oriented audience.
# Matched against lowercased position + tags.
KEYWORDS = [
    "data",
    "python",
    "machine learning",
    " ml",
    " ai",
    "analytics",
    "sql",
    "spark",
    "engineer",
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch Jobs Function

# COMMAND ----------

def fetch_remoteok_jobs():
    """
    Fetch all jobs from the RemoteOK API (single request, no pagination —
    the endpoint returns the full recent feed).

    Returns:
        List of job dictionaries (the first array element is a legal notice
        and is dropped).
    """
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=15)

        if response.status_code == 429:
            print("  ⚠ Rate limit reached — try again later")
            return []
        if response.status_code != 200:
            print(f"  ✗ Error {response.status_code}: {response.text[:200]}")
            return []

        data = response.json()
        # Element 0 is a legal/ToS notice, not a job.
        jobs = [item for item in data[1:] if isinstance(item, dict) and item.get("slug")]
        print(f"  ✓ Fetched {len(jobs)} jobs from RemoteOK")
        return jobs

    except Exception as e:
        print(f"  ✗ Exception: {str(e)}")
        return []


def is_relevant(job):
    """True if the position title or tags match our data-oriented keywords."""
    text = " ".join(
        [str(job.get("position") or "")] + [str(t) for t in (job.get("tags") or [])]
    ).lower()
    return any(k in text for k in KEYWORDS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch and Filter Jobs

# COMMAND ----------

all_jobs = fetch_remoteok_jobs()
data_jobs = [job for job in all_jobs if is_relevant(job)]

print(f"\n{'='*50}")
print(f"✅ Total RemoteOK jobs: {len(all_jobs)}")
print(f"✅ Data-relevant jobs: {len(data_jobs)}")
print(f"{'='*50}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Preview Sample Jobs

# COMMAND ----------

if data_jobs:
    print("Sample jobs:\n")
    for i, job in enumerate(data_jobs[:3], 1):
        print(f"{i}. {job.get('position', 'N/A')}")
        print(f"   Company: {job.get('company', 'N/A')}")
        print(f"   Location: {job.get('location', 'N/A')}")
        print(f"   Salary: {job.get('salary_min', 'N/A')} - {job.get('salary_max', 'N/A')} USD")
        print(f"   Tags: {', '.join(job.get('tags') or [])[:80]}")
        print(f"   URL: {str(job.get('url', 'N/A'))[:60]}...")
        print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Raw Jobs to Staging Table

# COMMAND ----------

# Persist raw JSON to its own staging table (RemoteOK's schema differs from
# Adzuna's, so it is kept separate from staging_raw_jobs; 03_transform_jobs.py
# currently expects the Adzuna shape and stays untouched).
CATALOG_SCHEMA = "main.job_hunting"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG_SCHEMA}")

raw_df = spark.createDataFrame(
    [(i, json.dumps(job)) for i, job in enumerate(data_jobs)],
    "fetch_index INT, raw_json STRING",
)
raw_df.write.mode("overwrite").option("mergeSchema", "true").saveAsTable(
    f"{CATALOG_SCHEMA}.staging_raw_jobs_remoteok"
)

print(f"✅ Saved {len(data_jobs)} raw jobs to {CATALOG_SCHEMA}.staging_raw_jobs_remoteok")
print(f"   Fetched at {datetime.now().isoformat(timespec='seconds')}")