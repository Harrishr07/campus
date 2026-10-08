"""M02-01 Academic Governance setup, run on install and migrate (idempotent)."""

from campus.academic_governance.seed import mark_confidential, seed_body_types, seed_message_templates


def setup_academic_governance():
	seed_body_types()
	mark_confidential()
	seed_message_templates()
