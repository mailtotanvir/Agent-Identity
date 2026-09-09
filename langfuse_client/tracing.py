"""Langfuse SDK v2 wrapper: trace init, node spans, LLM generation + cost."""

import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# USD per 1K tokens. Vertex Gemini Flash pricing (text, standard context).
COST_PER_1K = {
    "gemini-3.7-flash": {"prompt": 0.000075, "completion": 0.000300},
    "gpt-4o-mini": {"prompt": 0.000150, "completion": 0.000600},
    "gpt-4o": {"prompt": 0.002500, "completion": 0.010000},
}

_client = None


def _get_client():
    global _client
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com"),
        )
    return _client


def init_trace(run_id: str, task_topic: str):
    """Create the run trace. Returns (trace, trace_id, trace_url)."""
    trace_id = uuid.uuid4().hex
    trace = _get_client().trace(
        id=trace_id,
        name="agent-identity-gateway",
        metadata={
            "run_id": run_id,
            "task_topic": task_topic,
            "auth0_client_id": os.environ.get("AUTH0_CLIENT_ID", ""),
        },
    )
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    return trace, trace_id, f"{host}/trace/{trace_id}"


@contextmanager
def node_span(trace, node_name: str):
    """Open a Langfuse span around a graph node; records errors on exit."""
    span = trace.span(name=node_name, start_time=datetime.now(timezone.utc))
    try:
        yield span
    except Exception as exc:
        span.end(level="ERROR", status_message=str(exc)[:500])
        raise
    else:
        span.end()


def record_llm_call(
    trace,
    node_name: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    input_text: str,
    output_text: str,
) -> float:
    """Log a generation to Langfuse and return its cost in USD."""
    pricing = COST_PER_1K.get(model, {"prompt": 0.0, "completion": 0.0})
    cost = (prompt_tokens / 1000) * pricing["prompt"] + (
        completion_tokens / 1000
    ) * pricing["completion"]
    trace.generation(
        name=f"{node_name}-llm",
        model=model,
        input=input_text,
        output=output_text,
        usage={
            "input": prompt_tokens,
            "output": completion_tokens,
            "unit": "TOKENS",
        },
        metadata={"cost_usd": round(cost, 6)},
    )
    return cost


def flush():
    if _client is not None:
        _client.flush()
