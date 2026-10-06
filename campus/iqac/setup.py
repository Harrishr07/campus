"""M15-01 IQAC setup: the IQAC Coordinator role and the seeded NAAC AQAR framework."""

import frappe

FRAMEWORK = "NAAC-AQAR-RAF2017"
PASS_PCT = "round(final_year_passed / final_year_appeared * 100, 2)"
# code, title, node type, parent code, formula; titles are placeholders
NODES = [
	("2", "Teaching-Learning and Evaluation", "Criterion", None, None),
	("2.1", "Student Enrolment and Profile", "Key Indicator", "2", None),
	("2.6", "Student Performance and Learning Outcomes", "Key Indicator", "2", None),
	("2.1.1", "Students admitted", "Metric", "2.1", "students_admitted"),
	("2.6.3", "Pass percentage of final year students", "Metric", "2.6", PASS_PCT),
]


def ensure_iqac_role():
	if not frappe.db.exists("Role", "IQAC Coordinator"):
		frappe.get_doc({"doctype": "Role", "role_name": "IQAC Coordinator", "desk_access": 1}).insert(
			ignore_permissions=True
		)


def seed_framework():
	"""Create the NAAC AQAR framework and its nodes when missing; never overwrites edited nodes."""
	if not frappe.db.exists("Accreditation Framework", FRAMEWORK):
		frappe.get_doc({"doctype": "Accreditation Framework", "framework_name": FRAMEWORK}).insert(
			ignore_permissions=True
		)
	for code, title, node_type, parent, formula in NODES:
		if frappe.db.exists("Framework Node", f"{FRAMEWORK}-{code}"):
			continue
		frappe.get_doc(
			{
				"doctype": "Framework Node", "framework": FRAMEWORK, "code": code, "title": title,
				"node_type": node_type, "formula": formula,
				"parent_node": parent and f"{FRAMEWORK}-{parent}",
			}  # fmt: skip
		).insert(ignore_permissions=True)
