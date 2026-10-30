
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.agents.tools import TOOLS, invoke_tool
from backend.database.connection import get_db


# ==========================================
# CONFIGURATION
# ==========================================

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

MAX_STEPS = 8

REQUIRED_READS = {
    "get_open_needs",
    "get_policy",
    "get_purchase_orders"
}


# ==========================================
# SYSTEM INSTRUCTIONS
# ==========================================

SYSTEM_INSTRUCTIONS = """
You are ChainPilot, an autonomous procurement
AI agent for a laptop manufacturing factory.

Your mission:
1. Inspect uncovered inventory shortages.
2. Read the current company policy.
3. Check existing purchase orders.
4. Compare suppliers when shortages exist.
5. Initiate permitted procurement when needed.
6. Explain your actions and decisions.

Rules:
- Never invent business data.
- Retrieve inventory, policy, and orders using tools.
- Use rank_suppliers to compare supplier options.
- Never approve your own orders.
- Never knowingly order the same shortage twice.
- Never bypass backend procurement rules.
- The backend enforces financial and approval limits.
- If no action is necessary, explain why.
- Keep your final summary concise.

A delayed order still covers its outstanding quantity.
Do not create a replacement unless the original commitment
is cancelled or reduced.

If a supplier cancels or partially fulfills an order,
investigate the uncovered quantity and available alternatives.

Only confirmed warehouse receipt increases physical stock.
"""


# ==========================================
# ACTIVITY LOG
# ==========================================

def log_agent_action(action, details):
    with get_db() as db:
        db.execute(
            """
            INSERT INTO agent_logs (
                timestamp, action, details
            )
            VALUES (?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                action,
                json.dumps(details, default=str)
            )
        )


# ==========================================
# TOOL DECLARATIONS
# ==========================================

def build_gemini_tools():
    declarations = []

    for tool in TOOLS:
        schema = dict(tool["parameters"])
        schema.pop("additionalProperties", None)

        declaration = types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=schema
        )

        declarations.append(declaration)

    return [
        types.Tool(
            function_declarations=declarations
        )
    ]


# ==========================================
# AGENT EXECUTION
# ==========================================

def run_supply_agent():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is missing from .env"
        )

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=60000
        )
    )

    history = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(
                    text=(
                        "Evaluate the factory's procurement "
                        "needs. Inspect inventory, company "
                        "policy and existing orders. "
                        "Compare suppliers for uncovered "
                        "shortages, request permitted "
                        "procurement, and summarize the result."
                    )
                )
            ]
        )
    ]

    trace = []
    inspected = set()
    procurement_called = False

    started = time.monotonic()

    print(
        "[ChainPilot] Agent started",
        flush=True
    )

    try:
        for step in range(1, MAX_STEPS + 1):

            print(
                f"[ChainPilot] Step {step}/{MAX_STEPS}: "
                "contacting Gemini...",
                flush=True
            )

            response = client.models.generate_content(
                model=MODEL,
                contents=history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTIONS,
                    tools=build_gemini_tools(),
                    temperature=0.2
                )
            )

            print(
                "[ChainPilot] Gemini responded",
                flush=True
            )

            if not response.candidates:
                return {
                    "status": "incomplete",
                    "summary": "No response candidate.",
                    "trace": trace
                }

            model_content = response.candidates[0].content

            if model_content is None:
                return {
                    "status": "incomplete",
                    "summary": "No model content.",
                    "trace": trace
                }

            # Preserve Gemini's original model response.
            # This also preserves thought signatures
            # associated with tool calls.
            history.append(model_content)

            calls = response.function_calls or []

            # ----------------------------------
            # FINAL ANSWER
            # ----------------------------------

            if not calls:
                summary = (
                    response.text
                    or "Agent evaluation completed."
                )

                log_agent_action(
                    "agent_completed",
                    {
                        "summary": summary,
                        "tools_used": len(trace)
                    }
                )

                return {
                    "status": "completed",
                    "model": MODEL,
                    "summary": summary,
                    "trace": trace,
                    "elapsed_seconds": round(
                        time.monotonic() - started, 2
                    )
                }

            tool_responses = []

            # ----------------------------------
            # EXECUTE REQUESTED TOOLS
            # ----------------------------------

            for call in calls:
                name = call.name
                args = dict(call.args or {})

                print(
                    f"[ChainPilot] Tool: {name}",
                    flush=True
                )

                try:
                    if name == "execute_procurement":

                        if procurement_called:
                            result = {
                                "error": (
                                    "Procurement already evaluated "
                                    "during this run."
                                )
                            }

                        elif not REQUIRED_READS.issubset(
                            inspected
                        ):
                            result = {
                                "error": (
                                    "Inspect inventory, policy "
                                    "and existing orders first."
                                )
                            }

                        else:
                            # Mark as called before performing
                            # a state-changing operation.
                            procurement_called = True

                            result = invoke_tool(
                                name, args
                            )

                    else:
                        result = invoke_tool(
                            name, args
                        )

                        if name in REQUIRED_READS:
                            inspected.add(name)

                except Exception as exc:
                    result = {
                        "error": str(exc)
                    }

                    print(
                        "[ChainPilot] Tool failed:",
                        type(exc).__name__,
                        flush=True
                    )

                # ----------------------------------
                # LOG REAL TOOL ACTION
                # ----------------------------------

                event = {
                    "step": step,
                    "tool": name,
                    "arguments": args,
                    "result": result
                }

                trace.append(event)

                log_agent_action(
                    "agent_tool_call",
                    event
                )

                # Gemini function result
                tool_responses.append(
                    types.Part.from_function_response(
                        name=name,
                        response={
                            "result": result
                        }
                    )
                )

            # IMPORTANT:
            # Using role="user" here avoids the
            # unsupported role="tool" error we
            # observed with your Gemini endpoint.
            history.append(
                types.Content(
                    role="user",
                    parts=tool_responses
                )
            )

        return {
            "status": "max_steps_reached",
            "model": MODEL,
            "summary": (
                "Agent reached its maximum number "
                "of steps."
            ),
            "trace": trace,
            "elapsed_seconds": round(
                time.monotonic() - started, 2
            )
        }

    finally:
        client.close()


def _background_agent(context):
    """
    Run Gemini after a supplier or inventory event.
    Errors are logged without changing the
    successful supplier-event transaction.
    """
    try:
        log_agent_action(
            "agent_triggered_automatically",
            {"context": context}
        )

        # Reuse the working Gemini agent.
        run_supply_agent()

    except Exception as exc:
        import logging

        logging.exception(
            "Automatic ChainPilot agent failed"
        )

        log_agent_action(
            "agent_failed",
            {
                "context": context,
                "error_type": type(exc).__name__
            }
        )


def trigger_agent_if_enabled(
    background_tasks,
    flag,
    context
):
    enabled = os.getenv(
        flag,
        "true"
        if flag == "AUTO_AGENT_ON_EVENTS"
        else "false"
    )

    if enabled.strip().lower() not in (
        "true",
        "yes",
        "1",
        "on"
    ):
        return False

    if not os.getenv("GEMINI_API_KEY"):
        return False

    background_tasks.add_task(
        _background_agent,
        context
    )

    return True

