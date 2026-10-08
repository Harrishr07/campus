"""M07-01 / M07-06 Faculty module setup: the faculty profile fields on Employee (blueprint 9.2) and the
qualification fields on Job Applicant. HRMS Employee is the faculty profile; no parallel DocType."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Faculty"
CADRES = ["Professor", "Associate Professor", "Assistant Professor"]
QUALIFICATIONS = ["Diploma", "Graduate", "Post Graduate", "Doctorate"]  # lowest first; the rank order of qualification.py
PHD_STATUSES = ["Not Pursuing", "Pursuing", "Submitted", "Awarded"]
NET_SET = ["NET", "SET", "SLET"]
TEACHING = 'eval:doc.oc_staff_type=="Teaching"'


def options(values):
	return "\n" + "\n".join(values)


def setup_faculty():
	create_custom_fields({"Employee": employee_fields(), "Job Applicant": applicant_fields()}, update=True)


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


def employee_fields():
	return faculty_profile_fields()


def faculty_profile_fields():
	return [
		field("oc_faculty_tab", "Tab Break", "Faculty", "old_parent"),
		field("oc_staff_type", "Select", "Staff Type", "oc_faculty_tab", options=options(["Teaching", "Non-teaching", "Project"]), in_standard_filter=1),
		field("oc_cadre", "Select", "Cadre", "oc_staff_type", options=options(CADRES), depends_on=TEACHING, mandatory_depends_on=TEACHING, in_standard_filter=1),
		field("oc_funding_mode", "Select", "Funding Mode", "oc_cadre", options=options(["Aided", "Self-financing"])),
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
