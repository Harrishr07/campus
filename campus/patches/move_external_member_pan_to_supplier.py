"""M02-01 Move PAN stored on External Member to the Supplier (Accounts owns it); also revert unedited unsourced Body Type seed values."""

from campus.academic_governance.external_member_pan import move_stored_pan_to_suppliers
from campus.academic_governance.seed import revert_unsourced_values


def execute():
	move_stored_pan_to_suppliers()
	revert_unsourced_values()
