"""M02-01 Academic Governance setup, run on install and migrate (idempotent)."""

from campus.academic_governance.seed import seed_body_types


def setup_academic_governance():
	seed_body_types()
