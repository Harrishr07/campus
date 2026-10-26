"""M04-01 Seat Matrix: sanctioned, allotted, filled and vacant seats per quota and community.

One Seat Matrix per (company, program, academic year). Its rows are (quota, category) pairs.

M04-08 strict mode (Admission Settings `strict_seat_matrix`, on for new installs): a program and year without a
matrix, or a counted quota and category without a row, is refused unless the user holds "Admission Override";
the override is then logged (Seat Override Log, reason No Seat Matrix / No Seat Matrix Row). With strict mode
off such admissions pass unchecked, as before. A full row is refused or logged (reason Row Full) in both modes.
Every override carries the justification the officer typed (M04-09: on the joining confirmation), stored on the log.
No override ever adds a row or changes sanctioned seats. Supernumerary and not-counted quotas are never checked.

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
Lock-order invariant: a transaction that submits, cancels or edits a submitted Program Enrollment, checks a seat
or recounts takes the Seat Matrix row lock (FOR UPDATE on the unique matrix_key; several matrices in
matrix_key order) BEFORE it takes any lock on a Program Enrollment row. `EnrollmentSeatLockMixin`
(extend_doctype_class) does this in submit(), cancel() and save() of a submitted enrollment, before calling
super(): Frappe's own `check_if_latest` runs SELECT ... FOR UPDATE on the enrollment row before any doc-event
hook, so a hook would be too late. `check_seat_available` and the recount lock the matrix first as well.
After the lock, `live_counts` counts submitted enrollments with a BLOCKING locking read (LOCK IN SHARE MODE),
which sees the latest committed rows. It runs on the composite index (oc_company, program, academic_year,
docstatus) that setup creates, so it locks only that program-year's submitted index range, not the table.

Deadlock analysis: a counter waits only for enrollment rows X-locked by another transaction. Every
transaction that holds such a lock through this module took the matrix first, and the matrix is held by the
counter, so it cannot be holding an enrollment row while waiting for the matrix: no cycle. Draft
enrollments (docstatus 0) are outside the counted index range, so inserting or editing drafts never waits for
a count (an insert into the gap next to the range may wait for the counter's commit, but a draft insert holds
nothing the counter needs). Writers that bypass this module (direct SQL, other apps) and then ask for the
matrix can still form a cycle; MariaDB then aborts one transaction with a deadlock error: the failure mode
is an aborted (fail closed) admission, never an undercount. Two such cycles are known, both inside admit and
both resolved by MariaDB aborting one transaction: (1) the naming-series counter row (Series) locked while a
concurrent transaction waits for a gap lock this one holds; (2) the empty index gaps of two programs in the
shared index range, where two counters hold gap locks and each then inserts into the other's gap. Admit
catches the deadlock, rolls back and retries once, then reports "busy, retry" (see admit.admit). SKIP LOCKED was rejected: it silently skips
committed rows locked by others, which undercounts and oversells.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from campus.admissions.setup import OVERRIDE_ROLE

# Seat Override Log reasons
ROW_FULL, NO_MATRIX, NO_ROW = "Row Full", "No Seat Matrix", "No Seat Matrix Row"


def matrix_key(company, program, academic_year):
	return f"{company}::{program}::{academic_year}"


def find_matrix(company, program, academic_year, for_update=False):
	"""Name of the Seat Matrix of the combination, or None. `for_update` takes the row lock."""
	return frappe.db.get_value(
		"Seat Matrix",
		{"matrix_key": matrix_key(company, program, academic_year)},
		"name",
		for_update=for_update,
	)


def counts_in_matrix(quota):
	"""False for quotas outside the sanctioned intake (supernumerary or not counted in the matrix)."""
	flags = frappe.get_cached_value(
		"Admission Quota", quota, ["is_supernumerary", "counts_in_seat_matrix"], as_dict=True
	)
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


def lock_matrices(doc):
	"""Lock the Seat Matrix of the enrollment (and of its stored values, if they differ) in matrix_key order."""
	keys = {matrix_key(doc.oc_company, doc.program, doc.academic_year)}
	if not doc.is_new():
		stored = frappe.db.get_value(
			"Program Enrollment", doc.name, ["oc_company", "program", "academic_year"]
		)
		if stored:
			keys.add(matrix_key(*stored))
	for key in sorted(keys):
		frappe.db.get_value("Seat Matrix", {"matrix_key": key}, "name", for_update=True)


class EnrollmentSeatLockMixin:
	"""Program Enrollment (extend_doctype_class): take the Seat Matrix lock before Frappe locks the enrollment row.

	Covers submit(), cancel(), save() of a submitted enrollment and insert() of an enrollment that is already
	submitted (docstatus 1, e.g. frappe.client.insert). The nested save() inside submit()/cancel() does not lock
	a second time.
	"""

	def insert(self, *args, **kwargs):
		if self.docstatus == 1:
			return self._seat_locked(super().insert, *args, **kwargs)
		return super().insert(*args, **kwargs)

	def submit(self):
		return self._seat_locked(super().submit)

	def cancel(self):
		return self._seat_locked(super().cancel)

	def save(self, *args, **kwargs):
		if self.docstatus == 1 and not self.flags.seat_matrices_locked:
			return self._seat_locked(super().save, *args, **kwargs)
		return super().save(*args, **kwargs)

	def _seat_locked(self, method, *args, **kwargs):
		if not self.flags.seat_matrices_locked:
			lock_matrices(self)
			self.flags.seat_matrices_locked = True
		try:
			return method(*args, **kwargs)
		finally:
			self.flags.seat_matrices_locked = False


def refresh_cache_of(doc, method=None):
	"""Program Enrollment on_submit / on_cancel: refresh the displayed filled counts (the matrix is already locked)."""
	name = find_matrix(doc.oc_company, doc.program, doc.academic_year)
	if name:
		refresh_cache(name, doc.oc_company, doc.program, doc.academic_year)


def refresh_cache(matrix, company, program, academic_year):
	live = live_counts(company, program, academic_year)
	for row in frappe.get_all(
		"Seat Matrix Row", {"parent": matrix}, ["name", "quota", "category", "sanctioned"], limit=0
	):
		filled = live.get((row.quota, row.category), 0)
		frappe.db.set_value(
			"Seat Matrix Row",
			row.name,
			{"filled": filled, "vacant": (row.sanctioned or 0) - filled},
			update_modified=False,
		)


def live_counts(company, program, academic_year):
	"""{(quota, category): n} of submitted Program Enrollments by a blocking locking read. Lock the matrix first."""
	rows = frappe.db.sql(
		"""select oc_admission_quota, student_category from `tabProgram Enrollment`
		where oc_company = %s and program = %s and academic_year = %s and docstatus = 1
			and ifnull(oc_admission_quota, '') != '' and ifnull(student_category, '') != ''
		lock in share mode""",
		(company, program, academic_year),
	)
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
		frappe.db.set_value(
			"Seat Matrix Row",
			row.name,
			"allotted",
			allotted.get((row.quota, row.category), 0),
			update_modified=False,
		)


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
			frappe.throw(
				_("Row {0}: quota {1} is not counted in the seat matrix.").format(row.idx, row.quota)
			)


def check_seat_available(program, academic_year, quota, category, applicant=None, justification=None):
	"""See `campus.admissions.api.check_seat_available`."""
	company = frappe.db.get_value("Program", program, "oc_company")
	if not counts_in_matrix(quota):
		return True
	matrix = find_matrix(company, program, academic_year, for_update=True)
	row = matrix and locked_row(matrix, quota, category)  # sanctioned, re-read under the lock
	if not row:
		return check_unconfigured(
			company, program, academic_year, quota, category, applicant, matrix, justification
		)
	live = live_counts(company, program, academic_year).get(
		(quota, category), 0
	)  # the truth: never the cached filled
	if vacancy(row, live) > 0:
		return True
	require_override(
		_("No seat is vacant for {0} / {1} in {2} ({3}); sanctioned {4}, filled {5}.").format(
			quota, category, program, academic_year, row.sanctioned, live
		),
		_("Seat Matrix Full"),
		justification,
	)
	log_override(
		company,
		program,
		academic_year,
		quota,
		category,
		applicant,
		ROW_FULL,
		row.sanctioned,
		live,
		justification,
	)
	return "override"


def check_unconfigured(company, program, academic_year, quota, category, applicant, matrix, justification):
	"""M04-08: no matrix or no row is allowed outside strict mode; in strict mode only by a logged override."""
	if not strict_mode():
		return True
	if matrix:
		reason = NO_ROW
		message = _("The Seat Matrix of {0} ({1}) has no row for {2} / {3}.").format(
			program, academic_year, quota, category
		)
	else:
		reason = NO_MATRIX
		message = _("No Seat Matrix is set up for {0} ({1}).").format(program, academic_year)
	require_override(message, _("Seat Matrix Not Configured"), justification)
	log_override(company, program, academic_year, quota, category, applicant, reason, 0, 0, justification)
	return "override"


def strict_mode():
	return bool(cint(frappe.db.get_single_value("Admission Settings", "strict_seat_matrix")))


def require_override(message, title, justification):
	"""Refuse unless the user holds the override role and has typed why the override is needed."""
	if OVERRIDE_ROLE not in frappe.get_roles():
		frappe.throw(message, title=title)
	if not (justification or "").strip():
		frappe.throw(_("{0} Type the justification for the seat override.").format(message), title=title)


def log_override(
	company, program, academic_year, quota, category, applicant, reason, sanctioned, filled, justification
):
	"""Record the override. It never changes the matrix: the approved intake stays as sanctioned."""
	frappe.get_doc(
		{
			"doctype": "Seat Override Log", "company": company, "program": program, "academic_year": academic_year,
			"quota": quota, "category": category, "applicant": applicant, "user": frappe.session.user,
			"overridden_on": now_datetime(), "reason": reason, "sanctioned": sanctioned, "filled": filled,
			"justification": justification.strip(),
		}
	).insert(ignore_permissions=True)  # fmt: skip
