"""GenAI semantic-convention attribute names, in one place.

As of 2026 the GenAI conventions were moved out of the main semantic-conventions
repository into a dedicated one, where nothing is marked Stable and there is no
tagged release — so there is no schema URL to pin against. The names have
already moved once: ``gen_ai.system`` became ``gen_ai.provider.name``, and
``prompt_tokens``/``completion_tokens`` became ``input_tokens``/``output_tokens``.

Two consequences drive this module:

1. Both provider generations are emitted, so a dashboard written against either
   name keeps working. This is cheap: one extra low-cardinality attribute.
2. Every name lives here, so the next rename is a single edit rather than a
   search through service code.

Token usage and finish reason are NOT set here. The botocore instrumentation
already emits them on its own span for ``bedrock-runtime.converse()``;
duplicating them would give model attributes two sources of truth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.trace import Span

# Current names.
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"

# Deprecated, emitted alongside the current name for dashboard compatibility.
GEN_AI_SYSTEM_DEPRECATED = "gen_ai.system"

PROVIDER_AWS_BEDROCK = "aws.bedrock"
OPERATION_CHAT = "chat"

# Domain attributes: what only this application knows about the call.
BRIEFING_SOURCE = "briefing.source"
BRIEFING_CACHE_HIT = "briefing.cache_hit"
ELEVATOR_ID = "elevator.id"
ELEVATOR_RISK_LEVEL = "elevator.risk_level"


def set_model_identity(span: Span, *, model_id: str) -> None:
    """Record which model was asked, under both provider attribute generations."""
    span.set_attribute(GEN_AI_OPERATION_NAME, OPERATION_CHAT)
    span.set_attribute(GEN_AI_PROVIDER_NAME, PROVIDER_AWS_BEDROCK)
    span.set_attribute(GEN_AI_SYSTEM_DEPRECATED, PROVIDER_AWS_BEDROCK)
    span.set_attribute(GEN_AI_REQUEST_MODEL, model_id)


def set_briefing_outcome(span: Span, *, source: str, cache_hit: bool) -> None:
    """Record how the briefing was produced.

    `source` is the single most useful attribute on this span: a Bedrock outage
    is otherwise invisible, because the deterministic fallback still returns
    HTTP 200 and a plausible briefing.
    """
    span.set_attribute(BRIEFING_SOURCE, source)
    span.set_attribute(BRIEFING_CACHE_HIT, cache_hit)


# Deliberately not recorded: `gen_ai.input.messages` and
# `gen_ai.output.messages`. The briefing prompt embeds fleet risk data,
# technician names and free-text visit notes; recording it would ship all of
# that to whatever backend the Collector exports to. This omission is a
# decision, not an oversight — do not "complete" the instrumentation by adding
# them.
