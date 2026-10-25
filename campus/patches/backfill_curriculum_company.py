"""M03-01 Back-fill `company` on existing Curriculum records so they appear in scoped list views."""

import frappe


def execute():
	"""Back-fill `company` on existing Curriculum records where company is NULL or blank."""
	if not frappe.db.table_exists("Curriculum"):
		return

	global_default = frappe.db.get_single_value("Global Defaults", "default_company")
	fallback_company = global_default or frappe.db.get_value("Company", {}, "name")

	curricula = frappe.db.sql(
		"""
		SELECT name, program, regulation, owner
		FROM `tabCurriculum`
		WHERE company IS NULL OR company = ''
		""",
		as_dict=True,
	)

	if not curricula:
		return

	for cur in curricula:
		company = None
		if cur.program:
			company = frappe.db.get_value("Program", cur.program, "oc_company")
		if not company and cur.regulation:
			company = frappe.db.get_value("Regulation", cur.regulation, "company")
		if not company and cur.owner:
			company = frappe.db.get_value("User Permission", {"user": cur.owner, "allow": "Company"}, "for_value")
		if not company:
			company = fallback_company

		if company:
			frappe.db.set_value("Curriculum", cur.name, "company", company, update_modified=False)

	frappe.db.commit()
