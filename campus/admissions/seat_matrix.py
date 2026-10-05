"""M04-01 Seat Matrix: sanctioned, allotted, filled and vacant seats per quota and community.

One Seat Matrix per (company, program, academic year). Its rows are (quota, category) pairs.

- `filled` is the number of SUBMITTED Program Enrollments of the program and year with that quota
  (`oc_admission_quota`) and student category. It is kept current by adjusting the row by one on Program
  Enrollment submit and cancel (`on_enrollment_submit` / `on_enrollment_cancel`), and `recount_filled`
  rebuilds it from the enrollments (new rows, and the Recount button).
- `allotted` is informational (applicants carrying an allotment number); it is read without locks and is
  refreshed on save, on recount, and after an allotment import. Nothing gates on it.
- `vacant` = sanctioned - filled; a negative value means the row was over-admitted by an override.

Concurrency (MariaDB REPEATABLE READ)
Every writer of `filled` first locks the Seat Matrix row (FOR UPDATE) and then re-reads the matrix row with a
locking read, so concurrent submits and cancels serialise on the matrix and never lose an update. Counting
enrolments under that lock was rejected: a locking read of the enrolment table would wait for the other
transaction's freshly submitted enrolment while that transaction waits for the matrix, a deadlock. The
incremental adjustment touches only the matrix rows. `check_seat_available` (api) takes the same lock and keeps
it until the caller's transaction ends, so check and admit are atomic as long as the enrolment is created and
submitted in the same transaction.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from campus.admissions.setup import OVERRIDE_ROLE


def matrix_key(company, program, academic_year):
	return f"{company}::{program}::{academic_year}"


def find_matrix(company, program, academic_year, for_update=False):
	"""Name of the Seat Matrix of the combination, or None. `for_update` takes the row lock."""
	return frappe.db.get_value(
		"Seat Matrix", {"matrix_key": matrix_key(company, program, academic_year)}, "name", for_update=for_update
	)


def counts_in_matrix(quota):
	"""False for quotas outside the sanctioned intake (supernumerary or not counted in the matrix)."""
	flags = frappe.get_cached_value("Admission Quota", quota, ["is_supernumerary", "counts_in_seat_matrix"], as_dict=True)
	return bool(flags) and not flags.is_supernumerary and bool(flags.counts_in_seat_matrix)


def locked_row(matrix, quota, category):
	"""The (quota, category) row of the matrix as read by a locking read, or None. Lock the matrix first."""
	return frappe.db.get_value(
		"Seat Matrix Row",
		{"parent": matrix, "quota": quota, "category": category},
		["name", "sanctioned", "filled"],
		as_dict=True,
		for_update=True,
	)


def vacancy(row):
	return (row.sanctioned or 0) - (row.filled or 0)


def adjust_filled(company, program, academic_year, quota, category, delta):
	"""Add `delta` to the filled count of the row, under the matrix lock; a no-op without a matching row."""
	if not (quota and category):
		return
	matrix = find_matrix(company, program, academic_year, for_update=True)
	if not matrix:
		return
	row = locked_row(matrix, quota, category)
	if not row:
		return
	filled = max((row.filled or 0) + delta, 0)
	frappe.db.set_value(
		"Seat Matrix Row", row.name, {"filled": filled, "vacant": (row.sanctioned or 0) - filled}, update_modified=False
	)


def on_enrollment_submit(doc, method=None):
	adjust_filled(doc.oc_company, doc.program, doc.academic_year, doc.get("oc_admission_quota"), doc.student_category, 1)


def on_enrollment_cancel(doc, method=None):
	adjust_filled(doc.oc_company, doc.program, doc.academic_year, doc.get("oc_admission_quota"), doc.student_category, -1)


def count_filled(company, program, academic_year):
	"""{(quota, category): n} of submitted Program Enrollments (plain read: see the module note)."""
	rows = frappe.get_all(
		"Program Enrollment",
		filters={"oc_company": company, "program": program, "academic_year": academic_year, "docstatus": 1,
			"oc_admission_quota": ("is", "set"), "student_category": ("is", "set")},
		fields=["oc_admission_quota", "student_category"],
		limit=0,
	)  # fmt: skip
	return _tally((r.oc_admission_quota, r.student_category) for r in rows)


def count_allotted(program, academic_year):
	"""{(quota, category): n} of applicants with an allotment number that are not rejected (plain read)."""
	rows = frappe.get_all(
		"Student Applicant",
		filters={"program": program, "academic_year": academic_year, "oc_allotment_no": ("is", "set"),
			"application_status": ("!=", "Rejected"), "oc_admission_quota": ("is", "set"), "student_category": ("is", "set")},
		fields=["oc_admission_quota", "student_category"],
		limit=0,
	)  # fmt: skip
	return _tally((r.oc_admission_quota, r.student_category) for r in rows)


def _tally(pairs):
	counts = {}
	for pair in pairs:
		counts[pair] = counts.get(pair, 0) + 1
	return counts


def prepare_rows(matrix, recount=False):
	"""Validate the rows and set allotted, filled and vacant on save.

	Filled of existing rows is the value stored in the database, read after locking the matrix: the form's
	copy may be stale and filled is read-only. New rows (and every row on `recount`) are counted from the
	enrolments. The count is a plain read; it is a repair path, run while no admissions are in flight.
	"""
	validate_rows(matrix)
	stored = {}
	if not matrix.is_new():
		find_locked_name(matrix.name)
		table = frappe.qb.DocType("Seat Matrix Row")
		rows = frappe.qb.from_(table).select(table.quota, table.category, table.filled).where(table.parent == matrix.name).for_update().run()
		stored = {(quota, category): filled or 0 for quota, category, filled in rows}
	enrolled = count_filled(matrix.company, matrix.program, matrix.academic_year) if recount or len(stored) < len(matrix.rows) else {}
	allotted = count_allotted(matrix.program, matrix.academic_year)
	for row in matrix.rows:
		pair = (row.quota, row.category)
		row.filled = enrolled.get(pair, 0) if recount or pair not in stored else stored[pair]
		row.allotted = allotted.get(pair, 0)
		row.vacant = (row.sanctioned or 0) - row.filled


def find_locked_name(name):
	frappe.db.get_value("Seat Matrix", name, "name", for_update=True)


@frappe.whitelist()
def recount_seat_matrix(name):
	"""Rebuild filled and allotted of a matrix from the Program Enrollments and applicants (repair tool)."""
	frappe.has_permission("Seat Matrix", "write", name, throw=True)
	matrix = frappe.get_doc("Seat Matrix", name)
	matrix.flags.recount = True
	matrix.save()
	return {"filled": sum(r.filled for r in matrix.rows)}


def refresh_allotted(company, program, academic_year):
	"""Refresh the informational allotted counts of the matrix of a program and year, if there is one."""
	name = find_matrix(company, program, academic_year)
	if not name:
		return
	allotted = count_allotted(program, academic_year)
	for row in frappe.get_all("Seat Matrix Row", {"parent": name}, ["name", "quota", "category"], limit=0):
		frappe.db.set_value("Seat Matrix Row", row.name, "allotted", allotted.get((row.quota, row.category), 0), update_modified=False)


def validate_rows(matrix):
	seen = set()
	for row in matrix.rows:
		pair = (row.quota, row.category)
		if pair in seen:
			frappe.throw(_("Row {0}: {1} / {2} is listed twice.").format(row.idx, row.quota, row.category))
		seen.add(pair)
		if (row.sanctioned or 0) < 0:
			frappe.throw(_("Row {0}: sanctioned seats cannot be negative.").format(row.idx))
		if not frappe.db.get_value("Admission Quota", row.quota, "counts_in_seat_matrix"):
			frappe.throw(_("Row {0}: quota {1} is not counted in the seat matrix.").format(row.idx, row.quota))


def check_seat_available(program, academic_year, quota, category, applicant=None):
	"""See `campus.admissions.api.check_seat_available`."""
	company = frappe.db.get_value("Program", program, "oc_company")
	if not counts_in_matrix(quota):
		return True
	matrix = find_matrix(company, program, academic_year, for_update=True)
	row = matrix and locked_row(matrix, quota, category)  # re-read under the lock: a plain read could be stale
	if not row or vacancy(row) > 0:
		return True
	if OVERRIDE_ROLE not in frappe.get_roles():
		frappe.throw(
			_("No seat is vacant for {0} / {1} in {2} ({3}); sanctioned {4}, filled {5}.").format(
				quota, category, program, academic_year, row.sanctioned, row.filled
			),
			title=_("Seat Matrix Full"),
		)
	log_override(company, program, academic_year, quota, category, applicant, row)
	return "override"


def log_override(company, program, academic_year, quota, category, applicant, row):
	frappe.get_doc(
		{
			"doctype": "Seat Override Log", "company": company, "program": program, "academic_year": academic_year,
			"quota": quota, "category": category, "applicant": applicant, "user": frappe.session.user,
			"overridden_on": now_datetime(), "sanctioned": row.sanctioned, "filled": row.filled,
		}
	).insert(ignore_permissions=True)  # fmt: skip
