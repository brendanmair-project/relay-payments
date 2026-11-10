"""The incident lifecycle (api-contract.md): detected -> triaged -> resolved, nothing else."""

DETECTED = "detected"
TRIAGED = "triaged"
RESOLVED = "resolved"
STATUSES = (DETECTED, TRIAGED, RESOLVED)
_ALLOWED = {(DETECTED, TRIAGED), (TRIAGED, RESOLVED)}


def can_transition(current: str, target: str) -> bool:
    return (current, target) in _ALLOWED
