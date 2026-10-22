"""M06-10 University result import (Affiliated mode): University Result Import.

Flow (COE): an import of an Affiliated Exam Session in an Import format with the university's result file (private)
is previewed (`validate_import`): every file row becomes a University Result Import Row - Valid, Correction (it
changes a result already imported), Unchanged (the same result is there already) or Rejected with its reason (a
required cell is blank; no student of the college has the university register number; the course code is not mapped
to one of our courses; the row repeats an earlier row's student and course; the student is not registered for the
course in this session; the grade or result is not in the code mapping and the student's Grading Scheme; a mark is not
a number). Nothing is written to the results. `start_import` (refused while a Correction row has no correction reason)
queues one bulk item per student (queue long, chunk 1).

Each student's import rows are written to the same Student Result our published results use (one per student and
session), so transcripts, arrears, progression, graduation and attainment read them like any other: course rows with
the grade, the grade point from the student's Grading Scheme, credits and type from the course offering (an arrear's
from its earlier attempt), SGPA / CGPA / arrears computed as the Result Run does; source University and the import as
its reference. A first result is version 1. The same rows again change nothing (Unchanged). A changed result is never
overwritten: it becomes a new version linked to the one it replaces, with its change log and the correction reason,
and only the new one is the latest.

The first import that writes a result publishes the session (publish_at = the import's Result Date, else now); later
imports leave it published. A run that ends with rows still waiting (a lost transaction) is finished by `reconcile`
(hourly): those rows become Error rows asking for a new import, so an import never stays Importing.
"""

import hashlib
import json

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cstr, flt, get_datetime, getdate, now_datetime
from frappe.utils.file_manager import get_file

from campus.campus_platform.api import get_regulation, get_rule
from campus.campus_platform.bulk import run_bulk
from campus.examinations import result_rules, results, rules, university_files
from campus.examinations.access import COE_ROLE
from campus.examinations.affiliation import AFFILIATED, UNIVERSITY_REGISTER_FIELD
from campus.examinations.arrears import outstanding_arrears
from campus.examinations.courses import offering_course

IMPORT, ROW, RESULT = "University Result Import", "University Result Import Row", "Student Result"
HANDLER = "campus.examinations.university_import.import_student"
KEY = "campus.examinations.university_import.item_key"
VALID, CORRECTION, UNCHANGED, REJECTED, IMPORTED, ERROR = "Valid", "Correction", "Unchanged", "Rejected", "Imported", "Error"
QUEUED = (VALID, CORRECTION)
WRITTEN = (IMPORTED, UNCHANGED)
SPECIAL_GRADES = {"AB": "AB", "SA": "SA", **{code: "WD" for code in rules.WITHDRAWAL_CODES}}
COMPARED = ("grade", "result", "cia", "ese", "total")
SAVEPOINT = "university_import_student"
UNIVERSITY = "University"


@frappe.whitelist(methods=["POST"])
def validate_import(name):
	"""Preview the file: one University Result Import Row per file row with its status; returns {status: count}."""
	doc = locked_import(name, ("Draft", "Validated"), _("This import has already been started."))
	fmt = frappe.get_doc("University Exam Format", doc.import_format)
	content = read_private_file(doc.result_file)
	records = university_files.parse_file(fmt, doc.result_file, content)
	frappe.db.delete(ROW, {"university_result_import": name})
	check = RowCheck(doc, fmt)
	for row_no, values in records:
		save_row(doc, row_no, values, check.preview(row_no, values))
	doc.db_set({"status": "Validated", "total_rows": len(records), "file_sha256": hashlib.sha256(content).hexdigest()})
	return refresh_summary(name)


@frappe.whitelist(methods=["POST"])
def start_import(name):
	"""Queue the students of the Valid and Correction rows; returns the Bulk Run name (None when nothing is to write)."""
	doc = locked_import(name, ("Validated",), _("Validate the import first; an import is run once."))
	if frappe.db.exists(ROW, {"university_result_import": name, "status": CORRECTION}) and not (doc.correction_reason or "").strip():
		frappe.throw(_("Some rows change results already imported: give the Correction Reason first."))
	students = frappe.get_all(ROW, {"university_result_import": name, "status": ["in", QUEUED]}, pluck="student", distinct=True, order_by="student")
	frappe.db.set_value(IMPORT, name, "status", "Importing")
	if not students:
		refresh_status(name)
		return None
	items = [{"import": name, "student": student} for student in sorted(students)]
	run = run_bulk("University Result Import", items, HANDLER, chunk=1, key=KEY, parameters={"import": name})
	frappe.db.set_value(IMPORT, name, "bulk_run", run)
	return run


def item_key(item):
	return f"{item['import']}::{item['student']}"


def locked_import(name, statuses, message):
	frappe.only_for((COE_ROLE, "System Manager"))
	frappe.has_permission(IMPORT, "write", name, throw=True)
	if frappe.db.get_value(IMPORT, name, "status", for_update=True) not in statuses:
		frappe.throw(message)
	doc = frappe.get_doc(IMPORT, name)
	doc.check_permission("write")
	return doc


def read_private_file(file_url):
	"""The attached result file's content; it must be a private File the user may read."""
	if not file_url:
		frappe.throw(_("Attach the university's result file first."))
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		frappe.throw(_("The result file {0} was not found.").format(file_url))
	file = frappe.get_doc("File", file_name)
	file.check_permission("read")
	if not file.is_private:
		frappe.throw(_("The result file holds students' results: attach it again as a private file."))
	content = get_file(file_url)[1]
	return content.encode() if isinstance(content, str) else content


# ---- preview ----------------------------------------------------------------------------------


class RowCheck:
	"""Preview of the rows of one import, in file order; earlier rows are remembered to flag repeats."""

	def __init__(self, doc, fmt):
		self.doc, self.codes, self.seen, self.schemes = doc, university_files.CodeMap(fmt), {}, {}

	def preview(self, row_no, values):
		"""{status, message, student, course, grade, result, cia, ese, total} of one row, without writing a result."""
		missing = [s for s in university_files.REQUIRED["Import"] if not values.get(s)]
		if missing:
			return rejected(_("Required: {0}.").format(", ".join(missing)))
		register_no = values["University Register No"]
		student = frappe.db.get_value("Student", {UNIVERSITY_REGISTER_FIELD: register_no, "oc_company": self.doc.company}, "name")
		if not student:
			return rejected(_("No student of this college has university register number {0}.").format(register_no))
		course = self.codes.ours("Course", values["Course Code"])
		if not course or not frappe.db.exists("Course", course):
			return rejected(_("Course code {0} is not mapped to one of our courses.").format(values["Course Code"]), student=student)
		found = {"student": student, "course": course}
		if (student, course) in self.seen:
			return rejected(_("Repeats row {0}.").format(self.seen[(student, course)]), **found)
		self.seen[(student, course)] = row_no
		if not registered_course(student, self.doc.exam_session, course):
			return rejected(_("{0} is not registered for {1} in this session.").format(student, course), **found)
		try:
			found.update(self.outcome(student, values))
		except frappe.ValidationError as error:
			return rejected(frappe.utils.strip_html(str(error)), **found)
		latest = latest_course_row(student, self.doc.exam_session, course)
		if latest and same_outcome(latest, found):
			return {**found, "status": UNCHANGED, "message": _("Already imported.")}
		return {**found, "status": CORRECTION if latest else VALID, "message": _("Changes the imported result.") if latest else None}

	def outcome(self, student, values):
		"""{grade, result, cia, ese, total} of a row: our grade letter, our result and the marks as numbers."""
		grade = self.codes.ours("Grade", values["Grade"])
		if not grade:
			raise frappe.ValidationError(_("Grade {0} is not in the code mapping.").format(values["Grade"]))
		result = self.grade_result(student, grade)
		if result is None:
			raise frappe.ValidationError(_("Grade {0} is not in the student's Grading Scheme.").format(grade))
		if values.get("Result"):
			stated = self.codes.ours("Result", values["Result"])
			if stated not in university_files.RESULT_CODES:
				raise frappe.ValidationError(_("Result {0} is not in the code mapping.").format(values["Result"]))
			if stated != result:
				raise frappe.ValidationError(_("Grade {0} means {1}, but the result says {2}.").format(grade, result, stated))
		marks = {}
		for source, field in (("CIA", "cia"), ("ESE", "ese"), ("Total", "total")):
			text = values.get(source)
			try:
				marks[field] = float(text) if text else 0.0
			except ValueError:
				raise frappe.ValidationError(_("{0} {1} is not a number.").format(source, text)) from None
		return {"grade": grade, "result": result, **marks}

	def grade_result(self, student, grade):
		"""Our result of `grade` in the student's Grading Scheme: Pass / Fail by the grade, AB / SA / WD by the
		code; None when the scheme has neither."""
		letters = self.scheme(student)
		if grade in letters:
			return rules.PASS if letters[grade]["is_pass"] else rules.FAIL
		return SPECIAL_GRADES.get(grade)

	def scheme(self, student):
		regulation = get_regulation(student)
		if regulation not in self.schemes:
			scheme = get_rule(student, "Grading Scheme")
			self.schemes[regulation] = {g.letter: g.as_dict() for g in scheme.grades}
		return self.schemes[regulation]


def rejected(message, **found):
	return {**found, "status": REJECTED, "message": message}


def registered_course(student, exam_session, course):
	"""The student's confirmed, eligible Exam Registration course row of the session ({course_offering, kind}) or None."""
	registration = frappe.db.get_value("Exam Registration", {"exam_session": exam_session, "student": student, "confirmed": 1})
	return registration and frappe.db.get_value(
		"Exam Registration Course",
		{"parent": registration, "parenttype": "Exam Registration", "course": course, "eligibility": "Eligible"},
		["course_offering", "kind"],
		as_dict=True,
	)


def latest_course_row(student, exam_session, course):
	latest = frappe.db.get_value(RESULT, {"student": student, "exam_session": exam_session, "is_latest": 1})
	return latest and frappe.db.get_value(
		"Student Result Course", {"parent": latest, "parenttype": RESULT, "course": course}, list(COMPARED), as_dict=True
	)


def same_outcome(row, found):
	return all(
		(flt(row.get(f)) == flt(found.get(f))) if f in ("cia", "ese", "total") else cstr(row.get(f)) == cstr(found.get(f))
		for f in COMPARED
	)


def save_row(doc, row_no, values, found):
	frappe.get_doc(
		{
			"doctype": ROW, "university_result_import": doc.name, "company": doc.company, "row_no": row_no,
			"university_register_no": cstr(values.get("University Register No"))[:140],
			**{f: found.get(f) for f in ("student", "course", "grade", "result", "cia", "ese", "total")},
			"status": found["status"], "message": cstr(found.get("message"))[:500] or None, "values_json": json.dumps(values),
		}
	).insert(ignore_permissions=True)  # fmt: skip


# ---- import -----------------------------------------------------------------------------------


def import_student(item, run):
	"""Bulk handler: write one student's queued rows to their Student Result; DB-only, no commit."""
	rows = frappe.get_all(
		ROW, {"university_result_import": item["import"], "student": item["student"], "status": ["in", QUEUED]},
		["name", "course", "grade", "result", "cia", "ese", "total"], order_by="row_no",
	)  # fmt: skip
	frappe.db.savepoint(SAVEPOINT)
	try:
		outcome, result = write_result(item["import"], item["student"], rows)
	except frappe.QueryDeadlockError:
		raise  # every savepoint is gone: the runner rolls back and records the item as failed
	except Exception as e:  # noqa: BLE001 - a failing student is recorded, never stalls the import
		frappe.db.rollback(save_point=SAVEPOINT)
		outcome, result = (ERROR, cstr(e)), None
	for row in rows:
		status, message = outcome if isinstance(outcome, tuple) else (outcome.get(row.course, UNCHANGED), None)
		frappe.db.set_value(ROW, row.name, {"status": status, "message": (message or None) and message[:500], "student_result": result})
	refresh_status(item["import"])


def write_result(import_name, student, rows):
	"""({course: Imported / Unchanged}, Student Result name) after writing `rows` to the student's result."""
	doc = frappe.db.get_value(IMPORT, import_name, ["name", "exam_session", "correction_reason"], as_dict=True)
	session = frappe.db.get_value(
		"Exam Session", doc.exam_session, ["name", "company", "academic_term", "examination_mode"], as_dict=True, for_update=True
	)
	if session.examination_mode != AFFILIATED:
		frappe.throw(_("{0} is not an Affiliated session.").format(session.name))
	latest = frappe.db.get_value(RESULT, {"student": student, "exam_session": session.name, "is_latest": 1}, ["name", "version"], as_dict=True, for_update=True)
	old = frappe.get_doc(RESULT, latest.name) if latest else None
	courses = {c.course: {f: c.get(f) for f in results.ROW_FIELDS} for c in (old.courses if old else [])}
	writer = ResultValues(student, session)
	changed = {}
	for row in rows:
		new = writer.course_row(row)
		was = courses.get(row.course)
		changed[row.course] = UNCHANGED if was and same_outcome(was, new) else IMPORTED
		courses[row.course] = new if changed[row.course] == IMPORTED else was
	if old and IMPORTED not in changed.values():
		return changed, old.name
	if old and not (doc.correction_reason or "").strip():
		frappe.throw(_("This changes a result already imported; give the import a Correction Reason."))
	values = writer.values(list(courses.values()))
	values.update({"source": UNIVERSITY, "university_result_import": import_name, "pending_ratification": 0})
	if not old:
		result = new_result(student, session, 1)
		result.update(values)
		result.insert(ignore_permissions=True)
		return changed, result.name
	log = result_rules.change_log(results.summary(old.as_dict()), results.summary(values))
	version = max(frappe.get_all(RESULT, {"student": student, "exam_session": session.name}, pluck="version") or [0]) + 1
	result = new_result(student, session, version)
	result.update({**values, "previous_version": old.name, "change_log": "\n".join(filter(None, [log, _("Correction: {0}").format(doc.correction_reason.strip())]))})
	frappe.db.set_value(RESULT, old.name, "is_latest", 0, update_modified=False)
	result.insert(ignore_permissions=True)
	return changed, result.name


class ResultValues:
	"""Course rows and the SGPA / CGPA / arrears of one student's imported result, computed as the Result Run does."""

	def __init__(self, student, session):
		self.student, self.session = student, session
		self.scheme = get_rule(student, "Grading Scheme")
		self.letters = {g.letter: g for g in self.scheme.grades}
		self.excluded = {row.course_category for row in self.scheme.get("gpa_excluded_categories", [])}
		self.history = results.earlier_rows(student, session.name, session.academic_term)

	def course_row(self, row):
		registered = registered_course(self.student, self.session.name, row.course)
		if not registered:
			frappe.throw(_("{0} is not registered for {1} in this session.").format(self.student, row.course))
		earlier = [r for r in self.history if r["course"] == row.course and r["course_offering"]]
		offering = registered.course_offering or (earlier[-1]["course_offering"] if earlier else None)
		if not offering:
			frappe.throw(_("No offering of {0} gives its credits.").format(row.course))
		course = offering_course(offering)
		passed = row.result == rules.PASS
		return {
			"course": row.course, "course_offering": offering, "course_type": course["course_type"], "credits": course["credits"],
			"cia": flt(row.cia), "ese": flt(row.ese), "total": flt(row.total), "grade": row.grade, "result": row.result,
			"grade_point": flt(self.letters[row.grade].grade_point) if passed and row.grade in self.letters else 0,
			"kind": "Arrear" if registered.kind == "Arrear" else "Current", "attempt": len(earlier) + 1, "moderation": 0, "grace": 0,
			"grading_method": UNIVERSITY, "in_gpa": int(rules.counts_in_gpa({"category": course["category"]}, self.excluded)),
		}  # fmt: skip

	def values(self, rows):
		current = [r for r in rows if r["kind"] == "Current"]
		attempts = self.history + rows
		passed = lambda r: r["result"] == rules.PASS  # noqa: E731
		return {
			"courses": rows,
			"sgpa": rules.sgpa([(r["credits"], r["grade_point"], passed(r)) for r in current if r["in_gpa"]]),
			"credits_earned": sum(r["credits"] for r in current if passed(r)),
			"cgpa": rules.cgpa([(r["course"], r["credits"], r["grade_point"], passed(r)) for r in attempts if r["in_gpa"]]),
			"result": result_rules.overall_result([r["result"] for r in rows]),
			"arrear_count": len(outstanding_arrears([(r["course"], r["result"]) for r in attempts])),
			"classification": None,
		}


def new_result(student, session, version):
	"""A Student Result of version `version` (named by its controller from the version)."""
	doc = results.new_result(student, session)
	doc.update({"version": version, "is_latest": 1})
	return doc


# ---- status -----------------------------------------------------------------------------------


def refresh_status(name):
	"""Once no row waits: Imported, Partly Imported or Failed; the first import that wrote a result publishes the session."""
	counts = refresh_summary(name)
	doc = frappe.db.get_value(IMPORT, name, ["status", "exam_session", "result_date"], as_dict=True)
	if doc.status != "Importing" or any(counts.get(s) for s in QUEUED):
		return
	written = sum(counts.get(s, 0) for s in WRITTEN)
	if not written:
		status = "Failed"
	elif any(counts.get(s) for s in (REJECTED, ERROR)):
		status = "Partly Imported"
	else:
		status = "Imported"
	frappe.db.set_value(IMPORT, name, "status", status)
	if counts.get(IMPORTED):
		publish_session(doc.exam_session, doc.result_date)


def publish_session(exam_session, result_date):
	session = frappe.get_doc("Exam Session", exam_session, for_update=True)
	if session.status == "Published":
		return
	session.update({"status": "Published", "publish_at": get_datetime(getdate(result_date)) if result_date else now_datetime()})
	session.flags.university_results = True
	session.save(ignore_permissions=True)


def refresh_summary(name):
	table = frappe.qb.DocType(ROW)
	counts = dict(
		frappe.qb.from_(table).select(table.status, Count("*")).where(table.university_result_import == name).groupby(table.status).run()
	)
	text = ", ".join(f"{_(status)}: {count}" for status, count in sorted(counts.items()))
	frappe.db.set_value(IMPORT, name, "summary", text, update_modified=False)
	return counts


def reconcile(name):
	"""Finish an import whose bulk run ended while rows still wait: they become Error rows asking for a new import."""
	doc = frappe.db.get_value(IMPORT, name, ["status", "bulk_run"], as_dict=True, for_update=True)
	if not doc or doc.status != "Importing" or not doc.bulk_run:
		return
	if frappe.db.get_value("Bulk Run", doc.bulk_run, "status") not in ("Completed", "Completed with errors", "Failed"):
		return
	message = _("Not imported: the import was interrupted at this row. Import the file again to retry it.")
	for row in frappe.get_all(ROW, {"university_result_import": name, "status": ["in", QUEUED]}, pluck="name"):
		frappe.db.set_value(ROW, row, {"status": ERROR, "message": message})
	refresh_status(name)


def reconcile_finished_imports():
	"""Scheduler (hourly): complete imports whose bulk run has finished; one bad import never stops the others."""
	for name in frappe.get_all(IMPORT, {"status": "Importing"}, pluck="name"):
		try:
			reconcile(name)
			frappe.db.commit()  # nosemgrep: one import per transaction, a failure must not undo the others
		except Exception:  # noqa: BLE001
			frappe.db.rollback()
			frappe.log_error(title=f"University result import reconcile failed: {name}", message=frappe.get_traceback(with_context=False))


def validate_import_doc(doc):
	"""Controller validate: an Affiliated session and an Import format; status and run fields are the import code's."""
	session = frappe.db.get_value("Exam Session", doc.exam_session, ["company", "examination_mode"], as_dict=True)
	if session.examination_mode != AFFILIATED:
		frappe.throw(_("{0} is not an Affiliated session; its results are the college's.").format(frappe.bold(doc.exam_session)))
	fmt = frappe.db.get_value("University Exam Format", doc.import_format, ["direction", "university"], as_dict=True)
	if fmt.direction != "Import":
		frappe.throw(_("{0} is not an Import format.").format(frappe.bold(doc.import_format)))
	doc.update({"company": session.company, "university": fmt.university})
	system = ("status", "bulk_run", "file_sha256", "total_rows", "summary")
	if doc.is_new():
		doc.update({"status": "Draft", "bulk_run": None, "file_sha256": None, "total_rows": 0, "summary": None})
		return
	if any(doc.has_value_changed(f) for f in system):
		frappe.throw(_("The status of an import is set by Validate and Import only."), frappe.PermissionError)
	inputs = ("exam_session", "import_format", "result_file", "result_date", "correction_reason")
	if any(doc.has_value_changed(f) for f in inputs):
		if doc.status not in ("Draft", "Validated"):
			frappe.throw(_("A started import cannot be changed."))
		if any(doc.has_value_changed(f) for f in inputs[:3]):
			doc.status = "Draft"  # a new file, session or format needs a new preview
