"""Proposal Studio engine embedded inside Ashlar HAL.

This package is adapted from the standalone Ashlar Proposal Studio. It keeps
Proposal Studio's client-analysis, report schema, PDF and PowerPoint renderers,
while taking its case state from the shared AshlarCase/FactLedger architecture.
"""

from .engine import ProposalBundle, ProposalGenerationBlocked, generate_case_proposal
from .report_schema import ClientReportValidationError, validate_client_report

__all__ = [
    "ProposalBundle",
    "ProposalGenerationBlocked",
    "generate_case_proposal",
    "ClientReportValidationError",
    "validate_client_report",
]
