"""M05-06 Student portal data (core of P1-T26): fees, attendance, results for a student or their guardian.

Every function resolves the target student from the session user: a student sees only themself, a
guardian only the students linked to them on the Student's guardian rows. A student id taken from the
request is honoured only when it is in that set (PermissionError otherwise); it is never trusted alone.
Whitelisted methods return plain dicts for the pages in campus/www/campus_portal.
"""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils.html_utils import sanitize_html

from campus.campus_finance.api import has_dues, student_invoices
from campus.campus_platform.api import latest_request, start_request
from campus.student_services.api import summarise, term_window

PORTAL_HOME = "/campus-portal"


def require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Log in to use the student portal."), frappe.PermissionError)


def linked_students(user=None):
	"""[{name, student_name}] of the students `user` is, or guards. Own student first, then by name."""
	user = user or frappe.session.user
	own = frappe.get_all("Student", {"user": user}, pluck="name")
	guardians = frappe.get_all("Guardian", {"user": user}, pluck="name")
	guarded = (
		frappe.get_all("Student Guardian", {"guardian": ["in", guardians], "parenttype": "Student"}, pluck="parent")
		if guardians
		else []
	)
	names = list(dict.fromkeys([*own, *sorted(guarded)]))
	rows = frappe.get_all("Student", {"name": ["in", names or [""]], "enabled": 1}, ["name", "student_name"])
	return sorted(rows, key=lambda row: (row.name not in own, row.student_name or row.name))


def resolve_student(student=None):
	"""The student the session user may act on: `student` if linked to them, else their first linked student."""
	require_login()
	allowed = linked_students()
	if not allowed:
		frappe.throw(_("No student is linked to your account."), frappe.PermissionError)
	if not student:
		return allowed[0].name
	if student not in {row.name for row in allowed}:
		frappe.throw(_("You cannot view this student."), frappe.PermissionError)
	return student


@frappe.whitelist()
def my_students():
	require_login()
	return linked_students()


@frappe.whitelist()
def get_fees(student=None):
	"""Submitted Sales Invoices and credit notes of the student, with outstanding totals per company.

	The invoices and the dues come from the fee ledger (campus_finance.api), the one source of truth.
	"""
	student = resolve_student(student)
	dues = has_dues(student)
	return frappe._dict(
		student=student,
		invoices=student_invoices(student),
		outstanding_by_company=[{"company": c, "outstanding": v} for c, v in dues.by_company.items()],
		total_outstanding=dues.total,
		due_now=dues.blocking,
	)


def student_terms(student):
	"""Academic Terms in which the student is an active member of a course offering, newest first."""
	group, member = frappe.qb.DocType("Student Group"), frappe.qb.DocType("Student Group Student")
	term = frappe.qb.DocType("Academic Term")
	return (
		frappe.qb.from_(group)
		.join(member)
		.on(member.parent == group.name)
		.join(term)
		.on(term.name == group.academic_term)
		.select(term.name, term.term_start_date)
		.where(group.group_based_on == "Course")
		.where(member.student == student)
		.where(member.active == 1)
		.groupby(term.name, term.term_start_date)
		.orderby(term.term_start_date, order=frappe.qb.desc)
		.run(as_dict=True)
	)


@frappe.whitelist()
def get_attendance(student=None, academic_term=None):
	"""Attendance summary (S1) of the student for `academic_term` (default: their latest term).

	The ownership check above replaces attendance_summary's Student read check, which portal users
	need not hold; that check stays as it is for every other caller.
	"""
	student = resolve_student(student)
	terms = [row.name for row in student_terms(student)]
	if academic_term and academic_term not in terms:
		frappe.throw(_("Attendance is not available for term {0}.").format(academic_term), frappe.PermissionError)
	academic_term = academic_term or (terms[0] if terms else None)
	summary = summarise(student, academic_term, term_window(academic_term), {}) if academic_term else None
	return {"student": student, "terms": terms, "academic_term": academic_term, "summary": summary}


@frappe.whitelist()
def get_results(student=None):
	"""Published Student Results of the student; the doctype's permission query gates publication."""
	student = resolve_student(student)
	names = frappe.get_list("Student Result", {"student": student}, pluck="name", order_by="creation desc")
	results = []
	for name in names:
		doc = frappe.get_doc("Student Result", name)
		doc.check_permission("read")
		results.append(
			{
				"name": doc.name,
				"exam_session": doc.exam_session,
				"academic_term": doc.academic_term,
				"company": doc.company,
				"sgpa": doc.sgpa,
				"cgpa": doc.cgpa,
				"credits_earned": doc.credits_earned,
				"grade_sheet_url": grade_sheet_url(doc.name),
				"courses": [
					{f: c.get(f) for f in ("course", "credits", "cia", "ese", "total", "grade", "grade_point", "result")}
					for c in doc.courses
				],
			}
		)
	return {"student": student, "results": results}


def grade_sheet_url(student_result):
	return (
		"/api/method/frappe.utils.print_format.download_pdf?doctype=Student%20Result"
		f"&name={quote(student_result)}&format=Grade%20Sheet"
	)


@frappe.whitelist()
def certificate_types():
	"""Certificate types a student may ask for, with their fee and whether approval is needed."""
	require_login()
	return frappe.get_all(
		"Certificate Type", {"enabled": 1}, ["name", "fee_amount", "needs_approval", "is_transfer_certificate"], order_by="name"
	)


@frappe.whitelist()
def request_certificate(certificate_type, purpose, student=None, leaving_date=None, reason_for_leaving=None):
	"""Ask for a certificate for the session user's student (or a guarded one); returns the request and its state.

	The student comes from resolve_student, never from the request alone. The request is made with
	ignore_permissions (portal roles may only read Certificate Request) and then sent through approval, or
	issued at once when the type needs none.
	"""
	student = resolve_student(student)
	request = frappe.get_doc(
		{
			"doctype": "Certificate Request", "student": student, "certificate_type": certificate_type,
			"purpose": (purpose or "").strip(), "leaving_date": leaving_date, "reason_for_leaving": reason_for_leaving,
		}
	)  # fmt: skip
	request.flags.ignore_permissions = True
	request.insert()
	start_request(request)
	request.reload()
	return certificate_row(request)


@frappe.whitelist()
def my_certificates(student=None):
	"""The student's certificate requests, newest first: state, number and, once issued, the PDF and verification links."""
	student = resolve_student(student)
	names = frappe.get_list("Certificate Request", {"student": student}, pluck="name", order_by="creation desc")
	return {"student": student, "certificates": [certificate_row(frappe.get_doc("Certificate Request", n)) for n in names]}


def certificate_row(request):
	issued = request.docstatus == 1
	state = {0: _("Requested"), 1: _("Issued"), 2: _("Cancelled")}[request.docstatus]
	approval = latest_request(request) if request.docstatus == 0 else None
	if approval:  # Pending, Rejected, Returned
		state = _(approval.status)
	return {
		"name": request.name, "certificate_type": request.certificate_type, "purpose": request.purpose, "status": state,
		"certificate_number": request.certificate_number, "issued_on": request.issued_on, "fee_amount": request.fee_amount,
		"pdf_url": certificate_pdf_url(request) if issued else None,
		"verification_code": request.verification_code,
	}  # fmt: skip


def certificate_pdf_url(request):
	print_format = frappe.db.get_value("Certificate Type", request.certificate_type, "print_format")
	return (
		"/api/method/frappe.utils.print_format.download_pdf?doctype=Certificate%20Request"
		f"&name={quote(request.name)}&format={quote(print_format)}"
	)


def page_context(context, student=None):
	"""Fill the shared parts of a portal page (login redirect, student switcher); returns the student.

	A user with no linked student gets an empty page with a notice rather than an error."""
	context.no_cache = 1
	context.show_sidebar = False
	if frappe.session.user == "Guest":
		request = getattr(frappe.local, "request", None)
		target = request.path if request and request.path.startswith(PORTAL_HOME) else PORTAL_HOME
		frappe.local.flags.redirect_location = f"/login?redirect-to={quote(target)}"
		raise frappe.Redirect
	context.students = linked_students()
	context.student = None
	if context.students:
		context.student = resolve_student(student or frappe.form_dict.get("student"))
		context.student_name = next(s.student_name for s in context.students if s.name == context.student)
	return context.student


def clean_circular_body(circulars):
	for circular in circulars:
		circular["body"] = sanitize_html(circular.get("body") or "")
	return circulars
