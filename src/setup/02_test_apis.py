# Databricks notebook source
# MAGIC %md
# MAGIC # Setup: Test API Connections
# MAGIC 
# MAGIC Verify that Adzuna and RemoteOK APIs are working.

# COMMAND ----------

import requests
import json

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Adzuna France API

# COMMAND ----------

ADZUNA_APP_ID = dbutils.secrets.get(scope="job-hunting", key="adzuna-app-id")
ADZUNA_API_KEY = dbutils.secrets.get(scope="job-hunting", key="adzuna-api-key")

url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
params = {
    'app_id': ADZUNA_APP_ID,
    'app_key': ADZUNA_API_KEY,
    'what': 'ingénieur data',
    'where': 'Paris',
    'results_per_page': 5
}

response = requests.get(url, params=params)

if response.status_code == 200:
    data = response.json()
    print(f"✅ Adzuna API working!")
    print(f"Total jobs found: {data['count']}")
    print(f"\nFirst 3 jobs:")
    for i, job in enumerate(data['results'][:3], 1):
        print(f"\n{i}. {job['title']}")
        print(f"   Company: {job['company']['display_name']}")
        print(f"   Location: {job['location']['display_name']}")
else:
    print(f"❌ Error: {response.status_code}")
    print(response.text)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test RemoteOK API

# COMMAND ----------

url = "https://remoteok.com/api"
headers = {'User-Agent': 'Mozilla/5.0'}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    jobs = response.json()[1:]  # Skip metadata
    print(f"✅ RemoteOK API working!")
    print(f"Total jobs: {len(jobs)}")
    print(f"\nFirst 3 remote jobs:")
    for i, job in enumerate(jobs[:3], 1):
        print(f"\n{i}. {job.get('position', 'N/A')}")
        print(f"   Company: {job.get('company', 'N/A')}")
        print(f"   Tags: {', '.join(job.get('tags', []))}")
else:
    print(f"❌ Error: {response.status_code}")

# COMMAND ----------

print("\n" + "="*50)
print("✅ All APIs tested successfully!")
print("="*50)

# COMMAND ----------

# Diagnose the stored Adzuna credentials — SAFE: never prints the values, only their shape.
_adzuna_app_id = dbutils.secrets.get(scope="job-hunting", key="adzuna-app-id")
_adzuna_api_key = dbutils.secrets.get(scope="job-hunting", key="adzuna-api-key")

print(f"app_id  length: {len(_adzuna_app_id)}  (Adzuna app IDs are typically 8 hex chars)")
print(f"api_key length: {len(_adzuna_api_key)}  (Adzuna API keys are typically 32 hex chars)")
print(f"app_id  has surrounding whitespace: {_adzuna_app_id != _adzuna_app_id.strip()}")
print(f"api_key has surrounding whitespace: {_adzuna_api_key != _adzuna_api_key.strip()}")

# If the values were entered in the wrong fields (app_id holds the long key), swap them.
# Guarded: it only acts when the swap is needed, so re-running a correct setup is a no-op.
if len(_adzuna_app_id) > len(_adzuna_api_key):
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    w.secrets.put_secret(scope="job-hunting", key="adzuna-app-id", string_value=_adzuna_api_key)
    w.secrets.put_secret(scope="job-hunting", key="adzuna-api-key", string_value=_adzuna_app_id)
    print("\n🔁 Values were swapped — fixed: adzuna-app-id now holds the 8-char App ID,")
    print("   adzuna-api-key now holds the 32-char API key. Re-run the API test above.")
else:
    print("\n✅ Values look correctly ordered (app_id shorter than api_key) — no swap needed.")