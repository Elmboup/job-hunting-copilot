# Databricks notebook source
# DBTITLE 1,Build AI Agent with LangGraph
# MAGIC %md
# MAGIC # Build AI Agent with LangGraph
# MAGIC
# MAGIC Create an AI agent that can search jobs, explain matches, and help with applications. The tools come from the UC functions in `01_create_uc_functions.sql` (exposed via Databricks MCP), and the LLM is `system.ai.meta-llama-3-3-70b-instruct`.
# MAGIC
# MAGIC Prerequisites: the UC functions exist (run `01` first) and `02_test_uc_functions.py` passes.

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# NOTE: the default resolver lands on langgraph 1.0.10 + langgraph-prebuilt 1.0.13,
# which is a symbol-incompatible pair ("cannot import name 'ExecutionInfo' from
# 'langgraph.runtime'"). All langgraph-prebuilt 1.0.x builds import ExecutionInfo, which
# only exists in langgraph >= 1.1 — so upgrade the langgraph stack together.
%pip install langgraph databricks-langchain --upgrade "langgraph>=1.1" "langgraph-prebuilt>=1.0"

# COMMAND ----------

# DBTITLE 1,Install langchain-openai (temp)
# ChatOpenAI client for the /ai-gateway/mlflow/v1 API (Unity Gateway model services).
%pip install langchain-openai

# COMMAND ----------

# DBTITLE 1,Restart Python (load installed packages)
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Imports
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient
from databricks.sdk import WorkspaceClient

# COMMAND ----------

# DBTITLE 1,Initialize Workspace Client
# MAGIC %md
# MAGIC ## Initialize Workspace Client

# COMMAND ----------

# DBTITLE 1,Create workspace client
workspace_client = WorkspaceClient()

print(f"✅ Connected to workspace: {workspace_client.config.host}")

# COMMAND ----------

# DBTITLE 1,Set Up MCP Client
# MAGIC %md
# MAGIC ## Set Up MCP Client for UC Functions

# COMMAND ----------

# DBTITLE 1,Configure MCP client
# Create MCP client that connects to our UC functions.
# URL pattern (per Databricks docs): /api/2.0/mcp/functions/{catalog}/{schema}/{function_name}
# — slash-separated and PER FUNCTION (the earlier draft used a single dot-separated
# schema-level URL, which the endpoint does not recognize).
UC_FUNCTIONS = [
    "search_jobs",
    "get_job_details",
    "explain_match",
    "draft_cover_letter",
    "get_market_stats",
]

mcp_client = DatabricksMultiServerMCPClient([
    DatabricksMCPServer(
        name=f"job-hunting-tools-{fn}",
        url=f"{workspace_client.config.host}/api/2.0/mcp/functions/main/job_hunting_tools/{fn}",
        workspace_client=workspace_client,
    )
    for fn in UC_FUNCTIONS
])

print("✅ MCP client configured")

# COMMAND ----------

# DBTITLE 1,Get Available Tools
# MAGIC %md
# MAGIC ## Get Available Tools

# COMMAND ----------

# DBTITLE 1,Load tools from UC functions
import asyncio

# Get tools from UC functions
tools = await mcp_client.get_tools()

print(f"✅ Loaded {len(tools)} tools:\n")
for tool in tools:
    print(f"  • {tool.name}")

# COMMAND ----------

# DBTITLE 1,Create Agent with French Prompt
# MAGIC %md
# MAGIC ## Create Agent with French Prompt
# MAGIC
# MAGIC ⚠ Two model-access issues found and fixed here:
# MAGIC
# MAGIC 1. `databricks-meta-llama-3-1-70b-instruct` (original draft) **does not exist** — the live model service is `system.ai.meta-llama-3-3-70b-instruct` (Unity Gateway).
# MAGIC 2. `ChatDatabricks` calls the classic `/serving-endpoints/<name>/invocations` route, which returns **404 ENDPOINT_NOT_FOUND** for Unity Gateway (`system.ai.*`) services. The agent therefore uses `ChatOpenAI` against the `/ai-gateway/mlflow/v1` Chat Completions base URL with the notebook session's OAuth token (verified with a live 200 call).

# COMMAND ----------

# DBTITLE 1,Create the agent
# French system prompt
SYSTEM_PROMPT = """Tu es un assistant IA spécialisé dans la recherche d'emploi en France. Tu aides les utilisateurs à:

1. **Rechercher des offres d'emploi** correspondant à leurs compétences et préférences
2. **Expliquer pourquoi** un poste est adapté ou non à leur profil
3. **Rédiger des lettres de motivation** personnalisées en français
4. **Analyser le marché de l'emploi** (salaires, tendances, entreprises)

**Ton style:**
- Réponds toujours en français
- Sois encourageant et positif
- Donne des conseils concrets et actionnables
- Cite des chiffres précis quand tu en as
- Utilise les outils disponibles pour chercher des informations

**Outils disponibles:**
- search_jobs: Recherche sémantique d'offres d'emploi
- get_job_details: Détails complets d'une offre
- explain_match: Analyse de correspondance profil/poste
- draft_cover_letter: Génération de lettre de motivation
- get_market_stats: Statistiques du marché de l'emploi

**Important:**
- Utilise TOUJOURS search_jobs pour trouver des offres
- Propose des offres concrètes avec titres et entreprises
- Explique pourquoi tu recommandes chaque offre
"""

# Create agent
# NOTE: langgraph-prebuilt 1.x renamed `state_modifier` to `prompt`.
# ChatDatabricks 404s on system.ai.* (it calls the classic /serving-endpoints route),
# so use ChatOpenAI against the Unity Gateway /ai-gateway/mlflow/v1 Chat Completions
# API with the notebook session's short-lived OAuth token (never persisted or printed).
auth_token = workspace_client.config.authenticate()["Authorization"].split(" ", 1)[1]

llm = ChatOpenAI(
    model="system.ai.meta-llama-3-3-70b-instruct",
    base_url=f"{workspace_client.config.host.rstrip('/')}/ai-gateway/mlflow/v1",
    api_key=auth_token,
)

agent = create_react_agent(
    llm,
    tools=tools,
    prompt=SYSTEM_PROMPT
)

print("✅ Agent created with French prompt")

# COMMAND ----------

# DBTITLE 1,Helper: Run Agent
# MAGIC %md
# MAGIC ## Helper: Run Agent

# COMMAND ----------

# DBTITLE 1,run_agent helper
async def run_agent(user_message: str, user_context: dict = None):
    """
    Run the agent with a user message
    
    Args:
        user_message: User's question in French or English
        user_context: Optional user profile context
    """
    # Build context message
    context_msg = ""
    if user_context:
        context_msg = f"\n\nContexte utilisateur:\n"
        if user_context.get('skills'):
            context_msg += f"- Compétences: {', '.join(user_context['skills'])}\n"
        if user_context.get('experience'):
            context_msg += f"- Expérience: {user_context['experience']}\n"
        if user_context.get('location'):
            context_msg += f"- Localisation: {user_context['location']}\n"
    
    full_message = user_message + context_msg
    
    # Run agent
    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": full_message}]
    })
    
    return result["messages"][-1].content

# COMMAND ----------

# DBTITLE 1,Test 1: Simple Job Search
# MAGIC %md
# MAGIC ## Test 1: Simple Job Search

# COMMAND ----------

# DBTITLE 1,Test 1 run
print("Test 1: Recherche simple\n")
print("User: Trouve-moi des postes de data engineer à Paris\n")

response = await run_agent(
    "Trouve-moi des postes de data engineer à Paris",
    user_context={
        'skills': ['Python', 'Spark', 'SQL'],
        'experience': '3 ans',
        'location': 'Paris'
    }
)

print(f"Agent: {response}\n")
print("="*60 + "\n")

# COMMAND ----------

# DBTITLE 1,Test 2: Job Match Explanation
# MAGIC %md
# MAGIC ## Test 2: Job Match Explanation

# COMMAND ----------

# DBTITLE 1,Test 2 run
print("Test 2: Explication de correspondance\n")
print("User: Pourquoi ce poste est-il adapté pour moi?\n")

response = await run_agent(
    "J'ai vu une offre de 'Data Engineer Senior' chez une startup. Peux-tu m'expliquer si c'est adapté pour moi?",
    user_context={
        'skills': ['Python', 'Spark', 'SQL', 'Databricks'],
        'experience': '4 ans en data engineering',
        'location': 'Paris'
    }
)

print(f"Agent: {response}\n")
print("="*60 + "\n")

# COMMAND ----------

# DBTITLE 1,Test 3: Cover Letter Generation
# MAGIC %md
# MAGIC ## Test 3: Cover Letter Generation

# COMMAND ----------

# DBTITLE 1,Test 3 run
print("Test 3: Génération de lettre de motivation\n")
print("User: Rédige-moi une lettre de motivation\n")

response = await run_agent(
    "Peux-tu m'aider à rédiger une lettre de motivation pour un poste de Data Engineer chez TechCorp?",
    user_context={
        'skills': ['Python', 'Spark', 'SQL'],
        'experience': '3 ans en data engineering, spécialisé en pipelines temps réel',
        'location': 'Paris'
    }
)

print(f"Agent: {response}\n")
print("="*60 + "\n")

# COMMAND ----------

# DBTITLE 1,Test 4: Market Analysis
# MAGIC %md
# MAGIC ## Test 4: Market Analysis

# COMMAND ----------

# DBTITLE 1,Test 4 run
print("Test 4: Analyse du marché\n")
print("User: Quelles sont les tendances du marché?\n")

response = await run_agent(
    "Quelles sont les tendances du marché de l'emploi data à Paris? Combien d'offres CDI sont disponibles?"
)

print(f"Agent: {response}\n")
print("="*60 + "\n")

# COMMAND ----------

# DBTITLE 1,Agent Configuration
# MAGIC %md
# MAGIC ## Agent Configuration
# MAGIC
# MAGIC ⚠ Originally this section passed `agent_config` to the next notebook via `dbutils.jobs.taskValues.set` — that was broken twice over: task values only work inside job runs, and they only accept primitive values (a dict fails). `04_test_agent.py` builds its own agent instance, so nothing needs to be passed — the config is kept here for reference.

# COMMAND ----------

# DBTITLE 1,Agent config dict
# Agent configuration (kept for reference / the Streamlit app in 04_app).
# NOT passed via dbutils.jobs.taskValues — see the note above.
agent_config = {
    'model_service': 'system.ai.meta-llama-3-3-70b-instruct',
    'llm_api': f"{workspace_client.config.host.rstrip('/')}/ai-gateway/mlflow/v1",  # Chat Completions (Unity Gateway)
    'mcp_base_url': f"{workspace_client.config.host.rstrip('/')}/api/2.0/mcp/functions/main/job_hunting_tools",  # append /{function_name} per tool
    'system_prompt': SYSTEM_PROMPT
}

print("✅ Agent configuration ready (04_test_agent.py builds its own agent instance)")

# COMMAND ----------

# DBTITLE 1,Summary
print("\n" + "="*60)
print("✅ AI AGENT READY")
print("="*60)
print(f"Model: system.ai.meta-llama-3-3-70b-instruct")
print(f"Tools: {len(tools)}")
print(f"Language: French")
print("="*60)