# Databricks notebook source
# DBTITLE 1,Cell 1
# Databricks notebook source
# MAGIC %md
# MAGIC # Setup: Create Databricks Secrets
# MAGIC 
# MAGIC Run this once to store your API keys securely.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Instructions
# MAGIC 
# MAGIC 1. Install the Databricks CLI (v0.205 or above) locally — the legacy `pip install databricks-cli` package is deprecated:
# MAGIC    ```bash
# MAGIC    # macOS (Homebrew)
# MAGIC    brew install databricks
# MAGIC    # or with pipx
# MAGIC    pipx install databricks
# MAGIC    ```
# MAGIC 2. Log in (opens your browser — no personal access token needed). Replace the host with your workspace URL:
# MAGIC    ```bash
# MAGIC    databricks auth login --host https://<your-workspace-host>
# MAGIC    ```
# MAGIC 3. Create the secret scope (already done — `job-hunting` exists ✅, shown here for reference):
# MAGIC    ```bash
# MAGIC    databricks secrets create-scope job-hunting
# MAGIC    ```
# MAGIC 4. Add the two secrets. Each command prompts for the value interactively so it never lands in your shell history:
# MAGIC    ```bash
# MAGIC    databricks secrets put-secret job-hunting adzuna-app-id
# MAGIC    databricks secrets put-secret job-hunting adzuna-api-key
# MAGIC    ```
# MAGIC 5. Verify the keys exist:
# MAGIC    ```bash
# MAGIC    databricks secrets list-secrets job-hunting
# MAGIC    ```

# COMMAND ----------

# Test secrets (values will be redacted)
try:
    app_id = dbutils.secrets.get(scope="job-hunting", key="adzuna-app-id")
    api_key = dbutils.secrets.get(scope="job-hunting", key="adzuna-api-key")
    print("✅ Secrets configured successfully!")
    print(f"App ID: {app_id[:4]}... (redacted)")
    print(f"API Key: {api_key[:4]}... (redacted)")
except Exception as e:
    print(f"❌ Error: {e}")
    print("Please follow the instructions above to create secrets.")

# COMMAND ----------

# DBTITLE 1,Store Adzuna API secrets from notebook
# Store the Adzuna API credentials in the 'job-hunting' secret scope — right from this notebook.
# No local Databricks CLI needed: the Databricks SDK authenticates automatically as you.
#
# How to use:
#   1. Run this cell once — two input widgets appear at the top of the notebook
#           (values are visible while typing, so do this when your screen isn't shared).
#   2. Type your Adzuna App ID and API Key into the widgets.
#   3. Re-run this cell — the values are stored as secrets and the widgets are removed.

from databricks.sdk import WorkspaceClient

SCOPE = "job-hunting"

# Show the input widgets (they persist across runs until removed)
dbutils.widgets.text("adzuna_app_id_input", "", "Adzuna App ID")
dbutils.widgets.text("adzuna_api_key_input", "", "Adzuna API Key")

app_id_value = dbutils.widgets.get("adzuna_app_id_input")
api_key_value = dbutils.widgets.get("adzuna_api_key_input")

if not app_id_value or not api_key_value:
    print("⚠️ Enter your Adzuna App ID and API Key in the two widgets above, then re-run this cell.")
else:
    w = WorkspaceClient()  # authenticated as the current user
    w.secrets.put_secret(scope=SCOPE, key="adzuna-app-id", string_value=app_id_value)
    w.secrets.put_secret(scope=SCOPE, key="adzuna-api-key", string_value=api_key_value)

    # Remove the widgets so the typed values don't linger in the notebook UI
    dbutils.widgets.remove("adzuna_app_id_input")
    dbutils.widgets.remove("adzuna_api_key_input")

    print("✅ Secrets stored in scope 'job-hunting': adzuna-app-id, adzuna-api-key. Widgets removed.")
    print("Re-run the test cell above to verify with the redacted output.")