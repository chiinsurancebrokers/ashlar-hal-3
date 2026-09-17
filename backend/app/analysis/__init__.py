"""Grounded comparison and advisory payloads for Ashlar Adviser OS."""

from .client_comparison import (
    build_client_report_prompt,
    build_comparison_matrix,
    build_grounded_case_payload,
    validate_client_report,
)

__all__ = [
    "build_client_report_prompt",
    "build_comparison_matrix",
    "build_grounded_case_payload",
    "validate_client_report",
]
