# Databricks notebook source
# DBTITLE 1,Cell 1
# Databricks notebook source
# MAGIC %md
# MAGIC # Load to Delta Lake
# MAGIC 
# MAGIC Save transformed jobs to Delta Lake table.

# COMMAND ----------

from pyspark.sql import SparkSession
from delta.tables import DeltaTable

spark = SparkSession.builder.appName("LoadToDelta").getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Catalog and Schema

# COMMAND ----------

# Create the schema if it doesn't exist (the main catalog already exists)
spark.sql("CREATE SCHEMA IF NOT EXISTS main.job_hunting")

print("✅ Catalog and schema ready")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Transformed Data

# COMMAND ----------

# Read the transformed jobs staged by 03_transform_jobs.py.
if spark.catalog.tableExists("main.job_hunting.staging_transformed_jobs"):
    jobs_df = spark.table("main.job_hunting.staging_transformed_jobs")
    print(f"✅ Loaded {jobs_df.count()} rows from main.job_hunting.staging_transformed_jobs")
else:
    raise Exception(
        "main.job_hunting.staging_transformed_jobs not found — "
        "run 01_fetch_adzuna_jobs.py then 03_transform_jobs.py first"
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save to Delta Lake

# COMMAND ----------

# Table name
table_name = "main.job_hunting.raw_job_postings"

# Check if table exists
table_exists = spark.catalog.tableExists(table_name)

if table_exists:
    print(f"Table {table_name} exists - performing MERGE")
    
    # Load existing table
    delta_table = DeltaTable.forName(spark, table_name)
    
    # Merge (sync) - update existing jobs, insert new ones, and delete rows
    # no longer present in staging (e.g. duplicates removed by 03_transform_jobs.py)
    (
        delta_table.alias("target").merge(
            jobs_df.alias("source"),
            "target.job_id = source.job_id"
        )
        .whenMatchedUpdateAll()
        .whenNotMatchedInsertAll()
        .whenNotMatchedBySourceDelete()
        .execute()
    )
    
    print(f"✅ Merged {jobs_df.count()} jobs into {table_name} (stale rows removed)")
    
else:
    print(f"Table {table_name} doesn't exist - creating new table")
    
    # Create new table
    jobs_df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("mergeSchema", "true") \
        .saveAsTable(table_name)
    
    print(f"✅ Created {table_name} with {jobs_df.count()} jobs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Data

# COMMAND ----------

# Read back from Delta
result_df = spark.table(table_name)

print(f"\nTable Statistics:")
print(f"  Total rows: {result_df.count()}")
print(f"  Unique jobs: {result_df.select('job_id').distinct().count()}")
print(f"  Date range: {result_df.agg({'posted_date': 'min'}).collect()[0][0]} to {result_df.agg({'posted_date': 'max'}).collect()[0][0]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sample Query

# COMMAND ----------

print("\nSample jobs from Delta Lake:\n")

spark.sql(f"""
    SELECT 
        title,
        company,
        location,
        contract_type_fr,
        remote_type,
        CONCAT(salary_min, ' - ', salary_max, ' EUR') as salary
    FROM {table_name}
    WHERE salary_min IS NOT NULL
    ORDER BY posted_date DESC
    LIMIT 10
""").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Success Summary

# COMMAND ----------

print("\n" + "="*60)
print("✅ DATA INGESTION PIPELINE COMPLETE")
print("="*60)
print(f"Table: {table_name}")
print(f"Total jobs: {result_df.count()}")
print(f"Latest fetch: {result_df.agg({'fetched_at': 'max'}).collect()[0][0]}")
print("="*60)