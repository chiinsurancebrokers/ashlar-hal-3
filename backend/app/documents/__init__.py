"""Document intelligence shared by HAL and Proposal Studio."""

from .bridge import ProposalBridgeResult, apply_proposal_analysis
from .extraction import ExtractionResult, extract_document
from .headline import analyze_quote_headlines
from .plan_selector import identify_selected_plan
from .proposal_adapter import analysis_to_facts
from .quality import assess_result_quality

__all__ = [
    "ExtractionResult",
    "ProposalBridgeResult",
    "analysis_to_facts",
    "analyze_quote_headlines",
    "apply_proposal_analysis",
    "assess_result_quality",
    "extract_document",
    "identify_selected_plan",
]
