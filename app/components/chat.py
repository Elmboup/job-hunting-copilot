"""LangGraph agent over the job-hunting UC functions (via Databricks MCP).

Mirrors the proven stack from 03_agent/03_build_agent.py:
  - one MCP server entry PER UC function (slash-separated URL — the old
    dot-separated schema-level URL fails with an opaque TaskGroup error)
  - ChatOpenAI against the Unity Gateway /ai-gateway/mlflow/v1 Chat
    Completions API (ChatDatabricks 404s on system.ai.* model services)
  - create_react_agent(prompt=...) — langgraph-prebuilt 1.x renamed
    state_modifier -> prompt
"""

import asyncio

from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from components.auth import get_workspace_client

CUC = "main"
SCHEMA = "job_hunting_tools"

UC_FUNCTIONS = [
    "search_jobs",
    "get_job_details",
    "explain_match",
    "draft_cover_letter",
    "get_market_stats",
]

SYSTEM_PROMPT = """Tu es un assistant IA spécialisé dans la recherche d'emploi en France.
Réponds toujours en français. Sois encourageant, précis et actionnable.
Utilise les outils disponibles pour chercher des offres et aider l'utilisateur."""


def build_mcp_client() -> DatabricksMultiServerMCPClient:
    """One DatabricksMCPServer entry per UC function."""
    wc = get_workspace_client()
    host = wc.config.host.rstrip("/")
    return DatabricksMultiServerMCPClient(
        [
            DatabricksMCPServer(
                name=f"job-hunting-tools-{fn}",
                url=f"{host}/api/2.0/mcp/functions/{CUC}/{SCHEMA}/{fn}",
                workspace_client=wc,
            )
            for fn in UC_FUNCTIONS
        ]
    )


async def _build_agent():
    mcp_client = build_mcp_client()
    tools = await mcp_client.get_tools()

    wc = get_workspace_client()
    host = wc.config.host.rstrip("/")
    token = wc.config.authenticate()["Authorization"].split(" ", 1)[1]
    llm = ChatOpenAI(
        model="system.ai.meta-llama-3-3-70b-instruct",
        base_url=f"{host}/ai-gateway/mlflow/v1",
        api_key=token,
    )

    agent = create_react_agent(
        llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    return agent, tools


def get_agent_and_tools():
    """Synchronous entry point for Streamlit (nest_asyncio is applied in app.py)."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(_build_agent())
