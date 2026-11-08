# Databricks notebook source
# MAGIC %md
# MAGIC # Data Ingestion: Fetch Jobs from Adzuna France
# MAGIC 
# MAGIC This notebook fetches job postings from Adzuna API for French cities.

# COMMAND ----------

import requests
from datetime import datetime
import json

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# API credentials
ADZUNA_APP_ID = dbutils.secrets.get(scope="job-hunting", key="adzuna-app-id")
ADZUNA_API_KEY = dbutils.secrets.get(scope="job-hunting", key="adzuna-api-key")

# French cities to search
FRENCH_CITIES = [
    'Paris', 'Lyon', 'Marseille', 'Toulouse', 'Nice',
    'Nantes', 'Strasbourg', 'Montpellier', 'Bordeaux', 'Lille'
]

# Search keywords (French)
KEYWORDS = [
    'data engineer',
    'ingénieur data',
    'développeur python',
    'data scientist'
]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch Jobs Function

# COMMAND ----------

def fetch_adzuna_jobs(country='fr', keywords='data engineer', location='Paris', pages=3):
    """
    Fetch jobs from Adzuna API
    
    Args:
        country: Country code (fr for France)
        keywords: Search keywords
        location: City name
        pages: Number of pages to fetch (50 results per page)
    
    Returns:
        List of job dictionaries
    """
    jobs = []
    
    for page in range(1, pages + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            'app_id': ADZUNA_APP_ID,
            'app_key': ADZUNA_API_KEY,
            'what': keywords,
            'where': location,
            'results_per_page': 50
        }
        
        try:
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                jobs.extend(results)
                print(f"  ✓ {location} - Page {page}: {len(results)} jobs")
            elif response.status_code == 429:
                print(f"  ⚠ Rate limit reached for {location}")
                break
            else:
                print(f"  ✗ Error {response.status_code} for {location} page {page}")
                
        except Exception as e:
            print(f"  ✗ Exception for {location} page {page}: {str(e)}")
    
    return jobs

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch Jobs from Multiple Cities

# COMMAND ----------

all_jobs = []

print("Fetching jobs from French cities...\n")

# Fetch for top 5 cities (to stay within API limits)
for city in FRENCH_CITIES[:5]:
    print(f"📍 {city}:")
    city_jobs = fetch_adzuna_jobs(
        country='fr',
        keywords='data engineer',
        location=city,
        pages=2  # 2 pages = 100 jobs per city
    )
    all_jobs.extend(city_jobs)
    print(f"   Total: {len(city_jobs)} jobs\n")

print(f"\n{'='*50}")
print(f"✅ Total jobs fetched: {len(all_jobs)}")
print(f"{'='*50}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Preview Sample Jobs

# COMMAND ----------

if all_jobs:
    print("Sample jobs:\n")
    for i, job in enumerate(all_jobs[:3], 1):
        print(f"{i}. {job.get('title', 'N/A')}")
        print(f"   Company: {job.get('company', {}).get('display_name', 'N/A')}")
        print(f"   Location: {job.get('location', {}).get('display_name', 'N/A')}")
        print(f"   Salary: {job.get('salary_min', 'N/A')} - {job.get('salary_max', 'N/A')} EUR")
        print(f"   URL: {job.get('redirect_url', 'N/A')[:50]}...")
        print()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save Raw Jobs to Staging Table (for next notebook)

# COMMAND ----------

# Save raw jobs to a staging Delta table so the next notebooks can read them.
# (dbutils.jobs.taskValues only works inside a job run and cannot carry large
# payloads — a staging table works both interactively and in scheduled jobs.)
CATALOG_SCHEMA = "main.job_hunting"
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG_SCHEMA}")

raw_df = spark.createDataFrame(
    [(i, json.dumps(job)) for i, job in enumerate(all_jobs)],
    "fetch_index INT, raw_json STRING",
)
raw_df.write.mode("overwrite").option("mergeSchema", "true").saveAsTable(
    f"{CATALOG_SCHEMA}.staging_raw_jobs"
)

print(f"✅ Saved {len(all_jobs)} raw jobs to {CATALOG_SCHEMA}.staging_raw_jobs")
print("   03_transform_jobs.py reads this table and writes staging_transformed_jobs.")