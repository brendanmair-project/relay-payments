"""Rule-based payment explainer, the always-available fallback (REL-24, ADR-0005)."""

from app.explain.rules import PATTERNS, ExplainEvent, Explanation, explain

__all__ = ["PATTERNS", "ExplainEvent", "Explanation", "explain"]
