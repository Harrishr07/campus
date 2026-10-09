"""M05-06 Student portal data (core of P1-T26): fees, attendance, results for a student or their guardian.

Every function resolves the target student from the session user: a student sees only themself, a
guardian only the students linked to them on the Student's guardian rows. A student id taken from the
request is honoured only when it is in that set (PermissionError otherwise); it is never trusted alone.
Whitelisted methods return plain dicts for the pages in campus/www/campus_portal.
"""

import os
from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils.html_utils import sanitize_html

from campus.campus_finance.api import can_pay_online, fee_payment_link, has_dues, student_invoices
from campus.campus_platform.api import find_policy, latest_request, start_request
from campus.examinations.api import confirm_registration, student_registrations
from campus.student_services import grievances
from campus.student_services.api import student_terms, summarise, term_window

PORTAL_HOME = "/campus-portal"
UPLOAD_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
UPLOAD_MAX_BYTES = 5 * 1024 * 1024


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
	invoices = student_invoices(student)
	online = {company: can_pay_online(company) for company in {i.company for i in invoices}}
	for invoice in invoices:
		invoice["can_pay"] = bool(online[invoice.company] and not invoice.is_return and invoice.outstanding_amount > 0)
	return frappe._dict(
		student=student,
		invoices=invoices,
		outstanding_by_company=[{"company": c, "outstanding": v} for c, v in dues.by_company.items()],
		total_outstanding=dues.total,
		due_now=dues.blocking,
	)


@frappe.whitelist(methods=["POST"])
def pay_invoice(invoice, student=None):
	"""The gateway URL to pay `invoice`. fee_payment_link checks the invoice is the caller's own or a ward's."""
	student = resolve_student(student)  # a login with no linked student, or a student that is not theirs, is refused
	owner = frappe.db.get_value("Sales Invoice", invoice, "student")
	if owner and owner != student:  # the switcher's ward must be the invoice's student
		frappe.throw(_("You cannot pay this invoice."), frappe.PermissionError)
	return {"url": fee_payment_link(invoice)}


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
	"""Certificate types a student may ask for, with their fee and whether approval is needed (never the desk-only
	examination types such as the Degree Data Sheet)."""
	from campus.examinations.api import desk_only_certificate_types

	require_login()
	return frappe.get_all(
		"Certificate Type", {"enabled": 1, "name": ["not in", desk_only_certificate_types() or [""]]},
		["name", "fee_amount", "needs_approval", "is_transfer_certificate"], order_by="name",
	)


@frappe.whitelist(methods=["POST"])
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
	check_approval_route(request)
	request.insert()
	start_request(request)
	request.reload()
	return certificate_row(request)


def check_approval_route(request):
	"""A type that needs approval cannot be asked for until the college has set up its approval route."""
	if not frappe.db.get_value("Certificate Type", request.certificate_type, "needs_approval"):
		return
	request.needs_approval = 1
	request.company = frappe.db.get_value("Student", request.student, "oc_company")
	if not find_policy(request):
		frappe.throw(
			_("{0} certificates need approval, which the college has not set up yet. Please contact the college office.").format(
				request.certificate_type
			)
		)


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


@frappe.whitelist()
def my_onboarding(student=None):
	"""Onboarding status of the session user's student (or a guarded one): {student, completion, items} or None.

	Items carry title, mandatory and status only; uploaded affidavits are not exposed.
	"""
	student = resolve_student(student)
	name = frappe.db.get_value("Student Onboarding", {"student": student})
	if not name:
		return None
	doc = frappe.get_doc("Student Onboarding", name)
	return {
		"student": student,
		"completion": doc.completion,
		"items": [{"title": _(row.title), "mandatory": row.mandatory, "status": row.status} for row in doc.items],
	}


@frappe.whitelist()
def grievance_categories():
	"""Grievance categories a student may raise: [{name, description}]."""
	require_login()
	return frappe.get_all("Grievance Type", {"oc_applies_to_students": 1}, ["name", "description"], order_by="name")


@frappe.whitelist(methods=["POST"])
def raise_grievance(category, description, student=None):
	"""Raise a grievance for the session user's student (or a guarded one); returns its row.

	The student comes from resolve_student, never from the request alone. The grievance enters the
	escalation chain of its category's policy at once. A file posted with it is attached privately."""
	student = resolve_student(student)
	upload = uploaded_file()  # checked before anything is created
	grievance = grievances.open_grievance(student, category, description)
	if upload:
		attach_private(grievance, "attachment", *upload)
	return grievance_row(grievance)


def posted_file():
	files = getattr(getattr(frappe.local, "request", None), "files", None)
	return files.get("file") if files else None


def uploaded_file():
	"""(file name, content) of the file posted with the request, or None; throws if it is not an allowed kind or too big."""
	upload = posted_file()
	if not upload or not upload.filename:
		return None
	name = os.path.basename(upload.filename)
	content = upload.stream.read(UPLOAD_MAX_BYTES + 1)
	if not name.lower().endswith(UPLOAD_EXTENSIONS):
		frappe.throw(_("Upload a PDF, JPG or PNG file."))
	if len(content) > UPLOAD_MAX_BYTES:
		frappe.throw(_("The file is larger than {0} MB.").format(UPLOAD_MAX_BYTES // (1024 * 1024)))
	return name, content


def attach_private(doc, fieldname, file_name, content):
	"""Save `content` as a private File attached to `doc.fieldname`; only people who can read `doc` can open it."""
	file = frappe.get_doc(
		{
			"doctype": "File", "file_name": file_name, "content": content, "is_private": 1,
			"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "attached_to_field": fieldname,
		}
	)  # fmt: skip
	file.flags.ignore_permissions = True
	file.insert()
	doc.db_set(fieldname, file.file_url)


@frappe.whitelist()
def my_grievances(student=None):
	"""The student's grievances, newest first. Ownership comes from resolve_student; the doctype's permission
	query still applies, so a confidential grievance is listed to the student who raised it and no one else."""
	student = resolve_student(student)
	names = frappe.get_list("Student Grievance", {"student": student}, pluck="name", order_by="creation desc")
	return {"student": student, "grievances": [grievance_row(frappe.get_doc("Student Grievance", n)) for n in names]}


def grievance_row(grievance):
	state = {0: _(grievance.status), 1: _("Resolved"), 2: _("Cancelled")}[grievance.docstatus]
	return {
		"name": grievance.name, "category": grievance.category, "description": grievance.description, "status": state,
		"raised_on": grievance.raised_on, "resolution": grievance.resolution, "resolved_on": grievance.resolved_on,
	}  # fmt: skip


@frappe.whitelist(methods=["POST"])
def apply_leave(from_date, to_date, leave_kind, reason=None, student=None):
	"""Apply for leave as the session user's student (or a guarded one): a draft the college staff review and submit.

	Medical and On Duty leave take a certificate posted with the request (private); staff cannot submit them without it."""
	student = resolve_student(student)
	upload = uploaded_file()
	leave = frappe.get_doc(
		{
			"doctype": "Student Leave Application", "student": student, "from_date": from_date, "to_date": to_date,
			"oc_leave_kind": leave_kind, "reason": (reason or "").strip(),
		}
	)  # fmt: skip
	leave.flags.ignore_permissions = True
	leave.insert()
	if upload:
		attach_private(leave, "oc_certificate", *upload)
	return leave_row(leave)


@frappe.whitelist()
def my_leaves(student=None):
	"""The student's leave applications, newest first; the doctype's portal scope still applies."""
	student = resolve_student(student)
	names = frappe.get_list("Student Leave Application", {"student": student}, pluck="name", order_by="creation desc")
	return {"student": student, "leaves": [leave_row(frappe.get_doc("Student Leave Application", n)) for n in names]}


def leave_row(leave):
	state = {0: _("Requested"), 1: _("Approved"), 2: _("Cancelled")}[leave.docstatus]
	return {
		"name": leave.name, "from_date": leave.from_date, "to_date": leave.to_date, "leave_kind": leave.oc_leave_kind,
		"reason": leave.reason, "status": state, "total_leave_days": leave.total_leave_days,
	}  # fmt: skip


def is_the_student(student):
	"""Whether the session user is the student themself (a guardian may view, only the student confirms)."""
	return frappe.db.get_value("Student", student, "user") == frappe.session.user


@frappe.whitelist()
def my_exam_registrations(student=None):
	"""The student's Exam Registrations of unpublished sessions: courses, eligibility, fee, whether they may confirm."""
	student = resolve_student(student)
	own = is_the_student(student)
	registrations = student_registrations(student)
	for row in registrations:
		row["can_confirm"] = bool(own and not row["confirmed"] and row["has_eligible"])
	return {"student": student, "registrations": registrations}


@frappe.whitelist(methods=["POST"])
def confirm_exam_registration(registration, student=None):
	"""The student confirms their own Exam Registration; this fixes the fee and queues the exam fee invoice."""
	student = resolve_student(student)
	if not is_the_student(student):
		frappe.throw(_("Only the student can confirm their exam registration."), frappe.PermissionError)
	if frappe.db.get_value("Exam Registration", registration, "student") != student:
		frappe.throw(_("You cannot confirm this exam registration."), frappe.PermissionError)
	doc = confirm_registration(registration)
	return {"registration": doc.name, "fee_total": doc.fee_total, "late_fee": doc.late_fee}
