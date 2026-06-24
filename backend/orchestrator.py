import json
import logging
import requests
from datetime import datetime
from config import settings
from main import QueryResponse

logger = logging.getLogger(__name__)


async def process_question(question: str) -> QueryResponse:
    """
    Main orchestration pipeline:
    1. Build system prompt with tool schemas
    2. Call Ollama to get tool name + args
    3. Validate arguments
    4. Execute parameterized query
    5. Format answer with Ollama
    6. Return structured response
    """
    try:
        logger.info(f"Starting orchestration for: {question}")

        tool_schemas = get_tool_schemas()
        system_prompt = build_system_prompt(tool_schemas)

        tool_call = await call_llm_for_tool(question, system_prompt)
        logger.info(f"LLM selected tool: {tool_call.get('tool')}")

        if not tool_call or "error" in tool_call:
            return QueryResponse(error=tool_call.get("error", "Failed to parse LLM response"))

        return QueryResponse(error="Orchestrator placeholder - Phase 0 in progress")

    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
        return QueryResponse(error=str(e))


def get_tool_schemas() -> list[dict]:
    """Get JSON schemas for all available functions (to be implemented)"""
    return []


def build_system_prompt(tool_schemas: list[dict]) -> str:
    """Build the system prompt for the LLM with tool definitions"""
    schema_json = json.dumps(tool_schemas, indent=2)
    return f"""You are a helpful assistant that translates natural language questions into structured function calls.

You have access to the following tools:

{schema_json}

When given a question, respond with ONLY a valid JSON object in this format:
{{
  "tool": "<tool_name>",
  "args": {{
    "arg1": "value1",
    "arg2": "value2"
  }}
}}

Never respond with anything other than valid JSON. If you cannot determine the right tool, respond with:
{{"error": "Unable to understand the question or map to available tools"}}
"""


async def call_llm_for_tool(question: str, system_prompt: str) -> dict:
    """Call Ollama to translate question into a tool call"""
    try:
        payload = {
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "stream": False,
            "format": "json",
        }

        response = requests.post(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        content = result.get("message", {}).get("content", "")

        tool_call = json.loads(content)
        return tool_call

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        return {"error": "LLM returned invalid JSON"}
    except requests.RequestException as e:
        logger.error(f"LLM request failed: {e}")
        return {"error": f"LLM service error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error calling LLM: {e}")
        return {"error": str(e)}


async def format_answer(result: dict, rows: list[dict]) -> str:
    """Call LLM to format the result into a natural language answer (Phase 1)"""
    return "Answer formatting - Phase 1 in progress"
