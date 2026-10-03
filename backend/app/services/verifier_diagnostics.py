from __future__ import annotations

from typing import Any


def verifier_diagnostic(decision: Any) -> dict[str, Any]:
    """Return a log-safe explanation of a verifier decision without applicant PII."""
    issues = getattr(decision, "issues", None) or []
    return {
        "verdict": getattr(decision, "verdict", "UNKNOWN"),
        "safe_action": getattr(decision, "safe_action", None),
        "model_used": bool(getattr(decision, "model_used", False)),
        "model_status": getattr(decision, "model_status", None),
        "issues": [
            {
                "severity": getattr(issue, "severity", None),
                "issue_type": getattr(issue, "issue_type", None),
                "field": getattr(issue, "field", None),
            }
            for issue in issues
        ],
    }
