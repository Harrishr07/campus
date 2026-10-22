"""P2-T03 Meeting resolution and agenda rows referenced proposals as plain text; clear the references to no proposal."""

from campus.academic_governance.setup import clear_stale_proposal_references


def execute():
	clear_stale_proposal_references()
