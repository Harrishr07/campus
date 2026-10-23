"""M03-02 Outcomes and mapping matrices: PEO / PO / PSO per programme and regulation, Course Outcomes per course and
curriculum, and the CO-PO Matrix of a course in a curriculum.

A matrix belongs to one curriculum version, so an offering (a Student Group carrying `oc_curriculum`) always resolves
to the matrix of the curriculum it was generated from: a 2022-batch offering uses the R2022 matrix even after R2026
adds its own. The Course Outcome record is canonical. The CO tags already on CIA questions, question bank items and
feedback questions are its `co_code`; CIA and bank tags are checked against the course's Course Outcomes once the
course has any (a course without them keeps free tags).

NBA Programme Outcomes PO1-PO12 are seeded per programme and regulation with their short titles. The statements are
placeholders until the official wording is loaded.
"""

import re

import frappe
from frappe import _

PO, PSO = "Program Outcome", "Program Specific Outcome"
MATRIX, CELL = "CO-PO Matrix", "CO-PO Correlation"
CORRELATIONS = range(0, 4)
MATRIX_POLICY = "CO-PO Matrix - HOD"

NBA_PROGRAM_OUTCOMES = (
	"Engineering knowledge",
	"Problem analysis",
	"Design/development of solutions",
	"Conduct investigations of complex problems",
	"Modern tool usage",
	"The engineer and society",
	"Environment and sustainability",
	"Ethics",
	"Individual and team work",
	"Communication",
	"Project management and finance",
	"Life-long learning",
)


def normalise_code(code):
	"""A CO / PO code without spaces, in capitals ("co 1" -> "CO1")."""
	return re.sub(r"\s+", "", code or "").upper()


def code_order(code):
	"""Sort key putting CO2 before CO10."""
	match = re.match(r"(\D*)(\d*)", code or "")
	return (match.group(1), int(match.group(2) or 0), code)


# Masters


def check_programme_regulation(program, regulation):
	if not frappe.db.exists("Regulation Program", {"parent": regulation, "parenttype": "Regulation", "program": program}):
		frappe.throw(_("Regulation {0} does not cover programme {1}.").format(frappe.bold(regulation), frappe.bold(program)))


@frappe.whitelist(methods=["POST"])
def seed_program_outcomes(program, regulation):
	"""Add the NBA PO1-PO12 the programme lacks under the regulation; returns the names created."""
	frappe.has_permission(PO, "create", throw=True)
	check_programme_regulation(program, regulation)
	created = []
	for number, title in enumerate(NBA_PROGRAM_OUTCOMES, 1):
		code = f"PO{number}"
		if frappe.db.exists(PO, {"program": program, "regulation": regulation, "po_code": code}):
			continue
		statement = _("{0} (placeholder - replace with the official NBA wording)").format(title)
		doc = frappe.get_doc({"doctype": PO, "program": program, "regulation": regulation, "po_code": code, "title": title, "statement": statement})
		created.append(doc.insert().name)
	return created


def seed_co_po_matrix_policy():
	"""CO-PO Matrices are approved by the HOD of the course's department, unless the college has its own policy."""
	if frappe.db.exists("Approval Policy", {"document_type": MATRIX}) or not frappe.db.exists("Position", "HOD"):
		return
	frappe.get_doc(
		{
			"doctype": "Approval Policy", "policy_name": MATRIX_POLICY, "document_type": MATRIX,
			"levels": [{"approver_type": "Position", "approver": "HOD", "scope_field": "department", "title": "HOD", "limit_to_company": 1}],
		}
	).insert(ignore_permissions=True)  # fmt: skip


def programme_outcomes(program, regulation):
	"""[{doctype, name, code, statement}] of the programme's POs then PSOs under the regulation, in code order."""
	result = []
	for doctype, field in ((PO, "po_code"), (PSO, "pso_code")):
		rows = frappe.get_all(doctype, {"program": program, "regulation": regulation}, ["name", f"{field} as code", "statement"])
		result += [frappe._dict(row, doctype=doctype) for row in sorted(rows, key=lambda r: code_order(r.code))]
	return result


def course_outcomes(course, curriculum):
	"""[{name, co_code, statement, bloom_level}] of the course's outcomes in the curriculum, in code order."""
	rows = frappe.get_all("Course Outcome", {"course": course, "curriculum": curriculum}, ["name", "co_code", "statement", "bloom_level"])
	return sorted(rows, key=lambda r: code_order(r.co_code))


# Versions


def matrix_for(course, curriculum):
	"""The approved (submitted) CO-PO Matrix of the course in the curriculum, or None."""
	return frappe.db.get_value(MATRIX, {"course": course, "curriculum": curriculum, "docstatus": 1})


def matrix_for_offering(offering):
	"""The approved matrix of an offering's course in the curriculum the offering was generated from, or None."""
	row = frappe.db.get_value("Student Group", offering, ["course", "oc_curriculum"], as_dict=True)
	if not row or not row.course or not row.oc_curriculum:
		return None
	return matrix_for(row.course, row.oc_curriculum)


# Coverage


def coverage(curriculum, read=frappe.get_all):
	"""Per PO / PSO of the curriculum's programme and regulation: total correlation and the courses mapping it, over the
	curriculum's approved matrices that `read` (get_all, or get_list for a report) returns."""
	program, regulation = frappe.db.get_value("Curriculum", curriculum, ["program", "regulation"])
	matrices = read(MATRIX, filters={"curriculum": curriculum, "docstatus": 1}, fields=["name", "course"])
	course_of = {m.name: m.course for m in matrices}
	totals, courses = {}, {}
	for cell in frappe.get_all(
		CELL, {"parenttype": MATRIX, "parent": ["in", list(course_of) or [""]], "correlation": [">", 0]}, ["parent", "outcome", "correlation"]
	):
		totals[cell.outcome] = totals.get(cell.outcome, 0) + cell.correlation
		courses.setdefault(cell.outcome, set()).add(course_of[cell.parent])
	return [
		frappe._dict(
			outcome_type=o.doctype, outcome=o.name, outcome_code=o.code, statement=o.statement,
			total_correlation=totals.get(o.name, 0), courses=len(courses.get(o.name, ())),
			status="Mapped" if totals.get(o.name) else "Not mapped",
		)  # fmt: skip
		for o in programme_outcomes(program, regulation)
	]


def unmapped_codes(curriculum):
	return [row.outcome_code for row in coverage(curriculum) if not row.total_correlation]


# CO tags of CIA questions and question bank items


def validate_co_tags(doc, method=None):
	"""Doc event (CIA Schedule, Question Bank Item, Answer Script Bundle): once the course has Course Outcomes, a CO tag
	set or changed in this save must be one of their codes (in the offering's curriculum for a CIA Schedule, in any
	curriculum otherwise) and is stored normalised. A tag left as it was is not checked, so a legacy tag never blocks
	an unrelated save. The tag is changed by the saving user, so the document's own audit records it (CIA Schedule and
	bundle versions, the bank item's editors)."""
	changed = changed_tag_rows(doc)
	if not changed:
		return
	course, curriculum = tag_scope(doc)
	allowed = co_codes(course, curriculum)
	if not allowed:
		return
	for row in changed:
		row.course_outcome = normalise_code(row.course_outcome)
		if row.course_outcome not in allowed:
			frappe.throw(
				_("{0} is not a course outcome of {1}. Use one of: {2}.").format(
					frappe.bold(row.course_outcome), frappe.bold(course), ", ".join(sorted(allowed, key=code_order))
				)
			)


def changed_tag_rows(doc):
	"""The rows (the document itself for a bank item) whose CO tag is set and new or different from before the save."""
	before = doc.get_doc_before_save()
	if doc.doctype == "Question Bank Item":
		rows, previous = [doc], {doc.name: before.course_outcome} if before else {}
	else:
		rows, previous = doc.get("questions"), {row.name: row.course_outcome for row in before.get("questions")} if before else {}
	return [row for row in rows if row.course_outcome and (row.name not in previous or previous[row.name] != row.course_outcome)]


def tag_scope(doc):
	if doc.doctype == "CIA Schedule":
		offering = frappe.db.get_value("Student Group", doc.course_offering, ["course", "oc_curriculum"], as_dict=True) or {}
		return doc.get("course") or offering.get("course"), offering.get("oc_curriculum")
	return doc.course, None


def co_codes(course, curriculum=None):
	if not course:
		return set()
	filters = {"course": course, **({"curriculum": curriculum} if curriculum else {})}
	return set(frappe.get_all("Course Outcome", filters, pluck="co_code"))


# Prints


def co_po_grid(doc):
	"""Print data of a CO-PO Matrix: the PO / PSO codes, one row per CO with its cells, and the column averages of the
	non-zero correlations (as NBA course files show them)."""
	outcomes = [o.code for o in programme_outcomes(doc.program, doc.regulation)]
	cells = {(row.co_code, row.outcome_code): row.correlation for row in doc.correlations}
	rows = []
	for co in course_outcomes(doc.course, doc.curriculum):
		rows.append(frappe._dict(co, cells=[cells.get((co.co_code, code)) or "" for code in outcomes]))
	averages = []
	for index in range(len(outcomes)):
		values = [row.cells[index] for row in rows if row.cells[index]]
		averages.append(round(sum(values) / len(values), 2) if values else "")
	return frappe._dict(outcomes=outcomes, rows=rows, averages=averages)
