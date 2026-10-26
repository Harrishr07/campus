"""M01-03 Seed Export Templates: the NAAC AQAR Excel and PDF layouts, and empty NBA SAR / NIRF mappings.

The regulators' official templates are not available, so every layout here is a labelled placeholder: the AQAR ones put
each answer node on a sheet per criterion (or a PDF section) in code order, and the NBA / NIRF ones are empty mappings on
Draft frameworks with no nodes yet. A college edits the mapping rows (they are data); seeding never overwrites a template
that exists. Seeding runs on every migrate: a deleted placeholder template is made again, and so is its NBA-SAR / NIRF
Draft framework when that is gone too (delete neither while the seed lists it; leave an unused one empty instead).
"""

import frappe

from campus.iqac.setup import FRAMEWORK

AQAR_EXCEL, AQAR_PDF = "NAAC AQAR Excel", "NAAC AQAR PDF"
NBA_EXCEL, NIRF_EXCEL = "NBA SAR Excel", "NIRF Excel"
NBA_FRAMEWORK, NIRF_FRAMEWORK = "NBA-SAR", "NIRF"
ANSWER_NODES = ["Metric", "Sub-Metric", "Extended Profile"]
FIRST_ROW = 4
PLACEHOLDER_NOTE = "Placeholder layout - the official {0} template was not available; replace the mappings with the official layout."
EMPTY_NOTE = "Placeholder mapping - the {0} framework has no nodes yet; map them here once they are defined."


def seed_export_templates():
	"""Create the placeholder Export Templates that are missing."""
	if frappe.db.exists("Accreditation Framework", FRAMEWORK):
		nodes = answer_nodes()
		make_template(AQAR_EXCEL, FRAMEWORK, "Excel", PLACEHOLDER_NOTE.format("NAAC AQAR"), excel_rows(nodes))
		make_template(AQAR_PDF, FRAMEWORK, "PDF", PLACEHOLDER_NOTE.format("NAAC AQAR"), pdf_rows(nodes))
	for framework, template in ((NBA_FRAMEWORK, NBA_EXCEL), (NIRF_FRAMEWORK, NIRF_EXCEL)):
		if frappe.db.exists("Export Template", template):
			continue
		if not frappe.db.exists("Accreditation Framework", framework):
			frappe.get_doc(
				{
					"doctype": "Accreditation Framework",
					"framework_name": framework,
					"framework_code": framework,
				}
			).insert(ignore_permissions=True)
		make_template(template, framework, "Excel", EMPTY_NOTE.format(framework), [])


def make_template(name, framework, export_format, description, rows):
	if frappe.db.exists("Export Template", name):
		return
	frappe.get_doc(
		{
			"doctype": "Export Template", "template_name": name, "framework": framework, "export_format": export_format,
			"is_placeholder": 1, "description": description, "mappings": rows,
		}
	).insert(ignore_permissions=True)  # fmt: skip


def answer_nodes():
	"""Answer nodes of the AQAR framework in code order (Extended Profile first), each with whether it has a Data Template slot."""
	with_slot = set(
		frappe.get_all(
			"Framework Node Evidence Slot",
			{"parenttype": "Framework Node", "slot_name": "Data Template"},
			pluck="parent",
		)
	)
	nodes = frappe.get_all(
		"Framework Node",
		{"framework": FRAMEWORK, "node_type": ["in", ANSWER_NODES]},
		["name", "code", "node_type"],
	)
	for node in nodes:
		node.data_sheet = int(node.name in with_slot and node.node_type == "Metric")
	return sorted(nodes, key=lambda n: (n.node_type != "Extended Profile", natural(n.code)))


def natural(code):
	return [int(part) if part.isdigit() else 0 for part in code.replace("EP-", "").split(".")]


def excel_rows(nodes):
	"""Sheet `Extended Profile` and one `Criterion <n>` per criterion; label in column A, value in column B."""
	used, rows = {}, []
	for node in nodes:
		sheet = (
			"Extended Profile"
			if node.node_type == "Extended Profile"
			else f"Criterion {node.code.split('.')[0]}"
		)
		used[sheet] = used.get(sheet, FIRST_ROW - 1) + 1
		rows.append(
			{
				"node": node.name,
				"sheet": sheet,
				"cell": f"B{used[sheet]}",
				"label_cell": f"A{used[sheet]}",
				"data_sheet": node.data_sheet,
			}
		)
	return rows


def pdf_rows(nodes):
	"""Extended Profile, then Part B (every criterion's metrics in code order); the cover block is Part A."""
	return [
		{"node": n.name, "section": "Extended Profile" if n.node_type == "Extended Profile" else "Part B"}
		for n in nodes
	]
