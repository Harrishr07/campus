"""M06-07, M05-04 Examination certificates on the P1-T20 certificate pattern: each print is a Certificate Type whose
Certificate Request (portal or desk, ownership-checked, fee if the type has one) issues a Verifiable Document (QR)
on submit. A Transcript Request is a Certificate Request of the Transcript type.

Prints (doc type Certificate Request, values from campus.examinations.graduation, published results only):
Transcript (every published semester), Consolidated Grade Sheet, Provisional Certificate (issuer per the Institution
Profile's provisional_certificate_issuer), Degree Certificate (only when degree_awarding_body is College) and
Degree Data Sheet (for the university, when it awards the degree). The semester Grade Sheet stays on Student Result
(examinations.api.issue_grade_sheet).

A request is refused (validate, so at request and at issue) when its print is not available to the student's
college, when the student has no published result, or, for the graduate prints, before the programme is completed.
Rendering refuses an unavailable print too, so switching the setting withdraws the degree print at once.
"""

import frappe
from frappe import _

from campus.campus_platform.api import get_institution
from campus.examinations.graduation import graduate_record

TRANSCRIPT, CONSOLIDATED, PROVISIONAL, DEGREE, DATA_SHEET = (
	"Transcript", "Consolidated Grade Sheet", "Provisional Certificate", "Degree Certificate", "Degree Data Sheet",
)  # fmt: skip
COLLEGE, UNIVERSITY = "College", "University"
# print format (= seeded Certificate Type) -> (number prefix, needs a completed programme)
PRINTS = {
	TRANSCRIPT: ("TRN/{abbr}/{yyyy}/", False),
	CONSOLIDATED: ("CGS/{abbr}/{yyyy}/", True),
	PROVISIONAL: ("PC/{abbr}/{yyyy}/", True),
	DEGREE: ("DEG/{abbr}/{yyyy}/", True),
	DATA_SHEET: ("DDS/{abbr}/{yyyy}/", True),
}
DEFAULTS = {"degree_awarding_body": UNIVERSITY, "provisional_certificate_issuer": COLLEGE}  # the profile defaults


def seed_certificate_types():
	"""One Certificate Type per print (verifiable, no approval, no fee). Existing types are left as configured."""
	for print_format, (prefix, _graduate) in PRINTS.items():
		if not frappe.db.exists("Certificate Type", print_format) and frappe.db.exists("Print Format", print_format):
			frappe.get_doc(
				{
					"doctype": "Certificate Type", "type_name": print_format, "print_format": print_format,
					"number_prefix": prefix, "needs_approval": 0, "verifiable": 1, "enabled": 1,
				}
			).insert(ignore_permissions=True)  # fmt: skip


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


def validate_request(doc, method=None):
	"""Certificate Request hook: an examination certificate needs the print available and published results."""
	print_format = frappe.db.get_value("Certificate Type", doc.certificate_type, "print_format")
	if print_format not in PRINTS:
		return
	check_available(print_format, frappe.db.get_value("Student", doc.student, "oc_company"))
	record = graduate_record(doc.student)
	if not record.semesters:
		frappe.throw(_("{0} has no published results yet.").format(frappe.bold(doc.student)))
	if PRINTS[print_format][1] and not record.completed:
		frappe.throw(
			_("{0} is issued once the programme is completed: published final-year results and no arrears.").format(_(print_format))
		)


def oc_graduate_record(doc, print_format):
	"""Jinja method for the examination prints: the graduate record of the request's student, with the issuer of
	the provisional certificate and the university. Throws when `print_format` is not available to the college."""
	company = frappe.db.get_value("Student", doc.student, "oc_company")
	check_available(print_format, company)
	record = graduate_record(doc.student)
	profile = get_institution(company)
	record.university = (profile and profile.affiliating_university) or _("the affiliating university")
	record.provisional_issuer = company if settings(company).provisional_certificate_issuer == COLLEGE else record.university
	return record
