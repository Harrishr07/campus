"""M05-15 Completion rules (pure, no database): a student's credit completion against the curriculum, the degree
authority's document cover and the alumni date.

A course of the curriculum is cleared by a pass in a published result or by a submitted Credit Recognition
(equivalence, transfer, waiver, external credit); a course both passed and recognised counts once, at the passed
credits, and recognised credits never exceed the curriculum's credits for the course. Each category's cleared
credits are checked against its minimum (the curriculum's Category Credit Requirement), the total of the
categories that count toward credits against the regulation's degree total (0: not checked), and every mandatory
(non-elective) course must be cleared. Courses outside the curriculum earn nothing. Honours / Minor rows are shown
for a student registered for them and never block the degree: without the credits it is awarded without the
variant (graduation_rules.specialisation).
"""

import hashlib
import json
from datetime import timedelta

from frappe.utils import flt

COMPLETE, INCOMPLETE = "Complete", "Incomplete"
MET, SHORT, NOT_REQUIRED = "Met", "Short", "Not Required"
TOTAL = "Total"
SUPERSEDED = "Superseded"


def evaluate(curriculum_rows, minimums, counting, total_required, passed, recognised, specialisations):
	"""{result, categories: [{category, required, earned, status}], missing_courses} of one student.

	`curriculum_rows`: dicts with course, category, credits, is_elective. `minimums`: {category: min credits}.
	`counting`: {category: counts toward credits}. `passed` / `recognised`: {course: credits}. `specialisations`:
	(label, required, earned) rows shown for information."""
	earned, missing = {}, []
	for row in curriculum_rows:
		cleared = cleared_credits(row, passed, recognised)
		if cleared is None and not row["is_elective"]:
			missing.append(row["course"])
		earned[row["category"]] = flt(earned.get(row["category"], 0) + (cleared or 0), 2)
	categories = [
		requirement(category, minimums.get(category, 0), earned.get(category, 0))
		for category in category_order(curriculum_rows, minimums)
	]
	if total_required:
		total = flt(sum(credits for category, credits in earned.items() if counting.get(category)), 2)
		categories.append(requirement(TOTAL, total_required, total))
	categories += [
		{"category": label, "required": flt(required), "earned": flt(got), "status": NOT_REQUIRED}
		for label, required, got in specialisations
	]
	complete = bool(curriculum_rows) and not missing and all(r["status"] != SHORT for r in categories)
	return {
		"result": COMPLETE if complete else INCOMPLETE,
		"categories": categories,
		"missing_courses": sorted(missing),
	}


def cleared_credits(row, passed, recognised):
	"""Credits the curriculum `row` earns: passed credits, else recognised ones capped at the row's; None when not cleared."""
	course = row["course"]
	if course in passed:
		return flt(passed[course])
	if course in recognised:
		return min(flt(recognised[course]), flt(row["credits"]))
	return None


def requirement(category, required, earned):
	return {
		"category": category,
		"required": flt(required),
		"earned": flt(earned),
		"status": SHORT if flt(earned) < flt(required) else MET,
	}


def category_order(curriculum_rows, minimums):
	"""Categories of the curriculum in order of first appearance, then the minimums' categories it does not use."""
	seen = list(dict.fromkeys(row["category"] for row in curriculum_rows))
	return seen + [category for category in minimums if category not in seen]


def fingerprint(curriculum, outcome):
	"""A digest of the curriculum and the outcome: an unchanged one means a re-run has nothing new to record."""
	payload = json.dumps([curriculum, outcome], sort_keys=True, default=str)
	return hashlib.sha256(payload.encode()).hexdigest()


def covering_document(documents, on_date):
	"""The first of `documents` (dicts with valid_from, valid_to, status) in force on `on_date`, or None. A superseded
	document never covers: its successor does."""
	for document in documents:
		if document["status"] != SUPERSEDED and document["valid_from"] <= on_date <= document["valid_to"]:
			return document
	return None


def alumni_date(graduated_on, after_days):
	return graduated_on + timedelta(days=int(after_days or 0))


def alumni_due(graduated_on, after_days, on_date):
	return alumni_date(graduated_on, after_days) <= on_date
