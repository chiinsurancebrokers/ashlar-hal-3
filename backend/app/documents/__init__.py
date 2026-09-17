"""Document intelligence shared by HAL and Proposal Studio."""

from .bridge import ProposalBridgeResult, apply_proposal_analysis
from .extraction import ExtractionResult, extract_document
from .proposal_adapter import analysis_to_facts
from .quality import assess_result_quality

__all__ = [
    "ExtractionResult",
    "ProposalBridgeResult",
    "analysis_to_facts",
    "apply_proposal_analysis",
    "assess_result_quality",
    "extract_document",
]
