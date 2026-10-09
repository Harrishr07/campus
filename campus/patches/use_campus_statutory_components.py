"""P2-T10 fix 2: Campus no longer changes HRMS's Provident Fund / Professional Tax (or DA / AGP it did not create).
Move Campus's draft salary structures to Campus EPF / Campus PT, leave every HRMS and college component as it is, print
what the earlier one-time wiring changed for manual review, and clear its flag (campus.faculty.payroll_setup.retire_statutory_wiring)."""

from campus.faculty.payroll_setup import retire_statutory_wiring


def execute():
	retire_statutory_wiring()
