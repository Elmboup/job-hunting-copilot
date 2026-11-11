"""Auth helpers for the Databricks App runtime.

The Apps runtime AUTO-INJECTS DATABRICKS_HOST, DATABRICKS_CLIENT_ID and
DATABRICKS_CLIENT_SECRET for the app's service principal — no app.yaml env
block is needed (the valueFrom resources 'workspace-url' /
'service-principal-o-auth-token' failed to resolve in this workspace's
builder; keep this file free of os.environ["DATABRICKS_TOKEN"]).

The app's service principal has been granted:
  - USE CATALOG on main; USE SCHEMA on main.job_hunting and main.job_hunting_tools
  - EXECUTE on the five main.job_hunting_tools.* functions
  - Unity Gateway system.ai.* models are NOT UC securables — no grant applies.
"""

from functools import lru_cache

from databricks.sdk import WorkspaceClient


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    """Single WorkspaceClient for the app, authenticated via the
    runtime-injected service-principal OAuth client credentials."""
    return WorkspaceClient()


def get_host_and_token():
    """(host, bearer_token) for direct API calls — e.g. the Chat Completions
    API at {host}/ai-gateway/mlflow/v1. The SDK mints the OAuth token from
    the service principal's client credentials."""
    wc = get_workspace_client()
    header = wc.config.authenticate()["Authorization"]
    return wc.config.host.rstrip("/"), header.split(" ", 1)[1]
