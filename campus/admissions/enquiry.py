"""M04-05 Enquiry CRM: web enquiry -> Lead -> WhatsApp acknowledgement -> round-robin officer -> Applicant.

- A Lead created from the "admission-enquiry" web form, or carrying a program of interest, gets the
  "admission.enquiry_ack" message (transactional, so no consent record is needed) and is assigned to an
  Admission Officer of its company. Assignment is ERPNext's/Frappe's Assignment Rule (Round Robin), one rule
  per company whose users are refreshed from the officers' Company User Permissions; the rule only assigns
  a Lead that has no assignment yet, so repeated saves never reassign.
- Guest submissions are guarded by a hidden honeypot field and a per-IP hourly limit.
- `convert_lead_to_applicant` is idempotent and links Lead and Student Applicant both ways.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint

from campus.admissions.setup import OFFICER_ROLE
from campus.campus_messaging.api import send

ACK_EVENT = "admission.enquiry_ack"
WEB_FORM_SOURCE = "Website Enquiry"
GUEST_LIMIT, GUEST_WINDOW_SECONDS = 10, 3600  # enquiries per IP per hour
RULE_PREFIX = "Enquiry Round Robin - "
WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# ---- Lead hooks ---------------------------------------------------------------------------

def before_insert(doc, method=None):
	if frappe.session.user == "Guest":
		guard_guest_submission(doc)
	if frappe.flags.in_web_form and not doc.utm_source:
		doc.utm_source = WEB_FORM_SOURCE


def validate(doc, method=None):
	if doc.company and doc.oc_program_interest:
		program_company = frappe.db.get_value("Program", doc.oc_program_interest, "oc_company")
		if program_company and program_company != doc.company:
			frappe.throw(_("Program {0} is not offered by {1}.").format(doc.oc_program_interest, doc.company))


def after_insert(doc, method=None):
	if not (doc.oc_program_interest or frappe.flags.in_web_form):
		return
	if doc.company:
		sync_assignment_rule(doc.company)  # before Frappe's own on_update assignment hook runs
	acknowledge(doc)


def guard_guest_submission(doc):
	if doc.oc_website_url:  # honeypot: humans never see the field
		frappe.throw(_("Could not accept the enquiry."))
	if not (doc.company and frappe.db.exists("Institution Profile", {"company": doc.company})):
		frappe.throw(_("Please choose a college from the list."))
	key = frappe.cache.make_key(f"oc-enquiry-rate-{getattr(frappe.local, 'request_ip', None) or 'unknown'}")
	count = frappe.cache.incrby(key, 1)
	if count == 1:
		frappe.cache.expire(key, GUEST_WINDOW_SECONDS)
	if count > GUEST_LIMIT:
		frappe.throw(_("Too many enquiries from this address. Please try again later."), frappe.RateLimitExceededError)


# ---- acknowledgement ----------------------------------------------------------------------

def whatsapp_number(doc):
	"""The enquirer's number in +91 form, or None."""
	number = re.sub(r"[^\d+]", "", doc.whatsapp_no or doc.mobile_no or "")
	if re.fullmatch(r"[6-9]\d{9}", number):
		return "+91" + number
	if re.fullmatch(r"(91|0)?[6-9]\d{9}", number):
		return "+91" + number[-10:]
	return number if number.startswith("+") and len(number) >= 11 else None


def acknowledge(doc):
	number = whatsapp_number(doc)
	if not number:
		return
	try:
		send(ACK_EVENT, doc, [f"phone:{number}"])
	except Exception:  # an enquiry must be saved even when messaging is down
		frappe.log_error(title=f"Enquiry acknowledgement failed for {doc.name}", message="See the Message Log.")


# ---- round-robin assignment ---------------------------------------------------------------

def company_officers(company):
	"""Enabled Admission Officers permitted for the company, in a stable order."""
	officers = frappe.get_all(
		"Has Role", {"role": OFFICER_ROLE, "parenttype": "User"}, pluck="parent", order_by="parent", limit=0
	)
	permitted = frappe.get_all(
		"User Permission", {"allow": "Company", "for_value": company, "user": ("in", officers or [""])},
		pluck="user", limit=0,
	)  # fmt: skip
	enabled = frappe.get_all("User", {"name": ("in", permitted or [""]), "enabled": 1}, pluck="name", order_by="name", limit=0)
	return enabled


def sync_assignment_rule(company):
	"""Create or refresh the company's Round Robin rule for new enquiries; disabled when it has no officers."""
	officers = company_officers(company)
	name = RULE_PREFIX + company
	rule = frappe.get_doc("Assignment Rule", name) if frappe.db.exists("Assignment Rule", name) else None
	if rule and [u.user for u in rule.users] == officers and bool(rule.disabled) == (not officers):
		return
	if not rule:
		if not officers:
			return
		rule = frappe.new_doc("Assignment Rule")
		rule.update(
			{
				"name": name, "document_type": "Lead", "rule": "Round Robin", "priority": 10,
				"assign_condition": f"company == {json.dumps(company)}",
				"description": "Follow up on enquiry {{ lead_name }}",
				"assignment_days": [{"day": d} for d in WEEK],
			}
		)  # fmt: skip
	rule.set("users", [{"user": u} for u in officers])
	rule.disabled = 0 if officers else 1
	rule.save(ignore_permissions=True)


# ---- conversion ---------------------------------------------------------------------------

def split_name(full_name):
	"""(first, middle, last): first word, last word, anything between."""
	parts = (full_name or "").split()
	if len(parts) < 2:
		return (parts[0] if parts else ""), "", ""
	return parts[0], " ".join(parts[1:-1]), parts[-1]


def default_academic_year():
	today = frappe.utils.nowdate()
	current = frappe.db.get_value(
		"Academic Year", {"year_end_date": (">=", today)}, "name", order_by="year_start_date asc"
	)
	return current or frappe.db.get_value("Academic Year", {}, "name", order_by="year_start_date desc")


def convert_lead_to_applicant(lead, academic_year=None):
	"""Create (once) the Student Applicant for the Lead and link both ways; later calls return the same one."""
	frappe.has_permission("Lead", "write", lead, throw=True)
	frappe.has_permission("Student Applicant", "create", throw=True)
	frappe.db.get_value("Lead", lead, "name", for_update=True)  # serialise concurrent conversions
	existing = frappe.db.get_value("Student Applicant", {"oc_lead": lead}, "name")
	if existing:
		return existing
	doc = frappe.get_doc("Lead", lead)
	if not doc.oc_program_interest:
		frappe.throw(_("Set the program of interest on the enquiry before converting it."))
	first, middle, last = split_name(doc.lead_name)
	year = academic_year or default_academic_year()
	if not year:
		frappe.throw(_("No Academic Year exists to admit the applicant into."))
	applicant = frappe.get_doc(
		{
			"doctype": "Student Applicant", "first_name": first, "middle_name": middle, "last_name": last,
			"student_email_id": doc.email_id, "student_mobile_number": doc.mobile_no,
			"program": doc.oc_program_interest, "academic_year": year, "oc_company": doc.company, "oc_lead": lead,
		}
	).insert()  # fmt: skip
	frappe.db.set_value("Lead", lead, {"oc_applicant": applicant.name, "status": "Converted"})
	return applicant.name
