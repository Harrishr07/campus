"""PR-02 Pilot admission set-up: student categories, admission quotas, the seat matrix of each programme (its intake
split by quota and category) and the admission settings. Seat counts are the profile's; a matrix that exists is
brought to the profile's sanctioned numbers (allotted and filled counts are never touched)."""

import frappe

from campus.setup.records import upsert


def ensure_admission(profile, college, out):
	seats = profile.get("seats")
	if not seats:
		return
	for category in seats["categories"]:
		upsert(out, "Student Category", {"category": category["category"]}, {"oc_is_reserved": int(category.get("reserved", 0))})
	for quota in seats["quotas"]:
		upsert(out, "Admission Quota", {"code": quota["code"]}, {"title": quota["title"]})
	year = seats["academic_year"]
	for programme in profile["programmes"]:
		ensure_seat_matrix(out, college, programme["name"], year, split_intake(programme["intake"], seats))
	ensure_admission_settings(profile, out)


def split_intake(intake, seats):
	"""{(quota, category): seats}: the intake divided by the quota shares, then each quota's seats by category share,
	by largest remainder so the parts always add up to the intake."""
	quota_seats = largest_remainder(intake, {q["code"]: q["share_pct"] for q in seats["quotas"]})
	split = {}
	for quota, count in quota_seats.items():
		for category, number in largest_remainder(count, seats["split"].get(quota, {})).items():
			split[(quota, category)] = number
	return split


def largest_remainder(total, shares):
	"""Whole-number parts of `total` in proportion to `shares`, adding up to `total`."""
	weight = sum(shares.values())
	if not weight:
		return dict.fromkeys(shares, 0)
	exact = {key: total * share / weight for key, share in shares.items()}
	parts = {key: int(value) for key, value in exact.items()}
	by_remainder = sorted(exact, key=lambda key: (exact[key] - parts[key], shares[key]), reverse=True)
	for key in by_remainder[: total - sum(parts.values())]:
		parts[key] += 1
	return parts


def ensure_seat_matrix(out, college, programme, year, split):
	key = {"company": college, "program": programme, "academic_year": year}
	name = frappe.db.exists("Seat Matrix", key)
	rows = [(quota, category, seats) for (quota, category), seats in split.items() if seats]
	if not name:
		frappe.get_doc(
			{"doctype": "Seat Matrix", **key, "rows": [{"quota": q, "category": c, "sanctioned": n} for q, c, n in rows]}
		).insert(ignore_permissions=True)
		out.created["Seat Matrix"] += 1
		return
	matrix = frappe.get_doc("Seat Matrix", name)
	existing = {(row.quota, row.category): row for row in matrix.rows}
	changed = False
	for (quota, category), seats in split.items():
		row = existing.get((quota, category))
		if row is None and seats:
			matrix.append("rows", {"quota": quota, "category": category, "sanctioned": seats})
			changed = True
		elif row is not None and row.sanctioned != seats:
			row.sanctioned, changed = seats, True
	if changed:
		matrix.save(ignore_permissions=True)
		out.updated["Seat Matrix"] += 1


def ensure_admission_settings(profile, out):
	"""The active admission year and the register number pattern, only where the college has set none."""
	settings = profile.get("admission")
	if not settings:
		return
	doc = frappe.get_doc("Admission Settings")
	changed = False
	for field, value in (("active_admission_year", settings.get("active_year")), ("register_no_pattern", settings.get("register_no_pattern"))):
		if value and not doc.get(field):
			doc.set(field, value)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)
		out.updated["Admission Settings"] += 1
