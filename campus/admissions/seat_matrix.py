"""M04-01 Seat Matrix: sanctioned, allotted, filled and vacant seats per quota and community.

One Seat Matrix per (company, program, academic year). Its rows are (quota, category) pairs.

- `filled` is the number of SUBMITTED Program Enrollments of the program and year with that quota
  (`oc_admission_quota`) and student category. Enforcement always uses the LIVE locked count of the
  enrollments (`live_counts`), never the stored `filled`, which is only a display cache refreshed from the
  live count on enrollment submit/cancel, on matrix save and on recount. It cannot drift into a wrong
  decision (category edits after submit, direct database edits and enrollments made outside the hooks are
  all counted).
- `allotted` is informational (applicants carrying an allotment number); it is read without locks and is
  refreshed on save, on recount, and after an allotment import. Nothing gates on it.
- `vacant` = sanctioned - filled; a negative value means the row was over-admitted by an override.

Concurrency (MariaDB REPEATABLE READ)
Lock order everywhere: the Seat Matrix row FIRST (FOR UPDATE), then the enrollment rows. The matrix is locked in
Program Enrollment before_submit / before_cancel (before Frappe writes the enrollment row), in
`check_seat_available` and in recount. After the lock the enrollments are counted with a LOCKING read
(`FOR UPDATE SKIP LOCKED`), so the count is the latest committed state and not the transaction's stale
snapshot. SKIP LOCKED is the deadlock-safe choice: a plain FOR UPDATE / LOCK IN SHARE MODE would wait for any
enrollment row X-locked by another open transaction (for instance a draft inserted before its own
before_submit asks for the matrix), while that transaction waits for the matrix we hold: a deadlock. A row
that is locked by someone else is uncommitted work of that transaction, which is not part of the committed
count anyway, and a transaction that is submitting or cancelling takes the matrix lock before it touches its
enrollment row, so it cannot be mid-flight while we hold the matrix. `check_seat_available` keeps the lock
until the caller's transaction ends, so check and admit are atomic when the enrollment is created and
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
		["name", "sanctioned"],
		as_dict=True,
		for_update=True,
	)


def vacancy(row, live):
	return (row.sanctioned or 0) - live


def lock_matrix_of(doc, method=None):
	"""Program Enrollment before_submit / before_cancel: take the matrix lock before the enrollment row is written."""
	find_matrix(doc.oc_company, doc.program, doc.academic_year, for_update=True)


def refresh_cache_of(doc, method=None):
	"""Program Enrollment on_submit / on_cancel: refresh the displayed filled counts (the matrix is already locked)."""
	name = find_matrix(doc.oc_company, doc.program, doc.academic_year)
	if name:
		refresh_cache(name, doc.oc_company, doc.program, doc.academic_year)


def refresh_cache(matrix, company, program, academic_year):
	live = live_counts(company, program, academic_year)
	for row in frappe.get_all("Seat Matrix Row", {"parent": matrix}, ["name", "quota", "category", "sanctioned"], limit=0):
		filled = live.get((row.quota, row.category), 0)
		frappe.db.set_value("Seat Matrix Row", row.name, {"filled": filled, "vacant": (row.sanctioned or 0) - filled}, update_modified=False)


def live_counts(company, program, academic_year):
	"""{(quota, category): n} of submitted Program Enrollments by a locking read. Lock the matrix first."""
	table = frappe.qb.DocType("Program Enrollment")
	rows = (
		frappe.qb.from_(table)
		.select(table.oc_admission_quota, table.student_category)
		.where(
			(table.oc_company == company) & (table.program == program) & (table.academic_year == academic_year)
			& (table.docstatus == 1) & table.oc_admission_quota.isnotnull() & (table.oc_admission_quota != "")
			& table.student_category.isnotnull() & (table.student_category != "")
		)
		.for_update(skip_locked=True)
		.run()
	)  # fmt: skip
	return _tally(rows)


def count_filled(company, program, academic_year):
	"""{(quota, category): n} of submitted Program Enrollments (plain read, for the live report)."""
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

	Filled is always the live locked count of submitted enrollments (the form's copy is read-only and may be
	stale); an existing matrix is locked before the count. `recount` is accepted for the Recount button and is
	the same computation.
	"""
	validate_rows(matrix)
	if not matrix.is_new():
		find_locked_name(matrix.name)
	live = live_counts(matrix.company, matrix.program, matrix.academic_year)
	allotted = count_allotted(matrix.program, matrix.academic_year)
	for row in matrix.rows:
		pair = (row.quota, row.category)
		row.filled = live.get(pair, 0)
		row.allotted = allotted.get(pair, 0)
		row.vacant = (row.sanctioned or 0) - row.filled


def find_locked_name(name):
	frappe.db.get_value("Seat Matrix", name, "name", for_update=True)


@frappe.whitelist()
def recount_seat_matrix(name):
	"""Refresh filled (live locked count) and allotted of a matrix; takes the matrix lock first."""
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
	row = matrix and locked_row(matrix, quota, category)  # sanctioned, re-read under the lock
	if not row:
		return True
	live = live_counts(company, program, academic_year).get((quota, category), 0)  # the truth: never the cached filled
	if vacancy(row, live) > 0:
		return True
	if OVERRIDE_ROLE not in frappe.get_roles():
		frappe.throw(
			_("No seat is vacant for {0} / {1} in {2} ({3}); sanctioned {4}, filled {5}.").format(
				quota, category, program, academic_year, row.sanctioned, live
			),
			title=_("Seat Matrix Full"),
		)
	log_override(company, program, academic_year, quota, category, applicant, row, live)
	return "override"


def log_override(company, program, academic_year, quota, category, applicant, row, live):
	frappe.get_doc(
		{
			"doctype": "Seat Override Log", "company": company, "program": program, "academic_year": academic_year,
			"quota": quota, "category": category, "applicant": applicant, "user": frappe.session.user,
			"overridden_on": now_datetime(), "sanctioned": row.sanctioned, "filled": live,
		}
	).insert(ignore_permissions=True)  # fmt: skip
