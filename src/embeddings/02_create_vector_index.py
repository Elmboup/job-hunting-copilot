# Databricks notebook source
# MAGIC %md
# MAGIC ## Install Dependencies
# MAGIC 
# MAGIC `databricks-ai-search` (formerly `databricks-vectorsearch`) is not
# MAGIC preinstalled on serverless — run this cell first in every new session.

# COMMAND ----------

%pip install databricks-ai-search

# COMMAND ----------

# MAGIC %md
# MAGIC # Create Vector Search Index
# MAGIC 
# MAGIC Set up Databricks Vector Search for semantic job matching.
# MAGIC 
# MAGIC The index uses **self-managed embeddings**: the `embedding` column is
# MAGIC pre-computed by `01_generate_embeddings.py`, so the index has no embedding
# MAGIC model endpoint of its own — queries must embed the query text with
# MAGIC `ai_query` and pass a `query_vector` (see Step 5).

# COMMAND ----------

from databricks.ai_search.client import VectorSearchClient
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

spark = SparkSession.builder.appName("CreateVectorIndex").getOrCreate()

# VectorSearchClient: endpoint/index management and sync
vsc = VectorSearchClient()

# WorkspaceClient: raw-vector queries (query_index) — the SDK passes vectors
# directly, avoiding JSON truncation of large 1024-dim vectors
w = WorkspaceClient()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration

# COMMAND ----------

# Vector Search configuration
ENDPOINT_NAME = "job-hunting-endpoint"
INDEX_NAME = "main.job_hunting.job_postings_vector_index"
SOURCE_TABLE = "main.job_hunting.job_postings_with_embeddings"
PRIMARY_KEY = "job_id"
EMBEDDING_COLUMN = "embedding"
EMBEDDING_DIMENSION = 1024  # databricks-bge-large-en output dimension
MODEL_ENDPOINT = "databricks-bge-large-en"  # must match 01_generate_embeddings.py

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Create Vector Search Endpoint

# COMMAND ----------

# Check if endpoint exists
try:
    endpoint = vsc.get_endpoint(ENDPOINT_NAME)
    print(f"✅ Endpoint '{ENDPOINT_NAME}' already exists")
    print(f"   Status: {endpoint.get('endpoint_status', {}).get('state', 'UNKNOWN')}")
except Exception:
    print(f"Creating endpoint '{ENDPOINT_NAME}'...")

    # Create endpoint
    vsc.create_endpoint(
        name=ENDPOINT_NAME,
        endpoint_type="STANDARD"
    )

    print(f"✅ Endpoint '{ENDPOINT_NAME}' created")
    print("   Note: It may take 5-10 minutes to become ONLINE")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Wait for Endpoint to be Online

# COMMAND ----------

import time

print("Waiting for endpoint to be ONLINE...")

max_wait = 600  # 10 minutes
start_time = time.time()

while time.time() - start_time < max_wait:
    try:
        endpoint = vsc.get_endpoint(ENDPOINT_NAME)
        state = endpoint.get('endpoint_status', {}).get('state', 'UNKNOWN')

        print(f"  Status: {state}")

        if state == "ONLINE":
            print("\n✅ Endpoint is ONLINE!")
            break
        elif state in ["OFFLINE", "FAILED"]:
            print(f"\n❌ Endpoint is {state}")
            break

        time.sleep(30)  # Check every 30 seconds

    except Exception as e:
        print(f"  Error checking status: {e}")
        time.sleep(30)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Create Vector Search Index
# MAGIC 
# MAGIC Prerequisites (set up at the end of `01_generate_embeddings.py`):
# MAGIC - Change Data Feed enabled on the source table
# MAGIC - `PRIMARY KEY` constraint on `job_id`

# COMMAND ----------

# Check if index exists
try:
    index = vsc.get_index(endpoint_name=ENDPOINT_NAME, index_name=INDEX_NAME)
    print(f"✅ Index '{INDEX_NAME}' already exists")
except Exception:
    print(f"Creating index '{INDEX_NAME}'...")

    # Create delta sync index with self-managed (pre-computed) embeddings
    vsc.create_delta_sync_index(
        endpoint_name=ENDPOINT_NAME,
        index_name=INDEX_NAME,
        source_table_name=SOURCE_TABLE,
        pipeline_type="TRIGGERED",
        primary_key=PRIMARY_KEY,
        embedding_dimension=EMBEDDING_DIMENSION,
        embedding_vector_column=EMBEDDING_COLUMN
    )

    print(f"✅ Index '{INDEX_NAME}' created")
    print("   Syncing data from source table...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Sync Index (if needed)

# COMMAND ----------

# Trigger sync
try:
    vsc.get_index(endpoint_name=ENDPOINT_NAME, index_name=INDEX_NAME).sync()
    print("✅ Index sync triggered")
except Exception as e:
    print(f"Sync info: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Test Semantic Search
# MAGIC 
# MAGIC The index has no embedding model endpoint (self-managed embeddings), so
# MAGIC `query_text` cannot be used. Instead: embed the query with `ai_query`, then
# MAGIC pass the vector with `query_vector` via the SDK's `query_index`.

# COMMAND ----------

print("Testing semantic search...\n")

# Test query in French
test_query = "ingénieur data Python Spark CDI Paris"

try:
    # Embed the query text with the same model used for the documents
    query_vector = (
        spark.createDataFrame([(test_query,)], "q STRING")
        .selectExpr(f"ai_query('{MODEL_ENDPOINT}', q) AS embedding")
        .first()["embedding"]
    )

    results = w.vector_search_indexes.query_index(
        index_name=INDEX_NAME,
        columns=["job_id", "title", "company", "location", "contract_type_fr", "url"],
        query_vector=query_vector,
        num_results=5,
    )

    print(f"Query: '{test_query}'\n")
    print("Top 5 matching jobs:\n")

    for i, row in enumerate(results.result.data_array, 1):
        # row = [job_id, title, company, location, contract_type_fr, url, score]
        print(f"{i}. {row[1]}")
        print(f"   Company: {row[2]}")
        print(f"   Location: {row[3]}")
        print(f"   Contract: {row[4]}")
        print(f"   Score: {row[-1]}")
        print()

    print("✅ Semantic search is working!")

except Exception as e:
    print(f"❌ Error testing search: {e}")
    print("   The index may still be syncing. Wait a few minutes and try again.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Different Queries

# COMMAND ----------

test_queries = [
    "stage data science machine learning",
    "développeur backend remote télétravail",
    "CDI Lyon ingénieur",
    "freelance consultant data"
]

print("Testing multiple queries:\n")

for query in test_queries:
    try:
        query_vector = (
            spark.createDataFrame([(query,)], "q STRING")
            .selectExpr(f"ai_query('{MODEL_ENDPOINT}', q) AS embedding")
            .first()["embedding"]
        )

        results = w.vector_search_indexes.query_index(
            index_name=INDEX_NAME,
            columns=["title", "location", "contract_type_fr"],
            query_vector=query_vector,
            num_results=3,
        )

        top = results.result.data_array[0]
        print(f"Query: '{query}'")
        print(f"  → {top[0]}")
        print(f"     {top[1]} | {top[2]}")
        print()

    except Exception as e:
        print(f"Query: '{query}' - Error: {e}\n")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Alternative: Free Spark Similarity Search (no endpoint)
# MAGIC 
# MAGIC For this dataset size (a few hundred jobs), a Vector Search endpoint is
# MAGIC **not required**: brute-force cosine similarity computed natively in Spark
# MAGIC returns the same top-N results instantly, with zero endpoint cost — only
# MAGIC `ai_query` tokens to embed the query text. Vector Search earns its cost at
# MAGIC millions of vectors or production QPS/latency.
# MAGIC 
# MAGIC Uses only native higher-order expressions (`zip_with`, `aggregate`) —
# MAGIC no UDFs, and the query vector never leaves Spark.

# COMMAND ----------

from pyspark.sql.functions import col, expr


def semantic_search_free(query, num_results=5):
    """Cosine-similarity search over the jobs table — no Vector Search endpoint.

    Works while the job count stays in the tens of thousands. For larger
    collections or low-latency serving, use the Vector Search index above.
    """
    # Embed the query text with the same model as the documents
    query_df = (
        spark.createDataFrame([(query,)], "q STRING")
        .selectExpr(f"ai_query('{MODEL_ENDPOINT}', q) AS query_embedding")
    )

    return (
        spark.table(SOURCE_TABLE)
        .filter(col("embedding").isNotNull())
        .crossJoin(query_df)
        .withColumn(
            "score",
            expr(
                """
                aggregate(zip_with(embedding, query_embedding, (a, b) -> a * b), 0.0D, (acc, x) -> acc + x)
                / (sqrt(aggregate(embedding, 0.0D, (acc, x) -> acc + x * x))
                   * sqrt(aggregate(query_embedding, 0.0D, (acc, x) -> acc + x * x)))
                """
            ),
        )
        .orderBy(col("score").desc())
        .limit(num_results)
    )


# Demo: same French query as Step 5, for comparison with the Vector Search results
demo_results = semantic_search_free("ingénieur data Python Spark CDI Paris", num_results=5)

display(demo_results.select("title", "company", "location", "contract_type_fr", "score"))

# COMMAND ----------

print("\n" + "="*60)
print("✅ VECTOR SEARCH INDEX READY")
print("="*60)
print(f"Endpoint: {ENDPOINT_NAME}")
print(f"Index: {INDEX_NAME}")
print(f"Source table: {SOURCE_TABLE}")
print(f"Embedding dimension: {EMBEDDING_DIMENSION}")
print("\nYou can now search jobs semantically!")
print("="*60)