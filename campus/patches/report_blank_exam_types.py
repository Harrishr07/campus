"""M06-12 Report curriculum courses with a blank exam type (course type) without filling them in.

A blank exam type is not Internal Only and not Theory: the Result Run refuses to start for an offering of such a
row, so the COE sets each one explicitly. This patch only lists them (migrate output and one Error Log).
"""

import frappe


def execute():
	rows = frappe.get_all(
		"Curriculum Course",
		{"parenttype": "Curriculum", "exam_type": ["is", "not set"]},
		["parent", "semester", "course"],
		order_by="parent, semester, idx",
	)
	if not rows:
		return
	lines = [f"{row.parent} semester {row.semester}: {row.course}" for row in rows]
	message = (
		"Curriculum courses with no exam type (set each explicitly; Result Runs refuse them):\n"
		+ "\n".join(lines)
	)
	print(f"campus: {len(rows)} " + message)
	frappe.log_error(title="Curriculum courses with no exam type", message=message)
