"""M07-01 / M07-06 Faculty module setup: the faculty profile fields on Employee (blueprint 9.2) and the
qualification fields on Job Applicant. HRMS Employee is the faculty profile; no parallel DocType."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from campus.faculty.attendance_corrections import seed_policy as seed_attendance_correction_policy
from campus.faculty.payroll_setup import FUNDING_MODES, setup_payroll
from campus.faculty.timetable.setup import setup_timetable

MODULE = "Faculty"
CADRES = ["Professor", "Associate Professor", "Assistant Professor"]
QUALIFICATIONS = ["Diploma", "Graduate", "Post Graduate", "Doctorate"]  # lowest first; the rank order of qualification.py
PHD_STATUSES = ["Not Pursuing", "Pursuing", "Submitted", "Awarded"]
NET_SET = ["NET", "SET", "SLET"]
TEACHING = 'eval:doc.oc_staff_type=="Teaching"'


def options(values):
	return "\n" + "\n".join(values)


def setup_faculty():
	create_custom_fields(
		{"Employee": employee_fields(), "Job Applicant": applicant_fields(), "Training Event": training_event_fields(), "Appraisal": appraisal_fields()},
		update=True,
	)
	setup_timetable()
	seed_substitution_template()
	seed_appraisal_review_policy()
	seed_attendance_correction_policy()
	grant_teaching_staff_rights()
	setup_payroll()


# Rights on Education DocTypes the teaching roles need without the office role (Academics User). Custom DocPerm:
# Education's DocType JSON is never edited. Company User Permissions still scope them.
# Once a doctype has Custom DocPerms, the site ignores its standard DocPerms: a later Education upgrade to the
# Course Schedule or Student Attendance permissions does not reach the site (review in the Role Permission Manager).
TEACHING_STAFF_RIGHTS = {
	("Course Schedule", "Instructor"): ("select",),  # pick the period of an Attendance Correction Request at the desk
	("Student Attendance", "HOD"): ("read", "report"),  # the Attendance Shortage report
	("Student Attendance", "Class Advisor"): ("read", "report"),
}
GRANTED_RIGHTS_KEY = "campus_teaching_staff_rights"  # global default: the TEACHING_STAFF_RIGHTS rules already granted


def grant_teaching_staff_rights():
	"""Grant each rule once: a missing row is added with exactly its rights (not Custom DocPerm's default read and
	export), and the rule is recorded as granted. A recorded rule is never touched again, so a right the college
	removes or adds in the Role Permission Manager stays as the college left it."""
	granted = set(frappe.parse_json(frappe.db.get_global(GRANTED_RIGHTS_KEY) or "[]"))
	for (doctype, role), rights in TEACHING_STAFF_RIGHTS.items():
		key = f"{doctype}:{role}"
		if key in granted:
			continue
		if not frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}):
			add_rule(doctype, role, rights)
		granted.add(key)
	frappe.db.set_global(GRANTED_RIGHTS_KEY, frappe.as_json(sorted(granted), indent=None))


def add_rule(doctype, role, rights):
	from frappe.core.doctype.custom_docperm.custom_docperm import update_custom_docperm
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
	from frappe.permissions import add_permission

	name = add_permission(doctype, role, 0)  # copies the standard DocPerms first, so none is lost
	update_custom_docperm(name, {"read": 0, "export": 0, **{right: 1 for right in rights}})
	validate_permissions_for_doctype(doctype)


SUBSTITUTION_EVENT = "substitution.assigned"


SUBSTITUTION_TEMPLATES = [
	(
		SUBSTITUTION_EVENT,
		"Substitution: {{ doc.student_group }} on {{ frappe.format(doc.schedule_date, {'fieldtype': 'Date'}) }}",
		"You are the substitute for {{ doc.absent_faculty_name }} in {{ doc.student_group }} ({{ doc.course }}) on "
		"{{ frappe.format(doc.schedule_date, {'fieldtype': 'Date'}) }}, {{ doc.from_time }} to {{ doc.to_time }}, room {{ doc.room or '-' }}. "
		"You can mark attendance for this period from the substitution.",
	),
	(
		"substitution.cancelled",
		"Substitution cancelled: {{ doc.student_group }} on {{ frappe.format(doc.schedule_date, {'fieldtype': 'Date'}) }}",
		"The substitution for {{ doc.absent_faculty_name }} in {{ doc.student_group }} on "
		"{{ frappe.format(doc.schedule_date, {'fieldtype': 'Date'}) }}, {{ doc.from_time }} to {{ doc.to_time }}, is cancelled. You need not take this class.",
	),
]


def seed_substitution_template():
	"""The notices a substitute gets when a Substitution is confirmed or cancelled; an existing (possibly edited) template is left alone."""
	for event_key, subject, body in SUBSTITUTION_TEMPLATES:
		if frappe.db.exists("Message Template", event_key):
			continue
		frappe.get_doc(
			{
				"doctype": "Message Template", "event_key": event_key, "purpose": "transactional",
				"channels": [{"channel": "email"}, {"channel": "whatsapp"}, {"channel": "sms"}],
				"bodies": [{"language": "en", "subject": subject, "body": body}],
			}
		).insert(ignore_permissions=True)  # fmt: skip


ALLOCATION_POLICY = "Course Allocation - HOD"


def seed_course_allocation_policy():
	"""Course Allocations are approved by the HOD of the allocated department, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": "Course Allocation"}) or not frappe.db.exists("Position", "HOD"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": ALLOCATION_POLICY, "document_type": "Course Allocation",
			"levels": [{"approver_type": "Position", "approver": "HOD", "scope_field": "department", "title": "HOD", "limit_to_company": 1}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


APPRAISAL_REVIEW_POLICY = "Appraisal Review - HOD"
APPRAISAL_REVIEW_PRINCIPAL_POLICY = "Appraisal Review - Principal"
NOT_HOD = 'not doc.get("appraisee_is_hod")'


def seed_appraisal_review_policy():
	"""Self-appraisals are reviewed by the HOD of the appraisee's department, or by the Principal when the appraisee is an HOD
	themselves; a college's own policy for Appraisal Review is left alone."""
	if not frappe.db.exists("Position", "HOD"):
		return
	hod = frappe.db.exists("Approval Policy", APPRAISAL_REVIEW_POLICY)
	if hod:
		if not frappe.db.get_value("Approval Policy", hod, "condition"):
			frappe.db.set_value("Approval Policy", hod, "condition", NOT_HOD)
	elif not frappe.db.exists("Approval Policy", {"document_type": "Appraisal Review"}):
		insert_review_policy(APPRAISAL_REVIEW_POLICY, NOT_HOD, 0, "HOD", "department")
	if not frappe.db.exists("Approval Policy", APPRAISAL_REVIEW_PRINCIPAL_POLICY) and frappe.db.exists("Position", "PRINCIPAL"):
		insert_review_policy(APPRAISAL_REVIEW_PRINCIPAL_POLICY, 'doc.get("appraisee_is_hod")', 1, "PRINCIPAL", "company")


def insert_review_policy(name, condition, priority, position, scope_field):
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": name, "document_type": "Appraisal Review", "condition": condition, "priority": priority,
			"levels": [{"approver_type": "Position", "approver": position, "scope_field": scope_field, "title": position.title(), "limit_to_company": 1}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def grant_employee_role(employee, method=None):
	"""Teaching staff with a login get the HRMS Employee role (it carries their rights on Appraisal; Appraisal permissions
	are HRMS's and are not copied into Custom DocPerm). Doc event of Employee and the onboarding helper."""
	if employee.get("oc_staff_type") != "Teaching" or not employee.get("user_id") or employee.user_id == "Administrator":
		return
	if "Employee" not in frappe.get_roles(employee.user_id):
		frappe.get_doc("User", employee.user_id).add_roles("Employee")


def training_event_fields():
	return [
		field(
			"oc_is_fdp", "Check", "Faculty Development Programme", "type",
			description="Counted as an FDP in a teacher's self-appraisal and in NAAC 6.3.4.",
		),
	]  # fmt: skip


def appraisal_fields():
	"""The API (self-appraisal) result on an HRMS Appraisal; written only by campus.faculty.self_appraisal."""
	return [
		field("oc_api_section", "Section Break", "API Self-Appraisal", "company", collapsible=1),
		field("oc_api_rule", "Link", "API Score Rule", "oc_api_section", options="API Score Rule", read_only=1, no_copy=1),
		field("oc_api_total", "Float", "API Points", "oc_api_rule", read_only=1, no_copy=1),
		field("oc_api_breakdown", "Small Text", "API Breakdown", "oc_api_total", read_only=1, no_copy=1),
		field(
			"oc_api_override_reason", "Small Text", "HR Override Reason", "oc_api_breakdown", no_copy=1,
			description="Only HR can submit a self-appraisal without the HOD review, and must give the reason here.",
		),
		field("oc_api_override_by", "Link", "Override By", "oc_api_override_reason", options="User", read_only=1, no_copy=1),
	]  # fmt: skip


def employee_fields():
	return faculty_profile_fields()


def faculty_profile_fields():
	return [
		field("oc_faculty_tab", "Tab Break", "Faculty", "old_parent"),
		field("oc_staff_type", "Select", "Staff Type", "oc_faculty_tab", options=options(["Teaching", "Non-teaching", "Project"]), in_standard_filter=1),
		field("oc_cadre", "Select", "Cadre", "oc_staff_type", options=options(CADRES), depends_on=TEACHING, mandatory_depends_on=TEACHING, in_standard_filter=1),
		field("oc_funding_mode", "Select", "Funding Mode", "oc_cadre", options=options(FUNDING_MODES)),
		field("oc_pay_scale", "Data", "Pay Scale", "oc_funding_mode"),
		field("oc_aicte_faculty_id", "Data", "AICTE Faculty ID", "oc_pay_scale"),
		field("oc_faculty_column", "Column Break", None, "oc_aicte_faculty_id"),
		*qualification_fields("oc_faculty_column"),
		field("oc_specialisation", "Data", "Specialisation", "oc_prior_teaching_experience"),
		field("oc_research_guide", "Check", "Recognised Research Guide", "oc_specialisation"),
		field("oc_research_ids_section", "Section Break", "Research Identifiers", "oc_research_guide"),
		field("oc_orcid", "Data", "ORCID", "oc_research_ids_section"),
		field("oc_scopus_id", "Data", "Scopus Author ID", "oc_orcid"),
		field("oc_vidwan_irins_url", "Data", "Vidwan / IRINS Profile URL", "oc_scopus_id", options="URL"),
		field("oc_qualification_section", "Section Break", "Qualification Check", "oc_vidwan_irins_url", depends_on=TEACHING),
		field("oc_qualification_shortfall", "Small Text", "Shortfall Against Faculty Norm", "oc_qualification_section", read_only=1),
		field(
			"oc_qualification_override_reason", "Small Text", "Override Reason", "oc_qualification_shortfall",
			description="Needed, from the Principal, to appoint or change a teacher whose qualification is below the norm.",
		),
		field("oc_qualification_override_by", "Link", "Override By", "oc_qualification_override_reason", options="User", read_only=1),
	]  # fmt: skip


def applicant_fields():
	return [
		field("oc_cadre", "Select", "Cadre", "designation", options=options(CADRES)),
		*qualification_fields("oc_cadre"),
		field("oc_qualification_shortfall", "Small Text", "Shortfall Against Faculty Norm", "oc_prior_teaching_experience", read_only=1),
	]


def qualification_fields(insert_after):
	return [
		field("oc_highest_qualification", "Select", "Highest Qualification", insert_after, options=options(QUALIFICATIONS)),
		field("oc_phd_status", "Select", "PhD Status", "oc_highest_qualification", options=options(PHD_STATUSES)),
		field("oc_phd_awarded_on", "Date", "PhD Awarded On", "oc_phd_status", depends_on='eval:doc.oc_phd_status=="Awarded"'),
		field("oc_net_set", "Select", "NET / SET / SLET", "oc_phd_awarded_on", options=options(NET_SET)),
		field("oc_prior_teaching_experience", "Float", "Teaching Experience Before Joining (Years)", "oc_net_set"),
	]


def field(fieldname, fieldtype, label, insert_after, **kwargs):
	return {"fieldname": fieldname, "fieldtype": fieldtype, "label": label, "insert_after": insert_after, "module": MODULE, "permlevel": 0, **kwargs}


PERM_FLAGS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import", "share", "print", "email", "select", "if_owner")
PROFILE_FIELDS_ONCE_AT_PERMLEVEL_ONE = (
	"oc_aicte_faculty_id", "oc_highest_qualification", "oc_phd_status", "oc_phd_awarded_on", "oc_net_set",
	"oc_prior_teaching_experience", "oc_qualification_shortfall", "oc_qualification_override_reason", "oc_qualification_override_by",
)  # fmt: skip


def undo_permlevel_one():
	"""Undo fix round 1 of P2-T05 on a site that ran it: the profile fields go back to permlevel 0 and the Employee
	Custom DocPerm rows that move created go away. Idempotent and DML only.

	`add_permission` copies every standard Employee permission into Custom DocPerm the first time it is used, which
	freezes the standard permissions. So: if Employee's permlevel-0 Custom DocPerm rows are exactly the standard
	DocPerm rows (same roles and flags), nobody customised Employee and all rows are removed so the standard
	permissions apply again. Otherwise only the permlevel-1 rows of HR Manager, HR User and Principal are removed.
	"""
	for fieldname in PROFILE_FIELDS_ONCE_AT_PERMLEVEL_ONE:
		frappe.db.set_value("Custom Field", {"dt": "Employee", "fieldname": fieldname}, "permlevel", 0)
	custom = frappe.get_all("Custom DocPerm", {"parent": "Employee"}, ["name", "role", "permlevel", *PERM_FLAGS])
	if not custom:
		return
	if copies_standard_permissions(custom):
		frappe.db.delete("Custom DocPerm", {"parent": "Employee"})
	else:
		frappe.db.delete("Custom DocPerm", {"parent": "Employee", "permlevel": 1, "role": ["in", ["HR Manager", "HR User", "Principal"]]})
	frappe.clear_cache(doctype="Employee")


def copies_standard_permissions(custom):
	"""True when the permlevel 0 and 1 Custom DocPerm rows are the standard rows plus only HR Manager, HR User and Principal at permlevel 1."""
	standard = frappe.get_all("DocPerm", {"parent": "Employee"}, ["role", "permlevel", *PERM_FLAGS])
	ours = {(r.role, r.permlevel) for r in custom if r.permlevel == 1 and r.role in ("HR Manager", "HR User", "Principal")}
	rest = [r for r in custom if (r.role, r.permlevel) not in ours]
	key = lambda r: tuple(sorted((k, v or 0) for k, v in r.items() if k != "name"))  # noqa: E731
	return sorted(map(key, rest)) == sorted(map(key, standard))
