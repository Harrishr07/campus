"""M06-07, M05-04 Examination certificates on the P1-T20 certificate pattern: each print is a Certificate Type whose
Certificate Request (portal or desk, ownership-checked, fee if the type has one) issues a Verifiable Document (QR)
on submit. A Transcript Request is a Certificate Request of the Transcript type.

Prints (doc type Certificate Request, values from campus.examinations.graduation, published ratified results only):
Transcript (every published semester), Consolidated Grade Sheet, Provisional Certificate (issuer per the Institution
Profile's provisional_certificate_issuer), Degree Certificate (only when degree_awarding_body is College) and
Degree Data Sheet (for the university, when it awards the degree). The semester Grade Sheet stays on Student Result
(examinations.api.issue_grade_sheet).

Control (fix round 1):
- The graduate documents are seeded needing approval (the college's Certificate Request Approval Policy, e.g. the
  COE); the Transcript does not. A Provisional and a Degree Certificate are issued once per student (a cancelled one
  may be issued again), checked under a lock on the Student at issue. The Degree Data Sheet is for the university
  and is requested on the desk only (who may create Certificate Requests), never in the portal.
- A request is refused (validate) when its print is not available to the student's college, when the student has
  no published result, or, for the graduate prints, before the programme is completed.
- Snapshot: on submit the graduate record is frozen as JSON on the request (record_snapshot), and an issued print
  renders from that snapshot only, so the QR always attests what was issued: a later result version, rule change or
  setting switch never alters it. A draft renders live (preview, no QR) and refuses a print unavailable to the
  college.
"""

import json

import frappe
from frappe import _

from campus.campus_platform.api import get_institution
from campus.examinations.graduation import graduate_record

TRANSCRIPT, CONSOLIDATED, PROVISIONAL, DEGREE, DATA_SHEET = (
	"Transcript", "Consolidated Grade Sheet", "Provisional Certificate", "Degree Certificate", "Degree Data Sheet",
)  # fmt: skip
COLLEGE, UNIVERSITY = "College", "University"
# print format (= seeded Certificate Type) -> (number prefix, needs a completed programme, needs approval)
PRINTS = {
	TRANSCRIPT: ("TRN/{abbr}/{yyyy}/", False, 0),
	CONSOLIDATED: ("CGS/{abbr}/{yyyy}/", True, 1),
	PROVISIONAL: ("PC/{abbr}/{yyyy}/", True, 1),
	DEGREE: ("DEG/{abbr}/{yyyy}/", True, 1),
	DATA_SHEET: ("DDS/{abbr}/{yyyy}/", True, 1),
}
ONCE_ONLY = (PROVISIONAL, DEGREE)
DESK_ONLY = (DATA_SHEET,)
DEFAULTS = {"degree_awarding_body": UNIVERSITY, "provisional_certificate_issuer": COLLEGE}  # the profile defaults
REQUEST = "Certificate Request"


def seed_certificate_types():
	"""One Certificate Type per print (verifiable, no fee). Existing types are left as configured."""
	for print_format, (prefix, _graduate, needs_approval) in PRINTS.items():
		if not frappe.db.exists("Certificate Type", print_format) and frappe.db.exists("Print Format", print_format):
			frappe.get_doc(
				{
					"doctype": "Certificate Type", "type_name": print_format, "print_format": print_format,
					"number_prefix": prefix, "needs_approval": needs_approval, "verifiable": 1, "enabled": 1,
				}
			).insert(ignore_permissions=True)  # fmt: skip


def require_graduate_approval():
	"""Types seeded before fix round 1 issued graduate documents without approval: set it. DML only; run by a patch."""
	for print_format, (_prefix, _graduate, needs_approval) in PRINTS.items():
		if needs_approval:
			frappe.db.set_value("Certificate Type", {"print_format": print_format, "needs_approval": 0}, "needs_approval", 1)


def types_of(print_formats):
	"""Certificate Type names whose print format is one of `print_formats`."""
	return frappe.get_all("Certificate Type", {"print_format": ["in", list(print_formats)]}, pluck="name")


def desk_only_types():
	"""Certificate Types the portal must not offer (the Degree Data Sheet)."""
	return types_of(DESK_ONLY)


def settings(company):
	profile = get_institution(company)
	return frappe._dict({key: (profile and profile.get(key)) or default for key, default in DEFAULTS.items()})


def available_prints(company):
	"""The examination prints `company` may issue: the degree certificate where the college awards the degree,
	otherwise the degree data sheet for the university."""
	awarding = settings(company).degree_awarding_body
	hidden = DATA_SHEET if awarding == COLLEGE else DEGREE
	return [name for name in PRINTS if name != hidden]


def check_available(print_format, company):
	if print_format in PRINTS and print_format not in available_prints(company):
		if print_format == DEGREE:
			frappe.throw(_("A degree certificate is printed only where the college awards the degree; the university awards it here. Use the Degree Data Sheet."))
		frappe.throw(_("The degree data sheet is for a university that awards the degree; the college awards it here."))


def print_format_of(doc):
	return frappe.db.get_value("Certificate Type", doc.certificate_type, "print_format")


# ---- Certificate Request hooks ---------------------------------------------------------------


def validate_request(doc, method=None):
	"""Certificate Request validate: an examination certificate needs the print available and published results."""
	print_format = print_format_of(doc)
	if print_format not in PRINTS:
		return
	if doc.is_new() and print_format in DESK_ONLY and not frappe.has_permission(REQUEST, "create"):
		frappe.throw(_("The {0} is prepared by the college office for the university.").format(_(print_format)), frappe.PermissionError)
	check_available(print_format, frappe.db.get_value("Student", doc.student, "oc_company"))
	record = graduate_record(doc.student)
	if not record.semesters:
		frappe.throw(_("{0} has no published results yet.").format(frappe.bold(doc.student)))
	if PRINTS[print_format][1] and not record.completed:
		frappe.throw(
			_("{0} is issued once the programme is completed: published final-year results, no arrears and the credits of the regulation.").format(
				_(print_format)
			)
		)
	check_once_only(doc, print_format)


def before_submit_request(doc, method=None):
	"""Certificate Request before_submit: re-check the once-only rule under a lock and freeze the record."""
	print_format = print_format_of(doc)
	if print_format not in PRINTS:
		return
	frappe.db.get_value("Student", doc.student, "name", for_update=True)  # one issue per student at a time
	check_once_only(doc, print_format, lock=True)
	doc.record_snapshot = frappe.as_json(live_record(doc, print_format), indent=None)


def check_once_only(doc, print_format, lock=False):
	"""A Provisional or Degree Certificate is issued once per student; a cancelled one does not count. `lock` reads
	with a locking read (the caller holds the Student lock, taken after this transaction's snapshot)."""
	if print_format not in ONCE_ONLY:
		return
	table = frappe.qb.DocType(REQUEST)
	query = (
		frappe.qb.from_(table)
		.select(table.name)
		.where((table.student == doc.student) & (table.docstatus == 1) & (table.name != doc.name))
		.where(table.certificate_type.isin(types_of([print_format])))
	)
	issued = (query.for_update() if lock else query).run(pluck=True)
	if issued:
		frappe.throw(_("{0} already has a {1}: {2}. Cancel it to issue another.").format(frappe.bold(doc.student), _(print_format), issued[0]))


# ---- print data ------------------------------------------------------------------------------


def live_record(doc, print_format):
	"""The graduate record of the request's student now, with the provisional issuer and the university."""
	company = frappe.db.get_value("Student", doc.student, "oc_company")
	check_available(print_format, company)
	record = graduate_record(doc.student)
	profile = get_institution(company)
	record.university = (profile and profile.affiliating_university) or _("the affiliating university")
	record.provisional_issuer = company if settings(company).provisional_certificate_issuer == COLLEGE else record.university
	return record


def oc_graduate_record(doc, print_format):
	"""Jinja method for the examination prints: an issued request's frozen snapshot, or a draft's live record (a
	preview, refused when `print_format` is not available to the college)."""
	if doc.get("record_snapshot"):
		return json.loads(doc.record_snapshot, object_hook=frappe._dict)
	if doc.docstatus == 0:
		return live_record(doc, print_format)
	frappe.throw(_("{0} was issued without a record snapshot and cannot be reprinted; issue it again.").format(doc.name))
