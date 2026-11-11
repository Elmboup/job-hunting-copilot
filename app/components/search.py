"""Direct (non-LLM) calls to the job-hunting UC function tools.

Used by the app's search tab and stats sidebar so they don't burn LLM tokens.
"""

import json

TOOL_PREFIX = "main__job_hunting_tools__"


def find_tool(tools, function_name):
    """Return the LangChain tool wrapping main.job_hunting_tools.<function_name>."""
    wanted = f"{TOOL_PREFIX}{function_name}"
    for tool in tools:
        if tool.name == wanted:
            return tool
    raise LookupError(
        f"Tool {wanted} not loaded — available: {[t.name for t in tools]}"
    )


def _parse_tool_result(result):
    """MCP tool results arrive as JSON text, sometimes wrapped in content blocks."""
    candidates = []
    if isinstance(result, str):
        candidates.append(result)
    elif isinstance(result, dict):
        return result
    elif isinstance(result, (list, tuple)):
        candidates.extend(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in result
        )
    elif result is not None:
        candidates.append(str(result))
    for text in candidates:
        text = text.strip()
        if text.startswith("{"):
            return json.loads(text)
    return {"columns": [], "rows": []}


def _rows_as_dicts(payload):
    columns = payload.get("columns", [])
    return [dict(zip(columns, row)) for row in payload.get("rows", [])]


async def call_function(tools, function_name, arguments):
    """Invoke a UC function tool and return its rows as a list of dicts."""
    tool = find_tool(tools, function_name)
    result = await tool.ainvoke(arguments)
    payload = _parse_tool_result(result)
    if not payload.get("rows"):
        return payload  # scalar / empty result — pass through
    return _rows_as_dicts(payload)


async def search_jobs(
    tools,
    user_query,
    location=None,
    contract_type=None,
    remote_only=False,
    max_results=10,
):
    """Semantic job search via main.job_hunting_tools.search_jobs.

    '' and None both mean 'no filter' inside the TVF (nullif guard), so the
    '' values that MCP/LangChain pass for optional params are safe here.
    """
    return await call_function(
        tools,
        "search_jobs",
        {
            "user_query": user_query,
            "location": location or "",
            "remote_only": bool(remote_only),
            "contract_type": contract_type or "",
            "max_results": int(max_results),
        },
    )


async def draft_cover_letter(tools, job_title, company, job_description, user_background):
    """Scalar LLM function — returns the letter text."""
    rows = await call_function(
        tools,
        "draft_cover_letter",
        {
            "job_title": job_title,
            "company": company or "",
            "job_description": job_description or "",
            "user_background": user_background,
        },
    )
    if isinstance(rows, list) and rows:
        first = rows[0]
        return next(iter(first.values()), "")
    return ""
