# Databricks notebook source
# MAGIC %md
# MAGIC # Generate Embeddings for Job Descriptions
# MAGIC 
# MAGIC Create vector embeddings using Databricks Foundation Models with the native
# MAGIC `ai_query` function — no pandas UDF and no manual API tokens needed.

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, concat_ws, substring, expr

spark = SparkSession.builder.appName("GenerateEmbeddings").getOrCreate()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Jobs from Delta Lake

# COMMAND ----------

jobs_df = spark.table("main.job_hunting.raw_job_postings")

print(f"✅ Loaded {jobs_df.count()} jobs")

# Show sample
jobs_df.select("job_id", "title", "company", "location").show(5, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Combined Text for Embedding
# MAGIC 
# MAGIC Combine title, company, location, and description into one text field.

# COMMAND ----------

jobs_with_text = jobs_df.withColumn(
    "combined_text",
    concat_ws(
        " | ",
        col("title"),
        col("company"),
        col("location"),
        col("contract_type_fr"),
        col("remote_type"),
        # Truncate description to 1000 chars to avoid token limits
        substring(col("description"), 1, 1000)
    )
)

print("Sample combined text:")
jobs_with_text.select("job_id", "combined_text").show(2, truncate=100)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Embeddings with `ai_query` (Databricks Foundation Model)
# MAGIC 
# MAGIC `databricks-bge-large-en` produces **1024-dimensional** vectors.
# MAGIC 
# MAGIC Notes:
# MAGIC - `ai_query` is the native Spark expression (pandas UDFs are a last resort),
# MAGIC   and `w.config.token` is typically None on serverless notebooks, which
# MAGIC   would break manual HTTP calls.
# MAGIC - `bge-large-en` is English-tuned. It still embeds French text, but a
# MAGIC   multilingual model (e.g. BAAI/bge-m3 on a Model Serving endpoint) is a
# MAGIC   good upgrade — only this name would change.

# COMMAND ----------

MODEL_ENDPOINT = "databricks-bge-large-en"  # must match 02_create_vector_index.py

jobs_with_embeddings = jobs_with_text.withColumn(
    "embedding",
    expr(f"ai_query('{MODEL_ENDPOINT}', combined_text)"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Generate Embeddings (This may take a few minutes)

# COMMAND ----------

print("Generating embeddings...")

# Cache to avoid recomputation
jobs_with_embeddings.cache()

# Count to trigger computation
embedding_count = jobs_with_embeddings.filter(col("embedding").isNotNull()).count()

print(f"\n✅ Generated embeddings for {embedding_count} jobs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Embeddings

# COMMAND ----------

# Check embedding dimensions
sample_embedding = jobs_with_embeddings.filter(col("embedding").isNotNull()).select("embedding").first()

if sample_embedding:
    embedding_dim = len(sample_embedding['embedding'])
    print(f"✅ Embedding dimension: {embedding_dim}")
    print("   (databricks-bge-large-en produces 1024-dimensional vectors)")

    # Show sample
    print(f"\nFirst 10 values of sample embedding:")
    print(sample_embedding['embedding'][:10])
else:
    print("❌ No embeddings generated - check errors above")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save to Delta Lake

# COMMAND ----------

# Select relevant columns
final_df = jobs_with_embeddings.select(
    "job_id",
    "source",
    "title",
    "company",
    "location",
    "country",
    "remote_type",
    "description",
    "salary_min",
    "salary_max",
    "salary_currency",
    "url",
    "posted_date",
    "contract_type_fr",
    "fetched_at",
    "combined_text",
    "embedding"
)

# Save to new table
table_name = "main.job_hunting.job_postings_with_embeddings"

final_df.write \
    .format("delta") \
    .mode("overwrite") \
    .option("overwriteSchema", "true") \
    .saveAsTable(table_name)

# Delta Sync vector indexes (02_create_vector_index.py) require Change Data Feed
# and a primary key on the source table. The overwrite above can drop them,
# so (re-)apply both after every write.
try:
    spark.sql(f"ALTER TABLE {table_name} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
    print("✅ Change Data Feed enabled")
except Exception as e:
    print(f"CDF: {e}")

# PRIMARY KEY requires NOT NULL — the overwrite schema marks job_id nullable,
# so set nullability (no nulls exist) before adding the constraint.
try:
    spark.sql(f"ALTER TABLE {table_name} ALTER COLUMN job_id SET NOT NULL")
    print("✅ job_id set to NOT NULL")
except Exception as e:
    print(f"NOT NULL: {e}")

try:
    spark.sql(f"ALTER TABLE {table_name} ADD CONSTRAINT job_postings_pk PRIMARY KEY (job_id)")
    print("✅ Primary key constraint added")
except Exception as e:
    print(f"PK: {e}")

print(f"\n✅ Saved {final_df.count()} jobs with embeddings to {table_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Saved Data

# COMMAND ----------

# Read back
result_df = spark.table(table_name)

print(f"\nTable: {table_name}")
print(f"Total rows: {result_df.count()}")
print(f"Rows with embeddings: {result_df.filter(col('embedding').isNotNull()).count()}")

# Show sample
result_df.select("job_id", "title", "company", "location").show(5, truncate=False)

# COMMAND ----------

print("\n" + "="*60)
print("✅ EMBEDDINGS GENERATION COMPLETE")
print("="*60)
print(f"Table: {table_name}")
print(f"Jobs with embeddings: {result_df.filter(col('embedding').isNotNull()).count()}")
print(f"Embedding dimension: {embedding_dim}")
print("="*60)