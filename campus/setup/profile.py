"""PR-02 Pilot profile: load a college profile file from campus/setup/profiles and refuse an inconsistent one.

A profile is plain data (companies, calendar, programmes, regulation, seats, fees, policies, users). Adding a
second college is a second JSON file; no code changes. `profile_errors` checks the file against itself (every
programme, department, quota, category and company a section names is defined by the profile) so a typo is
refused before anything is written.
"""

import json
import re
from pathlib import Path

import frappe
from frappe import _

PROFILE_DIR = Path(__file__).parent / "profiles"
NAME = re.compile(r"^[a-z0-9_-]+$")
COMPANY_TOKENS = ("college", "trust")


def load_profile(profile):
	"""The validated profile dict of a profile name (file name without .json), or `profile` itself when it is a dict."""
	if not isinstance(profile, dict):
		if not (isinstance(profile, str) and NAME.match(profile)):
			frappe.throw(_("Invalid profile name {0}.").format(frappe.as_json(profile)))
		path = PROFILE_DIR / f"{profile}.json"
		if not path.exists():
			frappe.throw(_("Profile {0} does not exist in campus/setup/profiles.").format(profile))
		profile = json.loads(path.read_text())
	errors = profile_errors(profile)
	if errors:
		frappe.throw("<br>".join(errors), title=_("Invalid pilot profile"))
	return profile


def profile_errors(profile):
	"""Every inconsistency of `profile` with itself, as a list of messages (empty when it is sound)."""
	errors = []
	college = profile.get("college") or {}
	if not (college.get("name") and college.get("abbr")):
		errors.append(_("The profile needs a college company with a name and an abbreviation."))
	trust = profile.get("trust")
	if trust is not None and not (trust.get("name") and trust.get("abbr")):
		errors.append(_("The trust needs a name and an abbreviation."))
	departments = set(profile.get("departments", []))
	programmes = {p.get("name"): p for p in profile.get("programmes", [])}
	if not programmes:
		errors.append(_("The profile lists no programmes."))
	for name, programme in programmes.items():
		if programme.get("department") not in departments:
			errors.append(_("Programme {0} names an unknown department {1}.").format(name, programme.get("department")))
	errors += regulation_errors(profile, programmes)
	errors += seat_errors(profile, programmes)
	errors += fee_errors(profile, programmes)
	errors += user_errors(profile, departments)
	errors += [_("The profile needs {0}.").format(key) for key in ("user_domain", "test_password", "people_defaults") if not profile.get(key)]
	if profile.get("shared_services") and not trust:
		errors.append(_("Shared services need a trust company to provide them."))
	return errors


def regulation_errors(profile, programmes):
	regulation = profile.get("regulation")
	if not regulation:
		return []
	from campus.curriculum.rule_seed import RULES
	from campus.examinations.seed import GRADES

	errors = []
	seeded = [code for code in RULES if code in GRADES]
	if regulation.get("code") not in seeded:
		errors.append(_("Regulation {0} has no seeded rules; use one of {1}.").format(regulation.get("code"), ", ".join(seeded)))
	errors += [_("Regulation {0} names an unknown programme {1}.").format(regulation.get("code"), p) for p in regulation.get("programmes", []) if p not in programmes]
	return errors


def seat_errors(profile, programmes):
	seats = profile.get("seats")
	if not seats:
		return []
	quotas = {q.get("code") for q in seats.get("quotas", [])}
	categories = {c.get("category") for c in seats.get("categories", [])}
	errors = []
	if sum(q.get("share_pct", 0) for q in seats.get("quotas", [])) != 100:
		errors.append(_("Quota shares must add up to 100."))
	if seats.get("academic_year") not in {y.get("name") for y in profile.get("academic_years", [])}:
		errors.append(_("Seats name an unknown academic year {0}.").format(seats.get("academic_year")))
	for quota in quotas - set(seats.get("split", {})):
		errors.append(_("Quota {0} has no category split.").format(quota))
	for quota, split in seats.get("split", {}).items():
		if quota not in quotas:
			errors.append(_("Seat split names an unknown quota {0}.").format(quota))
		elif sum(split.values()) <= 0:
			errors.append(_("Category split of {0} is empty.").format(quota))
		errors += [_("Seat split of {0} names an unknown category {1}.").format(quota, c) for c in split if c not in categories]
	for name, programme in programmes.items():
		intake = programme.get("intake")
		if not isinstance(intake, int) or intake <= 0:
			errors.append(_("Intake of {0} is not a positive whole number.").format(name))
	return errors


def fee_errors(profile, programmes):
	fees = profile.get("fees")
	if not fees:
		return []
	quotas = {q.get("code") for q in profile.get("seats", {}).get("quotas", [])}
	errors = [_("Fees name an unknown programme {0}.").format(p) for p in fees.get("programmes", []) if p not in programmes]
	errors += [_("Fees name an unknown quota {0}.").format(q) for q in fees.get("components", {}) if q != "default" and q not in quotas]
	if "default" not in fees.get("components", {}):
		errors.append(_("Fees need a default component list."))
	years = {y.get("name") for y in profile.get("academic_years", [])}
	if fees.get("academic_year") not in years:
		errors.append(_("Fees name an unknown academic year {0}.").format(fees.get("academic_year")))
	return errors


def user_errors(profile, departments):
	errors = []
	users = profile.get("users", [])
	keys = [u.get("key") for u in users]
	errors += [_("User key {0} is used twice.").format(k) for k in set(keys) if keys.count(k) > 1]
	group = profile.get("class_group")
	programmes = {p.get("name") for p in profile.get("programmes", [])}
	if group and group.get("programme") not in programmes:
		errors.append(_("The class group names an unknown programme {0}.").format(group.get("programme")))
	profiles = {m.get("name") for m in profile.get("module_profiles", [])}
	for user in users:
		label = user.get("key")
		if user.get("module_profile") and user["module_profile"] not in profiles:
			errors.append(_("User {0} names unknown module profile {1}.").format(label, user["module_profile"]))
		if not (label and user.get("name") and user.get("roles")):
			errors.append(_("Every user needs a key, a name and roles ({0}).").format(label))
			continue
		errors += [_("User {0} is scoped to unknown company {1}.").format(label, c) for c in user.get("companies", []) if c not in COMPANY_TOKENS]
		if "trust" in user.get("companies", []) and not profile.get("trust"):
			errors.append(_("User {0} is scoped to the trust, which the profile does not define.").format(label))
		if user.get("department") and user["department"] not in departments:
			errors.append(_("User {0} is in unknown department {1}.").format(label, user["department"]))
		errors += position_errors(user, group, departments)
	by_key = {u.get("key"): u for u in users}
	for field, key in (profile.get("college") or {}).get("leaders", {}).items():
		if not by_key.get(key, {}).get("employee"):
			errors.append(_("Institution leader {0} names user {1}, who has no employee record.").format(field, key))
	return errors


def position_errors(user, group, departments):
	position = user.get("position")
	if not position:
		return []
	errors = []
	if position.get("scope") not in ("college", "department", "group"):
		errors.append(_("User {0} has an unknown position scope {1}.").format(user.get("key"), position.get("scope")))
	if position.get("scope") == "group" and not group:
		errors.append(_("User {0} holds a group position but the profile has no class group.").format(user.get("key")))
	if position.get("scope") == "department" and position.get("department") not in departments:
		errors.append(_("User {0} holds a position in unknown department {1}.").format(user.get("key"), position.get("department")))
	if not user.get("employee"):
		errors.append(_("User {0} holds a position and needs an employee record.").format(user.get("key")))
	return errors
