"""W3C trace context (`traceparent`, `tracestate`) carried producer -> posting service -> outbox -> Kafka headers.

A small, tested stand-in until Milestone 4 wires the OpenTelemetry SDK, whose propagator reads and writes the same
headers, so no event or table changes then. Format: https://www.w3.org/TR/trace-context/ (version 00).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping

TRACEPARENT = re.compile(r"00-(?P<trace>[0-9a-f]{32})-(?P<span>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})")
_ZERO_TRACE, _ZERO_SPAN = "0" * 32, "0" * 16


def is_valid(traceparent: str | None) -> bool:
    match = TRACEPARENT.fullmatch(traceparent or "")
    return bool(match) and match["trace"] != _ZERO_TRACE and match["span"] != _ZERO_SPAN  # type: ignore[index]


def new_traceparent(token_hex: Callable[[int], str] = secrets.token_hex) -> str:
    """Start a new trace (sampled)."""
    return f"00-{token_hex(16)}-{token_hex(8)}-01"


def child(traceparent: str | None, token_hex: Callable[[int], str] = secrets.token_hex) -> str:
    """Same trace, new span: what the next hop sends on. An invalid or missing parent starts a new trace."""
    match = TRACEPARENT.fullmatch(traceparent or "")
    if not match or not is_valid(traceparent):
        return new_traceparent(token_hex)
    return f"00-{match['trace']}-{token_hex(8)}-{match['flags']}"


def trace_id(traceparent: str | None) -> str | None:
    match = TRACEPARENT.fullmatch(traceparent or "")
    return match["trace"] if match and is_valid(traceparent) else None


def context_from_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """What to store with an outbox row: the incoming traceparent (if valid) and tracestate."""
    context = {}
    if is_valid(headers.get("traceparent")):
        context["traceparent"] = headers["traceparent"]
        if headers.get("tracestate"):
            context["tracestate"] = headers["tracestate"][:512]  # W3C limit
    return context


def kafka_headers(context: Mapping[str, str], token_hex: Callable[[int], str] = secrets.token_hex) -> dict[str, str]:
    """Headers for the outgoing message: a child span of the stored context, and the tracestate passed on."""
    out = {"traceparent": child(context.get("traceparent"), token_hex)}
    if context.get("tracestate"):
        out["tracestate"] = context["tracestate"]
    return out
