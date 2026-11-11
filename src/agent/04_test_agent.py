# Databricks notebook source
# DBTITLE 1,Test AI Agent — Interactive Demo
# MAGIC %md
# MAGIC # Test AI Agent — Interactive Demo
# MAGIC
# MAGIC Test the agent with various scenarios. This notebook builds its own agent instance (same config as `03_build_agent.py`) so it runs standalone.
# MAGIC
# MAGIC ⚠ The last section is an interactive `input()` loop — run it manually in the notebook UI, never in a scheduled job.

# COMMAND ----------

# DBTITLE 1,Install Dependencies
# NOTE: the default resolver lands on langgraph 1.0.10 + langgraph-prebuilt 1.0.13,
# a symbol-incompatible pair ("cannot import name 'ExecutionInfo' from 'langgraph.runtime'").
# Upgrade the langgraph stack together; langchain-openai provides the ChatOpenAI client
# for the /ai-gateway/mlflow/v1 API (see the agent cell below).
%pip install langgraph databricks-langchain langchain-openai --upgrade "langgraph>=1.1" "langgraph-prebuilt>=1.0"

# COMMAND ----------

# DBTITLE 1,Restart Python (load installed packages)
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Imports
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from databricks_langchain import DatabricksMCPServer, DatabricksMultiServerMCPClient
from databricks.sdk import WorkspaceClient
import asyncio

# COMMAND ----------

# DBTITLE 1,Initialize Agent
# MAGIC %md
# MAGIC ## Initialize Agent (same config as 03_build_agent.py)

# COMMAND ----------

# DBTITLE 1,Build the agent
workspace_client = WorkspaceClient()

# MCP URL pattern (per Databricks docs): /api/2.0/mcp/functions/{catalog}/{schema}/{function_name}
# — slash-separated and PER FUNCTION (a single dot-separated schema-level URL does not work).
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

tools = await mcp_client.get_tools()

SYSTEM_PROMPT = """Tu es un assistant IA spécialisé dans la recherche d'emploi en France. 
Réponds toujours en français. Sois encourageant et donne des conseils concrets."""

# ChatDatabricks 404s on system.ai.* (it calls the classic /serving-endpoints route),
# so use ChatOpenAI against the Unity Gateway /ai-gateway/mlflow/v1 Chat Completions
# API with the notebook session's short-lived OAuth token (same approach as 03_build_agent.py).
auth_token = workspace_client.config.authenticate()["Authorization"].split(" ", 1)[1]

llm = ChatOpenAI(
    model="system.ai.meta-llama-3-3-70b-instruct",  # legacy databricks-llama-3-1 endpoint does not exist; see 03_build_agent.py
    base_url=f"{workspace_client.config.host.rstrip('/')}/ai-gateway/mlflow/v1",
    api_key=auth_token,
)

agent = create_react_agent(
    llm,
    tools=tools,
    prompt=SYSTEM_PROMPT
)

print("✅ Agent initialized")

# COMMAND ----------

# DBTITLE 1,Test User Profile
# MAGIC %md
# MAGIC ## Test User Profile

# COMMAND ----------

# DBTITLE 1,User profile
# Define test user profile
USER_PROFILE = {
    'name': 'Marie Dupont',
    'skills': ['Python', 'Spark', 'SQL', 'Databricks', 'Machine Learning'],
    'experience': '3 ans en data engineering',
    'location': 'Paris',
    'preferences': 'CDI, remote ou hybride, salaire 50-65k€'
}

print("Test User Profile:")
for key, value in USER_PROFILE.items():
    print(f"  {key}: {value}")

# COMMAND ----------

# DBTITLE 1,Scenario Runner
# MAGIC %md
# MAGIC ## Scenario Runner

# COMMAND ----------

# DBTITLE 1,test_scenario helper
async def test_scenario(scenario_name, user_message, user_profile):
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario_name}")
    print(f"{'='*60}\n")
    print(f"👤 User: {user_message}\n")
    
    # Build context
    context = f"\n\nProfil: {user_profile['name']}, {user_profile['experience']}, compétences: {', '.join(user_profile['skills'])}"
    
    # Run agent
    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": user_message + context}]
    })
    
    response = result["messages"][-1].content
    print(f"🤖 Agent:\n{response}\n")
    
    return response

# COMMAND ----------

# DBTITLE 1,Test 1: Basic Job Search
# MAGIC %md
# MAGIC ## Test 1: Basic Job Search ("Recherche d'emploi basique")

# COMMAND ----------

# DBTITLE 1,Test 1 run
await test_scenario(
    "Recherche d'emploi basique",
    "Je cherche un poste de data engineer à Paris en CDI",
    USER_PROFILE
)

# COMMAND ----------

# DBTITLE 1,Test 2: Specific Requirements
# MAGIC %md
# MAGIC ## Test 2: Specific Requirements ("Recherche avec critères spécifiques")

# COMMAND ----------

# DBTITLE 1,Test 2 run
await test_scenario(
    "Recherche avec critères spécifiques",
    "Trouve-moi des postes remote en data engineering, de préférence avec du Spark et du Python",
    USER_PROFILE
)

# COMMAND ----------

# DBTITLE 1,Test 3: Salary Inquiry
# MAGIC %md
# MAGIC ## Test 3: Salary Inquiry ("Question sur les salaires")

# COMMAND ----------

# DBTITLE 1,Test 3 run
await test_scenario(
    "Question sur les salaires",
    "Quels sont les salaires moyens pour un data engineer avec 3 ans d'expérience à Paris?",
    USER_PROFILE
)

# COMMAND ----------

# DBTITLE 1,Test 4: Cover Letter
# MAGIC %md
# MAGIC ## Test 4: Cover Letter ("Génération de lettre de motivation")

# COMMAND ----------

# DBTITLE 1,Test 4 run
await test_scenario(
    "Génération de lettre de motivation",
    "Peux-tu m'aider à rédiger une lettre de motivation pour un poste de Data Engineer Senior?",
    USER_PROFILE
)

# COMMAND ----------

# DBTITLE 1,Test 5: Career Advice
# MAGIC %md
# MAGIC ## Test 5: Career Advice ("Conseil de carrière")

# COMMAND ----------

# DBTITLE 1,Test 5 run
await test_scenario(
    "Conseil de carrière",
    "Je veux évoluer vers un poste de ML Engineer. Quelles compétences dois-je développer?",
    USER_PROFILE
)

# COMMAND ----------

# DBTITLE 1,Interactive Test
# MAGIC %md
# MAGIC ## Interactive Test
# MAGIC
# MAGIC ⚠ `input()` loop — run manually in the notebook UI, never in a scheduled job (it would hang forever waiting for stdin).

# COMMAND ----------

# DBTITLE 1,Interactive loop
# Interactive loop for manual testing
print("🤖 Agent de recherche d'emploi prêt!")
print("Tapez 'quit' pour arrêter\n")

while True:
    user_input = input("👤 Vous: ")
    
    if user_input.lower() in ['quit', 'exit', 'stop']:
        print("Au revoir! 👋")
        break
    
    if not user_input.strip():
        continue
    
    try:
        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": user_input}]
        })
        
        response = result["messages"][-1].content
        print(f"\n🤖 Agent: {response}\n")
        
    except Exception as e:
        print(f"❌ Erreur: {e}\n")

# COMMAND ----------

# DBTITLE 1,Done
print("\n✅ Agent testing complete!")