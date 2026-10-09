"""P2-T10 fix 2: Campus no longer changes HRMS's Provident Fund / Professional Tax (or DA / AGP it did not create).
Move Campus's draft salary structures to Campus EPF / Campus PT and undo the earlier one-time wiring where it is safe
(see campus.faculty.payroll_setup.revert_statutory_wiring)."""

from campus.faculty.payroll_setup import revert_statutory_wiring


def execute():
	revert_statutory_wiring()
