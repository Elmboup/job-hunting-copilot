# Databricks notebook source
# DBTITLE 1,Test UC Functions
# MAGIC %md
# MAGIC # Test UC Functions
# MAGIC
# MAGIC Interactive tests for the agent tools created in `01_create_uc_functions.sql`. Each cell exercises one tool — run them in order after the functions exist.
# MAGIC
# MAGIC All tools are plain SQL functions in `main.job_hunting_tools` — no Vector Search endpoint needed. `search_jobs` embeds the query with `ai_query` and scores with native cosine similarity; `explain_match` and `draft_cover_letter` call the LLM through `ai_query` as well.

# COMMAND ----------

# DBTITLE 1,Test 1: search_jobs
# MAGIC %md
# MAGIC ## Test 1: search_jobs (semantic search)
# MAGIC
# MAGIC Semantic search via `ai_query` embedding + cosine similarity — no Vector Search endpoint required.

# COMMAND ----------

# DBTITLE 1,search_jobs test query
# MAGIC %sql
# MAGIC SELECT * FROM main.job_hunting_tools.search_jobs(
# MAGIC     'ingénieur data Python',
# MAGIC     'Paris',
# MAGIC     false,
# MAGIC     'CDI',
# MAGIC     5
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Test 2: get_job_details
# MAGIC %md
# MAGIC ## Test 2: get_job_details
# MAGIC
# MAGIC Picks a real `job_id` from the embeddings table (the original test suite never covered this tool).

# COMMAND ----------

# DBTITLE 1,get_job_details test
job_id = spark.sql(
    "SELECT job_id FROM main.job_hunting.job_postings_with_embeddings LIMIT 1"
).collect()[0][0]
print(f"Testing with job_id: {job_id}")

display(spark.sql(f"SELECT * FROM main.job_hunting_tools.get_job_details('{job_id}')"))

# COMMAND ----------

# DBTITLE 1,Test 3: explain_match
# MAGIC %md
# MAGIC ## Test 3: explain_match

# COMMAND ----------

# DBTITLE 1,explain_match test query
# MAGIC %sql
# MAGIC SELECT main.job_hunting_tools.explain_match(
# MAGIC     'Data Engineer Senior',
# MAGIC     'Nous recherchons un Data Engineer avec 3+ ans d\'expérience en Python, Spark, et SQL.',
# MAGIC     'Python, Spark, SQL, Databricks',
# MAGIC     '4 ans d\'expérience en data engineering'
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Test 4: draft_cover_letter
# MAGIC %md
# MAGIC ## Test 4: draft_cover_letter

# COMMAND ----------

# DBTITLE 1,draft_cover_letter test query
# MAGIC %sql
# MAGIC SELECT main.job_hunting_tools.draft_cover_letter(
# MAGIC     'Data Engineer',
# MAGIC     'TechCorp',
# MAGIC     'Poste de Data Engineer pour construire des pipelines de données à grande échelle.',
# MAGIC     'Data Engineer avec 3 ans d\'expérience en Python, Spark et cloud'
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Test 5: get_market_stats
# MAGIC %md
# MAGIC ## Test 5: get_market_stats

# COMMAND ----------

# DBTITLE 1,get_market_stats test query
# MAGIC %sql
# MAGIC SELECT * FROM main.job_hunting_tools.get_market_stats('Paris', NULL);