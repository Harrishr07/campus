"""M04-09 follow-up (L-03): no cancelled Program Enrollment holds a joining key.

The first joining_gate patch keyed a student's first enrollment even when it was cancelled. An Admitted student
whose only enrollment was cancelled then held the applicant's key on the cancelled row, and their joining
confirmation could never insert its own (the key is unique); a cancelled and amended joining enrollment kept the
key on the cancelled original, so a retried joining refused instead of returning the amendment.

Every key on a cancelled enrollment is cleared, then each applicant's first submitted enrollment is keyed as
joining_gate now does (an amendment is a submitted enrollment of the student, so it takes the key). Idempotent.
"""

import frappe

from campus.patches.joining_gate import key_joining_enrollments


def execute():
	if not frappe.db.has_column("Program Enrollment", "oc_joining_key"):
		return  # joining_gate has not run on this site: it keys only submitted enrollments now
	frappe.db.sql("update `tabProgram Enrollment` set oc_joining_key = null where docstatus = 2 and oc_joining_key is not null")
	key_joining_enrollments()
