"""M03-03 CO and PO attainment, direct and indirect, per the regulation's Attainment Policy.

CO Attainment Run (one course offering): the policy of the offering's curriculum regulation; per Course Outcome of the
course in that curriculum, the share of students at the student threshold on the CO-tagged CIA questions and on the
CO-tagged ESE (valuation) questions, their levels, the direct level, the course exit survey level and the final level.
Its inputs come from examinations.api.offering_assessment (released, ratified results only) and
iqac.api.indirect_co_scores (closed campaigns, small groups hidden). PO Attainment Run (programme, batch, optionally
one academic year): over the batch's submitted CO runs of its regulation, sum(CO final x correlation) / sum(correlation)
per PO / PSO through each run's approved CO-PO Matrix, then the programme exit survey (iqac.api.campaign_outcome_scores)
at the policy's PO indirect weight. The maths is campus.curriculum.attainment_rules.

Both runs are computed by the bulk runner (one item per run; a failure marks the run Failed with the error) and copy
the policy values they used, so a submitted run never moves when a policy changes, and a regulation's policy reaches
only its own curriculum's offerings and batches. A policy a submitted run used is locked: disable it and create a new
one for the regulation. The CO run's input snapshot (per-student marks) is at permlevel 1, read by System Manager,
COE and Dean Academics only; `questions_used` (no students) is what the print and everyone else see. Who reads and
manages a run: campus.curriculum.attainment_access.

ESE figures are the raw valuation question marks (before moderation, grace and revaluation). A run whose ESE marks
carry no CO tag at all cannot be submitted (tag the bundle's questions); a paper whose question maxima exceed the ESE
maximum (a choice paper) is flagged, and a question a student did not answer counts in neither marks nor maximum.
"""

import json
from collections import Counter

import frappe
from frappe import _
from frappe.utils import now_datetime, strip_html

from campus.campus_platform.company_scope import permitted_companies
from campus.curriculum import attainment_access
from campus.curriculum import attainment_rules as rules
from campus.curriculum.outcomes import CELL, MATRIX, code_order, course_outcomes, matrix_for, normalise_code, programme_outcomes

POLICY, CO_RUN, PO_RUN = "Attainment Policy", "CO Attainment Run", "PO Attainment Run"
CO_RESULT, PO_RESULT = "CO Attainment Result", "PO Attainment Result"
CO_HANDLER = "campus.curriculum.attainment.compute_co_item"
PO_HANDLER = "campus.curriculum.attainment.compute_po_item"
TOOLS = ("cia", "ese")
ESE_BASIS = "raw valuation question marks of the deciding rounds (before moderation, grace and revaluation)"
SAVEPOINT = "attainment_run"


# ---- policy -------------------------------------------------------------------------------


def policy_for(regulation):
	"""The active Attainment Policy of `regulation`; refused when the regulation has none."""
	name = frappe.db.get_value(POLICY, {"regulation": regulation, "disabled": 0})
	if not name:
		frappe.throw(_("Regulation {0} has no Attainment Policy. Create one first.").format(frappe.bold(regulation)))
	return name


def policy_values(policy):
	return rules.Policy(
		policy.direct_weight, policy.indirect_weight, policy.cia_weight, policy.ese_weight, policy.student_threshold,
		tuple(sorted((band.level, band.min_students_percent) for band in policy.level_bands)), policy.target_level,
		policy.survey_scale or 5,
	)  # fmt: skip


def policy_snapshot(policy):
	values = policy_values(policy)
	return {
		"name": policy.name, **{f: policy.get(f) for f in rules.Policy._fields if f != "bands"},
		"bands": [list(band) for band in values.bands], "po_indirect_weight": policy.po_indirect_weight,
		"po_target_level": policy.po_target_level,
	}  # fmt: skip


# ---- scope of a run -----------------------------------------------------------------------


def set_co_scope(doc):
	"""Derive a CO run's course, curriculum, regulation and policy from its offering."""
	group = frappe.db.get_value(
		"Student Group", doc.course_offering,
		["group_based_on", "course", "oc_curriculum", "academic_year", "academic_term", "oc_company"], as_dict=True,
	)  # fmt: skip
	if not group or group.group_based_on != "Course":
		frappe.throw(_("{0} is not a course offering (a Student Group based on Course).").format(frappe.bold(doc.course_offering)))
	if not group.oc_curriculum:
		frappe.throw(_("{0} was not generated from a curriculum, so it has no course outcomes.").format(frappe.bold(doc.course_offering)))
	program, regulation = frappe.db.get_value("Curriculum", group.oc_curriculum, ["program", "regulation"])
	doc.update(
		{
			"course": group.course, "curriculum": group.oc_curriculum, "regulation": regulation, "program": program,
			"academic_year": group.academic_year, "academic_term": group.academic_term,
			"company": group.oc_company or frappe.db.get_value("Program", program, "oc_company"),
			"department": frappe.db.get_value("Course", group.course, "department"), "policy": policy_for(regulation),
		}
	)  # fmt: skip


def set_po_scope(doc):
	from campus.campus_platform.api import resolve_regulation

	doc.company = frappe.db.get_value("Program", doc.program, "oc_company")
	doc.regulation = resolve_regulation(doc.company, doc.program, doc.batch)
	if not doc.regulation:
		frappe.throw(_("No effective regulation of {0} covers batch {1}.").format(frappe.bold(doc.program), frappe.bold(doc.batch)))
	doc.policy = policy_for(doc.regulation)
	if doc.exit_survey:
		check_exit_survey(doc)


EXIT_AUDIENCES = ("Students", "Alumni")


def check_exit_survey(doc):
	"""A programme exit survey is a closed Students / Alumni campaign of the college whose Audience Rule is this
	programme's: a college-wide campaign would mix other programmes' answers into PO1 ... (they share the NBA codes)."""
	campaign = frappe.db.get_value("Feedback Campaign", doc.exit_survey, ["company", "end_date", "audience", "audience_rule"], as_dict=True)
	if not campaign or campaign.company != doc.company:
		frappe.throw(_("{0} is not a feedback campaign of {1}.").format(frappe.bold(doc.exit_survey), frappe.bold(doc.company)))
	rule_program = frappe.db.get_value("Audience Rule", campaign.audience_rule, "program") if campaign.audience_rule else None
	if campaign.audience not in EXIT_AUDIENCES or rule_program != doc.program:
		frappe.throw(
			_("{0} is not an exit survey of programme {1}: it needs a Students or Alumni audience with an Audience Rule of that programme.").format(
				frappe.bold(doc.exit_survey), frappe.bold(doc.program)
			)
		)
	if not campaign.end_date or str(campaign.end_date) >= frappe.utils.today():
		frappe.throw(_("Only a closed campaign counts: {0} is still open.").format(frappe.bold(doc.exit_survey)))


def check_one_live(doc, filters, lock):
	"""Refuse a second draft or submitted run for the same scope; `lock` (doctype, name) serialises the check."""
	frappe.db.get_value(*lock, "name", for_update=True)
	filters = {**filters, "docstatus": ["<", 2]}
	if not doc.is_new():
		filters["name"] = ["!=", doc.name]
	other = frappe.db.get_value(doc.doctype, filters, "name", for_update=True)
	if other:
		frappe.throw(_("{0} already exists for this scope. Cancel or amend it instead.").format(frappe.bold(other)))


# ---- queueing (bulk runner) ---------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def queue_co_run(name):
	"""Compute a draft CO Attainment Run in the background; returns the Bulk Run."""
	frappe.get_doc(CO_RUN, name).check_permission("write")
	return queue_co_runs([name])


def queue_co_runs(names):
	from campus.campus_platform.bulk import run_bulk

	bulk_run = run_bulk("CO Attainment", names, CO_HANDLER, chunk=1)
	for name in names:
		frappe.db.set_value(CO_RUN, name, {"status": "Queued", "bulk_run": bulk_run})
	return bulk_run


@frappe.whitelist(methods=["POST"])
def start_term_runs(company, academic_term):
	"""A draft CO Attainment Run (existing or new) for every offering of the term whose course has an approved CO-PO
	Matrix and whose regulation has a policy, computed in one bulk run; returns the Bulk Run."""
	frappe.has_permission(CO_RUN, "create", throw=True)
	check_company(company)
	names = []
	filters = {"group_based_on": "Course", "academic_term": academic_term, "oc_company": company, "oc_curriculum": ["is", "set"]}
	managed = attainment_access.managed_programs(frappe.session.user)
	if managed is not None:  # an HOD: their department's programmes only
		filters["program"] = ["in", managed or [""]]
	for offering in frappe.get_all("Student Group", filters, ["name", "course", "oc_curriculum"], order_by="name"):
		regulation = frappe.db.get_value("Curriculum", offering.oc_curriculum, "regulation")
		if not matrix_for(offering.course, offering.oc_curriculum) or not frappe.db.exists(POLICY, {"regulation": regulation}):
			continue
		if frappe.db.exists(CO_RUN, {"course_offering": offering.name, "docstatus": 1}):
			continue
		draft = frappe.db.get_value(CO_RUN, {"course_offering": offering.name, "docstatus": 0})
		names.append(draft or frappe.get_doc({"doctype": CO_RUN, "course_offering": offering.name}).insert().name)
	if not names:
		frappe.throw(_("No offering of {0} needs a run: each needs an approved CO-PO Matrix and an Attainment Policy.").format(academic_term))
	return queue_co_runs(names)


@frappe.whitelist(methods=["POST"])
def queue_po_run(name):
	"""Compute a draft PO Attainment Run in the background; returns the Bulk Run."""
	from campus.campus_platform.bulk import run_bulk

	frappe.get_doc(PO_RUN, name).check_permission("write")
	bulk_run = run_bulk("PO Attainment", [name], PO_HANDLER, chunk=1)
	frappe.db.set_value(PO_RUN, name, {"status": "Queued", "bulk_run": bulk_run})
	return bulk_run


def compute_co_item(name, run=None):
	"""Bulk handler: compute one CO Attainment Run (DB only, no commit)."""
	compute_or_fail(CO_RUN, name, compute_co_run)


def compute_po_item(name, run=None):
	"""Bulk handler: compute one PO Attainment Run (DB only, no commit)."""
	compute_or_fail(PO_RUN, name, compute_po_run)


def compute_or_fail(doctype, name, compute):
	"""Compute the run; on a refusal or error its writes are undone and the run is left Failed with the message, never
	stuck at Queued. A deadlock is raised for the bulk runner to handle."""
	frappe.db.savepoint(SAVEPOINT)
	try:
		compute(name)
	except frappe.QueryDeadlockError:
		raise
	except Exception as e:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_messages()
		frappe.db.set_value(doctype, name, {"status": "Failed", "error": strip_html(str(e))[:1000] or _("Computation failed.")})


def draft(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("{0} is submitted: amend it to compute again.").format(frappe.bold(name)))
	return doc


# ---- CO run -------------------------------------------------------------------------------


def compute_co_run(name):
	from campus.examinations.api import offering_assessment
	from campus.iqac.api import indirect_co_scores

	doc = draft(CO_RUN, name)
	policy = frappe.get_doc(POLICY, doc.policy)
	values = policy_values(policy)
	cos = course_outcomes(doc.course, doc.curriculum)
	if not cos:
		frappe.throw(_("Define the course outcomes of {0} in {1} first.").format(frappe.bold(doc.course), frappe.bold(doc.curriculum)))
	data = offering_assessment(doc.course_offering)
	survey = {normalise_code(code): score for code, score in indirect_co_scores(doc.course_offering).items()}
	doc.results, snapshot = [], {}
	for co in cos:
		tools = {tool: tool_inputs([r for r in data[tool] if normalise_code(r["course_outcome"]) == co.co_code], values.student_threshold) for tool in TOOLS}
		score = survey.get(co.co_code)
		average = score["average"] if score and not score["suppressed"] else None
		result = rules.co_result(tools["cia"].attainment, tools["ese"].attainment, average, values)
		doc.append("results", {**result_fields(result), "course_outcome": co.name, "co_code": co.co_code,
			"indirect_responses": score["responses"] if score else None, "indirect_suppressed": score["suppressed"] if score else 0})  # fmt: skip
		snapshot[co.co_code] = {**{tool: tools[tool].snapshot for tool in TOOLS}, "indirect": score}
	batches = batch_counts(data.students)
	shared = {"exam_sessions": data.exam_sessions, "batches": batches, "ese_basis": ESE_BASIS, "policy": policy_snapshot(policy)}
	doc.update({f: policy.get(f) for f in ("direct_weight", "indirect_weight", "cia_weight", "ese_weight", "student_threshold", "target_level", "survey_scale")})
	doc.update(
		{
			"students": len(data.students), "batch": majority_batch(batches), "matrix": matrix_for(doc.course, doc.curriculum),
			"ese_untagged": int(bool(data.ese) and not any(r["course_outcome"] for r in data.ese)),
			"ese_choice_paper": int(bool(data.choice_paper)), "status": "Computed", "computed_on": now_datetime(), "error": None,
			"input_snapshot": json.dumps({**shared, "students": data.students, "cos": snapshot}),
			"questions_used": json.dumps({**shared, "cos": {code: {tool: [q["question"] for q in entry[tool]["questions"]] for tool in TOOLS} for code, entry in snapshot.items()}}),
		}
	)  # fmt: skip
	doc.save(ignore_permissions=True)  # write permission checked in draft(); the snapshot is at permlevel 1
	return doc


def tool_inputs(rows, threshold):
	"""One CO in one tool: (students, attained, percent) and its snapshot (questions; per student marks, maximum, attains)."""
	questions = {}
	for row in rows:
		questions.setdefault(row["question"], row["max_marks"])
	scores = rules.student_scores(rows)
	return frappe._dict(
		attainment=rules.tool_attainment(scores, threshold),
		snapshot={
			"questions": [{"question": q, "max_marks": m} for q, m in questions.items()],
			"students": {s: [marks, maximum, int(rules.attains((marks, maximum), threshold))] for s, (marks, maximum) in sorted(scores.items())},
		},
	)  # fmt: skip


def result_fields(result):
	fields = {k: v for k, v in result.items() if k not in ("notes", "gap")}
	return {**fields, "notes": "\n".join(_(note) for note in result.notes) or None}


def batch_counts(students):
	"""{batch: students} of the assessed students (recorded in the snapshot, so the run's batch is auditable)."""
	batches = Counter(frappe.get_all("Student", {"name": ["in", students or [""]]}, pluck="oc_batch"))
	batches.pop(None, None)
	return dict(sorted(batches.items()))


def majority_batch(batches):
	"""The batch most of the assessed students share (ties: the earliest name)."""
	return max(sorted(batches), key=lambda b: batches[b]) if batches else None


# ---- PO run -------------------------------------------------------------------------------


def compute_po_run(name):
	from campus.iqac.api import campaign_outcome_scores

	doc = draft(PO_RUN, name)
	policy = frappe.get_doc(POLICY, doc.policy)
	runs, cells = co_cells(doc)
	survey = {normalise_code(c): s for c, s in campaign_outcome_scores(doc.exit_survey).items()} if doc.exit_survey else {}
	values = policy_values(policy)
	top = rules.top_level(values.bands)
	doc.results, snapshot_cells = [], {}
	for outcome in programme_outcomes(doc.program, doc.regulation):
		mapped = [cell for cell in cells.get(outcome.name, []) if cell.final is not None]
		score = survey.get(outcome.code)
		average = score["average"] if score and not score["suppressed"] else None
		direct = rules.po_direct([(c.final, c.correlation) for c in mapped])
		result = rules.po_result(direct, average, values.survey_scale, top, policy.po_indirect_weight, policy.po_target_level)
		doc.append("results", {**result_fields(result), "outcome_type": outcome.doctype, "outcome": outcome.name, "outcome_code": outcome.code,
			"courses": len({c.course for c in mapped}), "total_correlation": sum(c.correlation for c in mapped),
			"indirect_responses": score["responses"] if score else None, "indirect_suppressed": score["suppressed"] if score else 0})  # fmt: skip
		snapshot_cells[outcome.code] = [[c.co_code, c.final, c.correlation, c.course, c.sections] for c in mapped]
	without_matrix = [r.name for r in runs if not r.matrix]
	doc.update(
		{
			"po_indirect_weight": policy.po_indirect_weight, "po_target_level": policy.po_target_level, "survey_scale": values.survey_scale,
			"co_runs": len(runs), "status": "Computed", "computed_on": now_datetime(), "error": None,
			"warnings": _("Left out, no approved CO-PO Matrix: {0}").format(", ".join(without_matrix)) if without_matrix else None,
			"input_snapshot": json.dumps(
				{"co_runs": runs, "without_matrix": without_matrix, "cells": snapshot_cells, "exit_survey": survey, "policy": policy_snapshot(policy)},
				default=str,
			),
		}
	)  # fmt: skip
	doc.save(ignore_permissions=True)  # write permission checked in draft()
	return doc


def co_cells(doc):
	"""The batch's submitted CO runs of the run's regulation, and {outcome: [cells]} where a cell is a CO of a course
	with its final level, the correlation in the course's CO-PO Matrix and its sections [[run, final, students]]. The
	sections of a course (its runs with the same matrix) are combined first into one student-weighted final per CO, so a
	course weighs once whatever its number of sections."""
	filters = {"docstatus": 1, "program": doc.program, "batch": doc.batch, "regulation": doc.regulation}
	if doc.academic_year:
		filters["academic_year"] = doc.academic_year
	runs = frappe.get_all(CO_RUN, filters, ["name", "course", "course_offering", "academic_year", "matrix", "students"], order_by="name")
	finals = {
		(r.parent, r.course_outcome): r
		for r in frappe.get_all(CO_RESULT, {"parenttype": CO_RUN, "parent": ["in", [r.name for r in runs] or [""]]}, ["parent", "course_outcome", "co_code", "final_level", "assessed"])
	}  # fmt: skip
	matrix_cells = {}
	for cell in frappe.get_all(
		CELL, {"parenttype": MATRIX, "parent": ["in", [r.matrix for r in runs if r.matrix] or [""]], "correlation": [">", 0]},
		["parent", "course_outcome", "outcome", "correlation"],
	):  # fmt: skip
		matrix_cells.setdefault(cell.parent, []).append(cell)
	sections = {}
	for run in runs:
		if run.matrix:
			sections.setdefault((run.course, run.matrix), []).append(run)
	cells = {}
	for (course, matrix), course_runs in sections.items():
		for cell in matrix_cells.get(matrix, []):
			per_section = []
			for run in course_runs:
				final = finals.get((run.name, cell.course_outcome))
				if final and final.assessed:
					per_section.append([run.name, final.final_level, run.students])
			if per_section:
				cells.setdefault(cell.outcome, []).append(
					frappe._dict(
						co_code=finals[(per_section[0][0], cell.course_outcome)].co_code, correlation=cell.correlation, course=course,
						final=rules.combine_sections([(f, n) for _run, f, n in per_section]), sections=per_section,
					)
				)
	return runs, cells


# ---- reports and print --------------------------------------------------------------------


def check_company(company):
	permitted = permitted_companies(frappe.session.user)
	if not company or (permitted is not None and company not in permitted):
		frappe.throw(_("Choose a college you are permitted for."), frappe.PermissionError)


def offering_instructors(offerings):
	"""{offering: [instructor names]}."""
	instructors = {}
	for row in frappe.get_all(
		"Student Group Instructor", {"parenttype": "Student Group", "parent": ["in", list(offerings) or [""]]},
		["parent", "instructor", "instructor_name"], order_by="idx",
	):  # fmt: skip
		instructors.setdefault(row.parent, []).append(row.instructor_name or row.instructor)
	return instructors


def course_attainment_sheet(doc):
	"""Print data of the NBA course file attainment sheet: the faculty, the questions per CO and tool, and the bands,
	from `questions_used` (no student data)."""
	snapshot = frappe.parse_json(doc.questions_used or "{}") or {}
	cos = snapshot.get("cos") or {}
	questions = {code: {tool: ", ".join(cos[code].get(tool) or []) or "-" for tool in TOOLS} for code in sorted(cos, key=code_order)}
	return frappe._dict(
		instructors=", ".join(offering_instructors([doc.course_offering]).get(doc.course_offering, [])),
		questions=questions, bands=(snapshot.get("policy") or {}).get("bands", []), sessions=", ".join(snapshot.get("exam_sessions") or []),
	)  # fmt: skip
