# Databricks notebook source
# DBTITLE 1,Cell 1
# Databricks notebook source
# MAGIC %md
# MAGIC # Data Ingestion: Fetch Jobs from RemoteOK
# MAGIC 
# MAGIC RemoteOK lists **global remote jobs** (no France filter), so it is not part
# MAGIC of the current French-jobs pipeline (Adzuna → Delta Lake).
# MAGIC 
# MAGIC TODO if needed: follow the same pattern as `01_fetch_adzuna_jobs.py` —
# MAGIC fetch https://remoteok.com/api (User-Agent header required, skip the first
# MAGIC metadata element), then write the raw JSON to a staging table
# MAGIC (e.g. `main.job_hunting.staging_remoteok_jobs`) for `03_transform_jobs.py`.