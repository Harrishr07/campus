"""P2-T05 demo faculty (M07-01): an AICTE-style Faculty Norm, 2026-27 sanctioned posts and the profiles of the
four demo instructors (all CSE, joined 2015-06-01). Idempotent; called from demo.build_base.

Numbers the faculty reports reproduce for 2026-27: sanctioned CSE 1/2/6 and ECE 1/1/3 (14), teachers 4 (Professor,
Associate Professor, two Assistant Professors), 2 with a PhD, 12 years' experience each.
"""

import frappe

from campus.tests.demo import CSE_DEPARTMENT, ECE_DEPARTMENT, ENGINEERING, department_name, employee_of, get_or_insert

YEAR = "2026-27"
NORM_FROM = "2022-06-01"
# cadre, ratio share, minimum qualification, PhD required, minimum experience (years), min / max teaching hours a week
NORM_CADRES = [
	("Professor", 1, "Post Graduate", 1, 10, 8, 14),
	("Associate Professor", 2, "Post Graduate", 1, 8, 10, 16),
	("Assistant Professor", 6, "Post Graduate", 0, 0, 12, 18),
]
ALLOCATION_POLICY = "Course Allocation - HOD"
SANCTIONED = {CSE_DEPARTMENT: (1, 2, 6), ECE_DEPARTMENT: (1, 1, 3)}
# username -> cadre, PhD status, PhD awarded on, NET/SET, prior experience, funding mode
PROFILES = {
	"hod_cse": ("Professor", "Awarded", "2014-03-15", "", 11, "Aided"),
	"faculty_1": ("Associate Professor", "Awarded", "2019-09-01", "", 9, "Aided"),
	"faculty_2": ("Assistant Professor", "Pursuing", None, "NET", 2, "Self-financing"),
	"faculty_3": ("Assistant Professor", "Not Pursuing", None, "", 0, "Self-financing"),
}


def make_faculty():
	make_norm()
	make_allocation_policy()
	make_sanctioned_posts()
	make_profiles()


def make_norm():
	get_or_insert(
		"Faculty Norm",
		{"company": ENGINEERING, "effective_from": NORM_FROM},
		{
			"norm_name": "AICTE APH (demo)", "regulator": "AICTE", "student_faculty_ratio": 20,
			"cadres": [
				{
					"cadre": c, "ratio_share": s, "minimum_qualification": q, "requires_phd": p, "minimum_experience_years": e,
					"min_hours_per_week": lo, "max_hours_per_week": hi,
				}
				for c, s, q, p, e, lo, hi in NORM_CADRES
			],
		},
	)  # fmt: skip


def make_allocation_policy():
	"""Course Allocations are approved by the HOD of the allocated department (M07-02)."""
	was_importing, frappe.flags.in_import = frappe.flags.in_import, False  # import mode skips the defaults (enabled, limit to company)
	try:
		get_or_insert(
			"Approval Policy",
			{"policy_name": ALLOCATION_POLICY, "document_type": "Course Allocation"},
			{
				"enabled": 1, "on_final_action": "Submit",
				"levels": [{"approver_type": "Position", "approver": "HOD", "scope_field": "department", "title": "HOD", "limit_to_company": 1}],
			},
		)
	finally:
		frappe.flags.in_import = was_importing


def make_sanctioned_posts():
	for department, counts in SANCTIONED.items():
		for (cadre, *_rule), count in zip(NORM_CADRES, counts):
			get_or_insert(
				"Sanctioned Post",
				{"department": department_name(department, ENGINEERING), "cadre": cadre, "academic_year": YEAR},
				{"sanctioned_count": count},
			)


def make_profiles():
	for username, (cadre, phd, awarded_on, net_set, prior, funding) in PROFILES.items():
		employee = frappe.get_doc("Employee", employee_of(username))
		if employee.oc_cadre == cadre:
			continue
		employee.update({
			"department": department_name(CSE_DEPARTMENT, ENGINEERING), "oc_staff_type": "Teaching", "oc_cadre": cadre,
			"oc_highest_qualification": "Post Graduate", "oc_phd_status": phd, "oc_phd_awarded_on": awarded_on,
			"oc_net_set": net_set, "oc_prior_teaching_experience": prior, "oc_funding_mode": funding,
			"oc_specialisation": "Computer Science",
		})  # fmt: skip
		employee.save(ignore_permissions=True)
