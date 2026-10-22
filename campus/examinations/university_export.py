"""M06-10 University exam registration export (Affiliated mode): University Exam Registration Batch.

Flow (COE): a batch of an Affiliated Exam Session in an Export format is built (`build_rows`, Draft only) from the
session's confirmed Exam Registrations - every eligible course, regular and arrear - with the CIA of the term. Each
row is validated: Ready, or Refused with every reason (no university register number, no university course code or
registration type in the format's code mappings, the CIA not finalised - the offering's CIA Schedule not locked or no
CIA mark - or, for an arrear, no earlier attempt to carry the CIA from). `export` writes the Ready rows to a private
file in the format (cells formula-safe, campus.examinations.university_files) and lists the refused rows. The
transmission reference and date, then the university's acknowledgement reference and date are recorded; before the
acknowledgement the COE enters the university's reason on each row it rejected, and the acknowledgement marks those
rows Rejected and the others of that export Accepted. `reexport` sends only the corrected rows: the Rejected rows
ticked Corrected and the Refused rows, each validated again from today's data (a row still failing stays with its
reason). Every step adds a comment to the batch.
"""

import frappe
from frappe import _
from frappe.utils import cstr, escape_html, flt, getdate, now_datetime

from campus.examinations import result_rules, university_files
from campus.examinations.access import COE_ROLE
from campus.examinations.affiliation import AFFILIATED, UNIVERSITY_REGISTER_FIELD
from campus.examinations.cia import schedule_of
from campus.examinations.courses import offering_course, student_limits

BATCH, ROW = "University Exam Registration Batch", "University Exam Registration Row"
READY, REFUSED, EXPORTED, ACCEPTED, REJECTED = "Ready", "Refused", "Exported", "Accepted", "Rejected"
SAT = ("Fail", "AB")  # earlier outcomes whose CIA an arrear attempt carries (as the Result Run)
ROW_VALUES = ("university_register_no", "university_course_code", "registration_type", "cia", "cia_max")


@frappe.whitelist(methods=["POST"])
def build_rows(name):
	"""Draft only: (re)build the batch's rows from the session's confirmed registrations; returns {status: count}."""
	batch = locked_batch(name, ("Draft",), _("Rows are built while the batch is a Draft."))
	builder = RowBuilder(batch)
	batch.rows = []
	for registration in frappe.get_all(
		"Exam Registration", {"exam_session": batch.exam_session, "company": batch.company, "confirmed": 1}, ["name", "student"], order_by="student"
	):  # fmt: skip
		for course in frappe.get_all(
			"Exam Registration Course", {"parent": registration.name, "parenttype": "Exam Registration", "eligibility": "Eligible"},
			["course", "course_offering", "kind"], order_by="idx",
		):  # fmt: skip
			batch.append("rows", builder.row(registration.student, course))
	return save(batch)


@frappe.whitelist(methods=["POST"])
def export(name):
	"""Write the Ready rows of a Draft batch to its export file; returns {file_url, exported, refused: [...]}."""
	batch = locked_batch(name, ("Draft",), _("This batch is exported already; use Re-export Corrections."))
	return send(batch, [row for row in batch.rows if row.status == READY])


@frappe.whitelist(methods=["POST"])
def reexport(name):
	"""Validate the corrected rows again (Rejected and ticked Corrected, or Refused) and export the ones now valid."""
	batch = locked_batch(name, ("Acknowledged", "Partly Rejected"), _("Re-export after the university acknowledged the last export."))
	builder, ready = RowBuilder(batch), []
	for row in batch.rows:
		if row.status == REFUSED or (row.status == REJECTED and row.corrected):
			fresh = builder.row(row.student, frappe._dict(course=row.course, course_offering=row.course_offering, kind=row.kind))
			row.update({f: fresh[f] for f in (*ROW_VALUES, "reason")})
			if fresh["status"] == READY:
				ready.append(row)
	if not ready:
		save(batch)
		frappe.throw(_("No corrected row is ready to export: {0}").format(refused_list(batch)))
	for row in ready:
		if row.rejection_reason:
			batch.add_comment("Info", _("{0} {1} sent again after the university's rejection: {2}").format(
				escape_html(row.student), escape_html(row.course), escape_html(row.rejection_reason)))
		row.update({"rejection_reason": None, "corrected": 0})
	return send(batch, ready)


@frappe.whitelist(methods=["POST"])
def record_transmission(name, reference, transmitted_on):
	"""The exported file was sent to the university under `reference` on `transmitted_on`."""
	batch = locked_batch(name, (EXPORTED,), _("Record the transmission of an exported batch."))
	reference = required_text(reference, _("Transmission Reference"))
	batch.update({"status": "Transmitted", "transmission_reference": reference, "transmitted_on": getdate(transmitted_on)})
	batch.add_comment("Info", _("Export {0} transmitted on {1}: {2}").format(batch.export_count, batch.transmitted_on, escape_html(reference)))
	return save(batch)


@frappe.whitelist(methods=["POST"])
def record_acknowledgement(name, reference, acknowledged_on):
	"""The university acknowledged the last export: rows with its rejection reason become Rejected, the rest Accepted."""
	batch = locked_batch(name, ("Transmitted",), _("Record the acknowledgement of a transmitted batch."))
	reference = required_text(reference, _("Acknowledgement Reference"))
	for row in batch.rows:
		if row.status == EXPORTED and row.export_no == batch.export_count:
			row.status = REJECTED if (row.rejection_reason or "").strip() else ACCEPTED
	rejected = any(row.status == REJECTED for row in batch.rows)
	batch.update({"status": "Partly Rejected" if rejected else "Acknowledged", "acknowledgement_reference": reference,
		"acknowledged_on": getdate(acknowledged_on)})  # fmt: skip
	batch.add_comment("Info", _("Export {0} acknowledged on {1}: {2}").format(batch.export_count, batch.acknowledged_on, escape_html(reference)))
	return save(batch)


# ---- steps ------------------------------------------------------------------------------------


def locked_batch(name, statuses, message):
	frappe.only_for((COE_ROLE, "System Manager"))
	frappe.has_permission(BATCH, "write", name, throw=True)
	if frappe.db.get_value(BATCH, name, "status", for_update=True) not in statuses:
		frappe.throw(message)
	batch = frappe.get_doc(BATCH, name)
	batch.check_permission("write")
	return batch


def send(batch, rows):
	"""Export `rows` as the batch's next file; returns {file_url, exported, refused}."""
	if not rows:
		frappe.throw(_("No row is ready to export: {0}").format(refused_list(batch)))
	fmt = frappe.get_doc("University Exam Format", batch.export_format)
	batch.export_count = (batch.export_count or 0) + 1
	for row in rows:
		row.update({"status": EXPORTED, "export_no": batch.export_count})
	extension, content = university_files.build_file(fmt, file_records(batch, rows))
	file = frappe.get_doc(
		{
			"doctype": "File", "file_name": f"{batch.name}-{batch.export_count}.{extension}", "content": content, "is_private": 1,
			"attached_to_doctype": BATCH, "attached_to_name": batch.name,
		}
	).insert(ignore_permissions=True)  # fmt: skip
	batch.update({"status": EXPORTED, "exported_file": file.file_url, "transmission_reference": None, "transmitted_on": None,
		"acknowledgement_reference": None, "acknowledged_on": None})  # fmt: skip
	batch.add_comment("Info", _("Export {0}: {1} rows on {2}.").format(batch.export_count, len(rows), now_datetime()))
	save(batch)
	refused = [{"student": r.student, "course": r.course, "reason": r.reason} for r in batch.rows if r.status in (REFUSED, REJECTED)]
	if refused:
		frappe.msgprint(refused_list(batch), title=_("Rows not exported"), indicator="orange")
	return {"file_url": file.file_url, "exported": len(rows), "refused": refused}


def save(batch):
	counts = {}
	for row in batch.rows:
		counts[row.status] = counts.get(row.status, 0) + 1
	batch.summary = ", ".join(f"{_(status)}: {count}" for status, count in sorted(counts.items()))
	batch.flags.server_update = True
	batch.save()
	return counts


def refused_list(batch):
	rows = [r for r in batch.rows if r.status in (REFUSED, REJECTED)]
	if not rows:
		return _("no row is refused.")
	items = "".join(
		f"<li>{escape_html(r.student)} {escape_html(r.course)}: {escape_html(r.reason or r.rejection_reason or _('rejected by the university'))}</li>"
		for r in rows
	)
	return f"<ul>{items}</ul>"


def required_text(value, label):
	value = (value or "").strip()
	if not value:
		frappe.throw(_("{0} is required.").format(label))
	return value


def file_records(batch, rows):
	"""[{source: value}] of `rows` for the export file."""
	fmt = frappe.get_doc("University Exam Format", batch.export_format)
	students = {
		s.name: s
		for s in frappe.get_all("Student", {"name": ["in", [r.student for r in rows]]}, ["name", "student_name", "oc_register_no", "date_of_birth"])
	}
	courses = dict(frappe.get_all("Course", {"name": ["in", [r.course for r in rows]]}, ["name", "course_name"], as_list=True))
	programs = dict(
		frappe.get_all("Exam Registration", {"exam_session": batch.exam_session, "student": ["in", list(students)]}, ["student", "program"], as_list=True)
	)
	records = []
	for row in rows:
		student = students[row.student]
		records.append(
			{
				"University Register No": row.university_register_no, "Register No": student.oc_register_no, "Student Name": student.student_name,
				"Date of Birth": university_files.date_text(student.date_of_birth, fmt), "Program": programs.get(row.student),
				"Course Code": row.university_course_code, "Course Name": courses.get(row.course), "Registration Type": row.registration_type,
				"CIA": row.cia, "CIA Max": row.cia_max, "Exam Session": batch.exam_session,
			}
		)  # fmt: skip
	return records


class RowBuilder:
	"""Builds and validates the rows of one batch from today's data."""

	def __init__(self, batch):
		from campus.examinations.results import earlier_rows

		self.batch, self.earlier_rows = batch, earlier_rows
		self.codes = university_files.CodeMap(frappe.get_doc("University Exam Format", batch.export_format))

	def row(self, student, course):
		"""A University Exam Registration Row (dict) of the student's registered `course` with its status and reasons."""
		reasons = []
		register_no = frappe.db.get_value("Student", student, UNIVERSITY_REGISTER_FIELD)
		if not register_no:
			reasons.append(_("no university register number"))
		code = self.codes.university("Course", course.course)
		if not code:
			reasons.append(_("course {0} has no university course code").format(course.course))
		kind = self.codes.university("Registration Type", course.kind)
		if not kind:
			reasons.append(_("registration type {0} has no university code").format(course.kind))
		cia, cia_max, problem = self.cia(student, course)
		if problem:
			reasons.append(problem)
		return {
			"student": student, "student_name": frappe.db.get_value("Student", student, "student_name"), "course": course.course,
			"course_offering": course.course_offering, "kind": course.kind, "university_register_no": register_no,
			"university_course_code": code, "registration_type": kind, "cia": cia, "cia_max": cia_max,
			"status": REFUSED if reasons else READY, "reason": "; ".join(reasons) or None,
		}  # fmt: skip

	def cia(self, student, course):
		"""(cia, cia_max, problem) of the student in the course this term; problem None when the CIA is final."""
		try:
			if course.course_offering:
				return self.term_cia(student, course.course_offering)
			return self.arrear_cia(student, course.course)
		except frappe.ValidationError as error:  # an unconfigured course or rule: refused with its reason
			return 0, 0, frappe.utils.strip_html(str(error))

	def term_cia(self, student, offering):
		schedule = schedule_of(offering)
		if schedule and not frappe.db.get_value("CIA Schedule", schedule, "locked_on"):
			return 0, 0, _("the CIA of {0} is not finalised (CIA Schedule {1} is not locked)").format(offering, schedule)
		sheets = frappe.get_all("Mark Sheet Entry", {"exam_session": self.batch.exam_session, "course_offering": offering}, pluck="name")
		mark = sheets and frappe.db.get_value(
			"Mark Sheet Entry Row", {"parent": ["in", sheets], "parenttype": "Mark Sheet Entry", "student": student}, ["name", "cia"], as_dict=True
		)
		if not mark:
			return 0, 0, _("no CIA mark in {0}").format(offering)
		return flt(mark.cia), student_limits(student, offering_course(offering))["cia_max"], None

	def arrear_cia(self, student, course):
		from campus.campus_platform.api import get_rule

		term = frappe.db.get_value("Exam Session", self.batch.exam_session, "academic_term")
		earlier = [r for r in self.earlier_rows(student, self.batch.exam_session, term) if r.course == course and r.course_offering]
		if not earlier:
			return 0, 0, _("no earlier attempt of {0} to carry the CIA from").format(course)
		carried = [r.cia for r in earlier if r.result in SAT]
		carry_forward = get_rule(student, "Exam Rule Set").cia_carry_forward
		cia = result_rules.arrear_cia(carried, None, carry_forward)
		return cia, student_limits(student, offering_course(earlier[-1].course_offering))["cia_max"], None


SERVER_FIELDS = (
	"status", "export_count", "exported_file", "summary", "transmission_reference", "transmitted_on", "acknowledgement_reference",
	"acknowledged_on",
)  # fmt: skip
SERVER_ROW_FIELDS = (
	"student", "student_name", "university_register_no", "course", "course_offering", "university_course_code", "kind",
	"registration_type", "cia", "cia_max", "status", "reason", "export_no",
)  # fmt: skip


def validate_batch(doc):
	"""Controller validate: the session is an Affiliated one, the format an Export one; rows and status are the server's."""
	session = frappe.db.get_value("Exam Session", doc.exam_session, ["company", "academic_term", "examination_mode"], as_dict=True)
	if session.examination_mode != AFFILIATED:
		frappe.throw(_("{0} is not an Affiliated session; its examinations are the college's.").format(frappe.bold(doc.exam_session)))
	fmt = frappe.db.get_value("University Exam Format", doc.export_format, ["direction", "university"], as_dict=True)
	if fmt.direction != "Export":
		frappe.throw(_("{0} is not an Export format.").format(frappe.bold(doc.export_format)))
	doc.update({"company": session.company, "academic_term": session.academic_term, "university": fmt.university})
	if doc.is_new():
		doc.update({**{f: None for f in SERVER_FIELDS}, "status": "Draft", "export_count": 0})
		doc.set("rows", [])
		return
	if doc.flags.server_update:
		return
	before = doc.get_doc_before_save()
	if any(plain(doc.get(f)) != plain(before.get(f)) for f in SERVER_FIELDS):
		frappe.throw(_("The status, export and transmission fields of a batch are set by its actions only."))
	if any(doc.has_value_changed(f) for f in ("exam_session", "export_format")) and before.status != "Draft":
		frappe.throw(_("An exported batch keeps its session and format."))
	guard_rows(doc, before)


def guard_rows(doc, before):
	"""A user edit may only enter the university's rejection reason (transmitted batch, row of the last export) and
	tick Corrected on a Rejected row."""
	old = {row.name: row for row in before.rows}
	if {row.name for row in doc.rows} != set(old):
		frappe.throw(_("The rows of a batch are built by the server."))
	for row in doc.rows:
		was = old[row.name]
		changed = [f for f in SERVER_ROW_FIELDS if plain(was.get(f)) != plain(row.get(f))]
		if changed:
			frappe.throw(_("Row {0}: {1} are set by the server.").format(row.idx, ", ".join(changed)))
		if plain(was.rejection_reason) != plain(row.rejection_reason) and not (
			doc.status == "Transmitted" and row.status == EXPORTED and row.export_no == doc.export_count
		):
			frappe.throw(_("Row {0}: enter the university's rejection reason on a row of the transmitted export.").format(row.idx))
		if bool(was.corrected) != bool(row.corrected) and row.status != REJECTED:
			frappe.throw(_("Row {0}: only a row the university rejected is marked corrected.").format(row.idx))


def plain(value):
	"""A comparable form of a field value: numbers as floats, blanks as ""."""
	if isinstance(value, int | float):
		return flt(value)
	return cstr(value).strip()
