"""M07-05 API scoring: points per activity under the API Score Rule, with annual caps, and the KRA scores.

Pure functions, no database. An item is (activity, date, quantity); a rule row has activity, points per unit, annual cap
(0 = no cap) and KRA. Points are quantity times the rule's points, summed per year and limited to the cap per year;
`year_of(date)` names the year an item falls in. A KRA's completion is its points against the target, limited to 100%, and its
score is out of 5 stars like an HRMS Appraisal Goal.
"""

import frappe
from frappe.utils import flt

STARS = 5


def score_activities(items, rows, year_of):
	"""One result per rule row: quantity, raw_points (before caps), points (after the annual cap)."""
	quantities = {}
	for activity, on_date, quantity in items:
		by_year = quantities.setdefault(activity, {})
		year = year_of(on_date)
		by_year[year] = by_year.get(year, 0) + flt(quantity)
	return [row_result(row, quantities.get(row.activity, {})) for row in rows]


def row_result(row, by_year):
	raw = [flt(quantity) * flt(row.points) for quantity in by_year.values()]
	counted = [min(points, row.annual_cap) if row.annual_cap else points for points in raw]
	return frappe._dict(
		activity=row.activity, kra=row.kra, quantity=sum(by_year.values()), raw_points=sum(raw), points=sum(counted),
		capped=sum(counted) < sum(raw),
	)  # fmt: skip


def kra_scores(results, kras):
	"""Per KRA of the rule (in its order): points, completion % and the star score."""
	scores = []
	for kra in kras:
		points = sum(r.points for r in results if r.kra == kra.kra)
		completion = min(100.0, 100 * points / kra.target_points) if flt(kra.target_points) else 0
		scores.append(
			frappe._dict(
				kra=kra.kra, weightage=kra.weightage, target_points=kra.target_points, points=points, completion=completion,
				score=flt(completion * STARS / 100, 2),
			)
		)  # fmt: skip
	return scores
