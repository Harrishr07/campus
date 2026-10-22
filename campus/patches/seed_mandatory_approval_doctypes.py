"""NFR Mandatory approval (R-07): list the sensitive document types that must never submit without a matching
Approval Policy in Campus Settings. Runs once, so a college's later edits to the list stand. DML only."""

from campus.campus_platform.mandatory_approval import seed_mandatory_approval


def execute():
	seed_mandatory_approval()
