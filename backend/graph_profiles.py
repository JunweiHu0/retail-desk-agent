"""Frozen graph ablations. No business policy or model-generated routing here."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GraphProfile:
    tools: str = "b1"
    context: bool = False
    sop: bool = False
    notes: bool = False
    review: bool = False
    guided: bool = False
    preview_names: bool = False


GRAPH_PROFILES = {
    "lg_b1": GraphProfile(),
    "lg_described": GraphProfile("tools_described"),
    "lg_structured": GraphProfile("tools_structured"),
    "lg_extended": GraphProfile("tools_extended"),
    "lg_guided": GraphProfile("tools_extended", context=True, guided=True, preview_names=True),
    "lg_context": GraphProfile("tools_extended", context=True),
    "lg_sop": GraphProfile("tools_extended", context=True, sop=True),
    "lg_notes": GraphProfile("tools_extended", context=True, sop=True, notes=True),
    "lg_review": GraphProfile("tools_extended", context=True, sop=True, notes=True, review=True),
}


def tool_variant(variant):
    profile = GRAPH_PROFILES.get(variant)
    return profile.tools if profile else variant


def uses_preview_names(variant):
    profile = GRAPH_PROFILES.get(variant)
    return bool(profile and profile.preview_names)
