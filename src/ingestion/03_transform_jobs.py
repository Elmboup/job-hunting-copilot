# Databricks notebook source
# MAGIC %md
# MAGIC # Data Transformation: Clean and Structure Job Data
# MAGIC 
# MAGIC Transform raw Adzuna jobs into our schema (clean, deduplicate, normalize).

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
from pyspark.sql.window import Window
from datetime import datetime

spark = SparkSession.builder.appName("JobTransformation").getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Raw Jobs from Staging Table

# COMMAND ----------

# Read the raw jobs fetched by 01_fetch_adzuna_jobs.py (staging Delta table).
# Falls back to a small live fetch so this notebook can also run standalone.
import json

try:
    raw_df = spark.table("main.job_hunting.staging_raw_jobs")
    raw_jobs = [json.loads(r.raw_json) for r in raw_df.collect()]
    print(f"✅ Loaded {len(raw_jobs)} raw jobs from main.job_hunting.staging_raw_jobs")
except Exception:
    print("⚠ Staging table not found — running standalone with a small live fetch")
    print("   (run 01_fetch_adzuna_jobs.py first for the full pipeline)")
    import requests
    ADZUNA_APP_ID = dbutils.secrets.get(scope="job-hunting", key="adzuna-app-id")
    ADZUNA_API_KEY = dbutils.secrets.get(scope="job-hunting", key="adzuna-api-key")

    response = requests.get(
        "https://api.adzuna.com/v1/api/jobs/fr/search/1",
        params={
            'app_id': ADZUNA_APP_ID,
            'app_key': ADZUNA_API_KEY,
            'what': 'data engineer',
            'where': 'Paris',
            'results_per_page': 20
        }
    )
    raw_jobs = response.json()['results']

# COMMAND ----------

# MAGIC %md
# MAGIC ## Transformation Functions

# COMMAND ----------

def detect_contract_type(title, description):
    """Detect French contract type from job title/description"""
    text = f"{title} {description}".lower()
    
    if 'cdi' in text:
        return 'CDI'
    elif 'cdd' in text:
        return 'CDD'
    elif 'stage' in text:
        return 'Stage'
    elif 'alternance' in text:
        return 'Alternance'
    elif 'freelance' in text or 'indépendant' in text:
        return 'Freelance'
    else:
        return 'CDI'  # Default assumption

def detect_remote_type(title, description):
    """Detect if job is remote/hybrid/onsite"""
    text = f"{title} {description}".lower()
    
    if any(word in text for word in ['remote', 'télétravail', '100% remote', 'full remote']):
        return 'remote'
    elif any(word in text for word in ['hybride', 'hybrid', 'partiel']):
        return 'hybrid'
    else:
        return 'onsite'

def transform_job(job):
    """Transform raw Adzuna job to our schema"""
    title = job.get('title', '')
    description = job.get('description', '')
    
    return {
        'job_id': f"adzuna_{job.get('id')}",
        'source': 'adzuna',
        'title': title,
        'company': job.get('company', {}).get('display_name'),
        'location': job.get('location', {}).get('display_name'),
        'country': 'France',
        'remote_type': detect_remote_type(title, description),
        'description': description,
        'salary_min': int(job.get('salary_min', 0)) if job.get('salary_min') else None,
        'salary_max': int(job.get('salary_max', 0)) if job.get('salary_max') else None,
        'salary_currency': 'EUR',
        'url': job.get('redirect_url'),
        'posted_date': job.get('created'),
        'contract_type_fr': detect_contract_type(title, description),
        'fetched_at': datetime.now().isoformat()
    }

# COMMAND ----------

# MAGIC %md
# MAGIC ## Transform All Jobs

# COMMAND ----------

print("Transforming jobs...\n")

transformed_jobs = [transform_job(job) for job in raw_jobs]

print(f"✅ Transformed {len(transformed_jobs)} jobs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Spark DataFrame

# COMMAND ----------

# Define schema
job_schema = StructType([
    StructField("job_id", StringType(), False),
    StructField("source", StringType(), False),
    StructField("title", StringType(), True),
    StructField("company", StringType(), True),
    StructField("location", StringType(), True),
    StructField("country", StringType(), True),
    StructField("remote_type", StringType(), True),
    StructField("description", StringType(), True),
    StructField("salary_min", IntegerType(), True),
    StructField("salary_max", IntegerType(), True),
    StructField("salary_currency", StringType(), True),
    StructField("url", StringType(), True),
    StructField("posted_date", StringType(), True),
    StructField("contract_type_fr", StringType(), True),
    StructField("fetched_at", StringType(), True)
])

# Create DataFrame
jobs_df = spark.createDataFrame(transformed_jobs, schema=job_schema)

print(f"✅ Created DataFrame with {jobs_df.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deduplicate Job Postings
# MAGIC 
# MAGIC Adzuna sometimes returns the same posting multiple times (same company,
# MAGIC title, and location) under different job IDs. Keep one row per
# MAGIC (company, title, location) — the most recently posted one.

# COMMAND ----------

row_count_before = jobs_df.count()

dedupe_window = Window.partitionBy("company", "title", "location").orderBy(col("posted_date").desc())

jobs_df = (
    jobs_df
    .withColumn("_row_number", row_number().over(dedupe_window))
    .filter(col("_row_number") == 1)
    .drop("_row_number")
)

row_count_after = jobs_df.count()
print(f"✅ Deduplicated: {row_count_before} → {row_count_after} rows ({row_count_before - row_count_after} duplicates removed)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data Quality Checks

# COMMAND ----------

print("Data Quality Report:\n")

# Check for nulls in key fields
print("Null counts:")
jobs_df.select([count(when(col(c).isNull(), c)).alias(c) for c in ['title', 'company', 'location']]).show()

# Contract type distribution
print("\nContract types:")
jobs_df.groupBy('contract_type_fr').count().orderBy(desc('count')).show()

# Remote type distribution
print("\nRemote types:")
jobs_df.groupBy('remote_type').count().orderBy(desc('count')).show()

# Location distribution
print("\nTop locations:")
jobs_df.groupBy('location').count().orderBy(desc('count')).limit(10).show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Preview Sample Data

# COMMAND ----------

print("Sample transformed jobs:\n")
jobs_df.select('title', 'company', 'location', 'contract_type_fr', 'remote_type', 'salary_min').show(10, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save to Staging Table

# COMMAND ----------

# Save the transformed jobs to a staging Delta table for 04_load_to_delta.py.
# (A Spark DataFrame cannot be passed through dbutils.jobs.taskValues — task
# values only carry small JSON-serializable values.)
jobs_df.write.mode("overwrite").option("mergeSchema", "true").saveAsTable(
    "main.job_hunting.staging_transformed_jobs"
)

print(f"✅ Saved {jobs_df.count()} transformed jobs to main.job_hunting.staging_transformed_jobs")