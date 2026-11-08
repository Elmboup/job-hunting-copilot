# Databricks notebook source
# MAGIC %md
# MAGIC # Workflow: Daily Job Sync
# MAGIC
# MAGIC TODO: Orchestrate the daily pipeline — fetch Adzuna + RemoteOK, transform, load
# MAGIC into Lakebase, refresh embeddings. Scheduled by the `daily_job_sync` job defined
# MAGIC in `databricks.yml` (deploy with `databricks bundle deploy`).