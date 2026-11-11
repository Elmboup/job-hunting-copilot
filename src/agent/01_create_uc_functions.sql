# Databricks notebook source
# DBTITLE 1,Create Unity Catalog Functions for AI Agent
# MAGIC %md
# MAGIC # Create Unity Catalog Functions for AI Agent
# MAGIC
# MAGIC These functions will be the agent's "tools" to search jobs, explain matches, and save applications. They are exposed to the agent via MCP in `03_build_agent.py`.
# MAGIC
# MAGIC Prerequisites: `main.job_hunting.job_postings_with_embeddings` must exist (run `02_embeddings/01_generate_embeddings.py` first).
# MAGIC
# MAGIC Interactive tests live in `02_test_uc_functions.py`.
# MAGIC
# MAGIC ⚠ All functions use the `RETURN`-clause form — the `AS $$...$$ LANGUAGE SQL` form is rejected by this workspace ("SQL is not a supported language for external user defined functions"). The `RETURN` form runs fine on serverless compute (all cells verified 2026-11-08) and on SQL warehouses. The same DDL is mirrored in the query *Create agent tool functions (TVF DDL)*. Tools 3 and 4 are scalar SQL functions calling the LLM via `ai_query` (not Python UDFs — UC Python function bodies cannot authenticate).

# COMMAND ----------

# DBTITLE 1,Create Schema for Agent Tools
# MAGIC %md
# MAGIC ## Create Schema for Agent Tools

# COMMAND ----------

# DBTITLE 1,Create schema
# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS main.job_hunting_tools;

# COMMAND ----------

# DBTITLE 1,Tool 1: Search Jobs
# MAGIC %md
# MAGIC ## Tool 1: Search Jobs (Semantic Search)
# MAGIC
# MAGIC Implemented as a pure SQL table-valued function: the query text is embedded with `ai_query` (same model as the documents — `databricks-bge-large-en`, 1024 dims) and scored with native cosine similarity over the embeddings table. This needs **no Vector Search endpoint** (the earlier draft used one, but this runtime requires a HANDLER clause for Python TVFs and the endpoint was never provisioned — the free SQL approach avoids both).
# MAGIC
# MAGIC Uses the `RETURN`-clause form — `AS $$...$$ LANGUAGE SQL` is rejected by this workspace as an "external" UDF. The `RETURN` form runs fine on both serverless compute and SQL warehouses.

# COMMAND ----------

# DBTITLE 1,Create search_jobs function
# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION main.job_hunting_tools.search_jobs(
# MAGIC     user_query STRING COMMENT 'Natural language search query in French or English',
# MAGIC     location STRING COMMENT 'Optional location filter (e.g., Paris, Lyon)',
# MAGIC     remote_only BOOLEAN COMMENT 'Filter for remote jobs only',
# MAGIC     contract_type STRING COMMENT 'Optional contract type filter (CDI, CDD, Stage, Alternance, Freelance)',
# MAGIC     max_results INT COMMENT 'Maximum number of results to return (default 10)'
# MAGIC )
# MAGIC RETURNS TABLE(
# MAGIC     job_id STRING,
# MAGIC     title STRING,
# MAGIC     company STRING,
# MAGIC     location STRING,
# MAGIC     contract_type_fr STRING,
# MAGIC     remote_type STRING,
# MAGIC     salary_min INT,
# MAGIC     salary_max INT,
# MAGIC     url STRING,
# MAGIC     match_score DOUBLE
# MAGIC )
# MAGIC COMMENT 'Search for jobs using semantic similarity. Returns jobs matching the query with relevance scores. Embeds the query with ai_query (databricks-bge-large-en) and scores with native cosine similarity — no Vector Search endpoint required.'
# MAGIC RETURN
# MAGIC     WITH query AS (
# MAGIC         SELECT ai_query('databricks-bge-large-en', search_jobs.user_query) AS query_embedding
# MAGIC     ),
# MAGIC     scored AS (
# MAGIC         SELECT
# MAGIC             j.job_id,
# MAGIC             j.title,
# MAGIC             j.company,
# MAGIC             j.location,
# MAGIC             j.contract_type_fr,
# MAGIC             j.remote_type,
# MAGIC             j.salary_min,
# MAGIC             j.salary_max,
# MAGIC             j.url,
# MAGIC             aggregate(zip_with(j.embedding, q.query_embedding, (a, b) -> a * b), 0.0D, (acc, x) -> acc + x)
# MAGIC                 / (sqrt(aggregate(j.embedding, 0.0D, (acc, x) -> acc + x * x))
# MAGIC                    * sqrt(aggregate(q.query_embedding, 0.0D, (acc, x) -> acc + x * x))) AS match_score
# MAGIC         FROM main.job_hunting.job_postings_with_embeddings j
# MAGIC         CROSS JOIN query q
# MAGIC         WHERE j.embedding IS NOT NULL
# MAGIC           -- nullif(...): LLM tool callers often pass '' instead of NULL for optional
# MAGIC           -- string parameters; treat both as "no filter"
# MAGIC           AND (nullif(search_jobs.location, '') IS NULL OR j.location LIKE concat('%', search_jobs.location, '%'))
# MAGIC           AND (NOT coalesce(search_jobs.remote_only, false) OR j.remote_type = 'remote')
# MAGIC           AND (nullif(search_jobs.contract_type, '') IS NULL OR j.contract_type_fr = search_jobs.contract_type)
# MAGIC     )
# MAGIC     SELECT job_id, title, company, location, contract_type_fr, remote_type, salary_min, salary_max, url, match_score
# MAGIC     FROM (
# MAGIC         SELECT s.*, row_number() OVER (ORDER BY match_score DESC) AS rn
# MAGIC         FROM scored s
# MAGIC     )
# MAGIC     WHERE rn <= coalesce(search_jobs.max_results, 10)
# MAGIC     ORDER BY rn;

# COMMAND ----------

# DBTITLE 1,Tool 2: Get Job Details
# MAGIC %md
# MAGIC ## Tool 2: Get Job Details

# COMMAND ----------

# DBTITLE 1,Create get_job_details function
# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION main.job_hunting_tools.get_job_details(
# MAGIC     job_id STRING COMMENT 'Job ID to retrieve'
# MAGIC )
# MAGIC RETURNS TABLE(
# MAGIC     job_id STRING,
# MAGIC     title STRING,
# MAGIC     company STRING,
# MAGIC     location STRING,
# MAGIC     contract_type_fr STRING,
# MAGIC     remote_type STRING,
# MAGIC     description STRING,
# MAGIC     salary_min INT,
# MAGIC     salary_max INT,
# MAGIC     salary_currency STRING,
# MAGIC     url STRING,
# MAGIC     posted_date STRING
# MAGIC )
# MAGIC COMMENT 'Get full details for a specific job by ID.'
# MAGIC RETURN
# MAGIC     SELECT 
# MAGIC         job_id,
# MAGIC         title,
# MAGIC         company,
# MAGIC         location,
# MAGIC         contract_type_fr,
# MAGIC         remote_type,
# MAGIC         description,
# MAGIC         salary_min,
# MAGIC         salary_max,
# MAGIC         salary_currency,
# MAGIC         url,
# MAGIC         posted_date
# MAGIC     FROM main.job_hunting.job_postings_with_embeddings
# MAGIC     WHERE job_id = get_job_details.job_id;

# COMMAND ----------

# DBTITLE 1,Tool 3: Explain Job Match
# MAGIC %md
# MAGIC ## Tool 3: Explain Job Match

# COMMAND ----------

# DBTITLE 1,Create explain_match function
# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION main.job_hunting_tools.explain_match(
# MAGIC     job_title STRING COMMENT 'Job title',
# MAGIC     job_description STRING COMMENT 'Job description',
# MAGIC     user_skills STRING COMMENT 'User skills (comma-separated)',
# MAGIC     user_experience STRING COMMENT 'User experience description'
# MAGIC )
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Explain why a job is or is not a good match for the user. Returns detailed analysis. Uses ai_query with system.ai.meta-llama-3-3-70b-instruct.'
# MAGIC RETURN ai_query(
# MAGIC     'system.ai.meta-llama-3-3-70b-instruct',
# MAGIC     concat(
# MAGIC         'Analyse cette correspondance d''emploi:\n\n',
# MAGIC         'Poste: ', coalesce(job_title, ''), '\n',
# MAGIC         'Description: ', coalesce(left(job_description, 1000), ''), '\n\n',
# MAGIC         'Profil du candidat:\n',
# MAGIC         '- Compétences: ', coalesce(user_skills, ''), '\n',
# MAGIC         '- Expérience: ', coalesce(user_experience, ''), '\n\n',
# MAGIC         'Explique pourquoi ce poste est ou n''est pas adapté. Sois spécifique sur:\n',
# MAGIC         '1. Compétences correspondantes\n',
# MAGIC         '2. Compétences manquantes\n',
# MAGIC         '3. Niveau d''expérience requis\n',
# MAGIC         '4. Recommandation globale (Excellent match / Bon match / Match partiel / Pas adapté)\n\n',
# MAGIC         'Réponds en français, de manière concise (3-4 phrases).'
# MAGIC     )
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Tool 4: Draft Cover Letter
# MAGIC %md
# MAGIC ## Tool 4: Draft Cover Letter (French)

# COMMAND ----------

# DBTITLE 1,Create draft_cover_letter function
# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION main.job_hunting_tools.draft_cover_letter(
# MAGIC     job_title STRING COMMENT 'Job title',
# MAGIC     company STRING COMMENT 'Company name',
# MAGIC     job_description STRING COMMENT 'Job description',
# MAGIC     user_background STRING COMMENT 'User background and experience'
# MAGIC )
# MAGIC RETURNS STRING
# MAGIC COMMENT 'Generate a professional French cover letter paragraph for the job. Uses ai_query with system.ai.meta-llama-3-3-70b-instruct.'
# MAGIC RETURN ai_query(
# MAGIC     'system.ai.meta-llama-3-3-70b-instruct',
# MAGIC     concat(
# MAGIC         'Rédige un paragraphe de lettre de motivation professionnelle en français pour:\n\n',
# MAGIC         'Poste: ', coalesce(job_title, ''), '\n',
# MAGIC         'Entreprise: ', coalesce(company, ''), '\n',
# MAGIC         'Description: ', coalesce(left(job_description, 500), ''), '\n',
# MAGIC         'Profil du candidat: ', coalesce(user_background, ''), '\n\n',
# MAGIC         'Format français standard:\n',
# MAGIC         '- Commence par "Madame, Monsieur,"\n',
# MAGIC         '- 3-4 phrases maximum\n',
# MAGIC         '- Mets en avant les compétences pertinentes\n',
# MAGIC         '- Montre l''intérêt pour l''entreprise\n',
# MAGIC         '- Ton professionnel mais pas trop formel\n\n',
# MAGIC         'Ne génère QUE le paragraphe principal, pas la formule de politesse finale.'
# MAGIC     )
# MAGIC );

# COMMAND ----------

# DBTITLE 1,Tool 5: Market Statistics
# MAGIC %md
# MAGIC ## Tool 5: Get Job Market Statistics

# COMMAND ----------

# DBTITLE 1,Create get_market_stats function
# MAGIC %sql
# MAGIC CREATE OR REPLACE FUNCTION main.job_hunting_tools.get_market_stats(
# MAGIC     location STRING COMMENT 'Optional location filter',
# MAGIC     contract_type STRING COMMENT 'Optional contract type filter'
# MAGIC )
# MAGIC RETURNS TABLE(
# MAGIC     total_jobs INT,
# MAGIC     avg_salary_min INT,
# MAGIC     avg_salary_max INT,
# MAGIC     top_companies STRING,
# MAGIC     contract_distribution STRING
# MAGIC )
# MAGIC COMMENT 'Get job market statistics for a location or contract type.'
# MAGIC RETURN
# MAGIC     SELECT 
# MAGIC         COUNT(*) as total_jobs,
# MAGIC         CAST(AVG(salary_min) AS INT) as avg_salary_min,
# MAGIC         CAST(AVG(salary_max) AS INT) as avg_salary_max,
# MAGIC         CONCAT_WS(', ', COLLECT_LIST(company)) as top_companies,
# MAGIC         CONCAT_WS(', ', COLLECT_LIST(CONCAT(contract_type_fr, ': ', cnt))) as contract_distribution
# MAGIC     FROM (
# MAGIC         SELECT 
# MAGIC             company,
# MAGIC             contract_type_fr,
# MAGIC             COUNT(*) as cnt,
# MAGIC             salary_min,
# MAGIC             salary_max
# MAGIC         FROM main.job_hunting.job_postings_with_embeddings
# MAGIC         WHERE 
# MAGIC             -- nullif(...): LLM tool callers often pass '' instead of NULL for optional
# MAGIC             -- string parameters; treat both as "no filter"
# MAGIC             (nullif(get_market_stats.location, '') IS NULL OR location LIKE CONCAT('%', get_market_stats.location, '%'))
# MAGIC             AND (nullif(get_market_stats.contract_type, '') IS NULL OR contract_type_fr = get_market_stats.contract_type)
# MAGIC         GROUP BY company, contract_type_fr, salary_min, salary_max
# MAGIC         ORDER BY cnt DESC
# MAGIC         LIMIT 5
# MAGIC     );

# COMMAND ----------

# DBTITLE 1,Verify Functions
# MAGIC %md
# MAGIC ## Verify Functions Created
# MAGIC
# MAGIC The interactive tests that used to live here now live in `02_test_uc_functions.py`.

# COMMAND ----------

# DBTITLE 1,Show created functions
# MAGIC %sql
# MAGIC -- SHOW FUNCTIONS rejects a cross-catalog schema reference on Spark; use information_schema.
# MAGIC SELECT routine_name, external_language, data_type
# MAGIC FROM main.information_schema.routines
# MAGIC WHERE specific_schema = 'job_hunting_tools'
# MAGIC ORDER BY routine_name;

# COMMAND ----------

# DBTITLE 1,Success status
# MAGIC %sql
# MAGIC -- (The original single-cell version ended with a Python-style PRINT(), which is
# MAGIC -- not valid SQL — replaced with this status row.)
# MAGIC SELECT '✅ All UC Functions created successfully!' AS status;