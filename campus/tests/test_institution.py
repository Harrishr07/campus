"""M17-01 integration tests: Institution Profile, Module Pack, Shared Service Agreement, Campus Settings."""

import frappe
from frappe.utils import add_days, today

from campus.campus_platform.api import clear_pack_cache, get_institution, pack_enabled, service_provider
from campus.campus_platform.module_packs import SEED_PACKS, seed_module_packs
from campus.campus_platform.pack_visibility import boot_session, hidden_workspaces
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

TRUST = "Campus Test Trust"
DEMO = "Campus Test Demo College"
OTHER = "Campus Test Other College"
USER_DEMO = "campus-pack-demo@example.com"
USER_BOTH = "campus-pack-both@example.com"
WORKSPACE = "Campus Test Pack Workspace"


def make_profile(company, status="Affiliated", effective_from=None, **kwargs):
	return frappe.get_doc(
		{
			"doctype": "Institution Profile",
			"company": company,
			"institution_status": status,
			"status_effective_from": effective_from,
			**kwargs,
		}
	).insert()


def make_agreement(service, members, from_date=None, to_date=None, provider=TRUST):
	return frappe.get_doc(
		{
			"doctype": "Shared Service Agreement",
			"provider_company": provider,
			"service": service,
			"from_date": from_date or add_days(today(), -30),
			"to_date": to_date,
			"members": [{"company": m} for m in members],
		}
	).insert()


def hidden_test_workspaces(user):
	"""The test workspace's verdict only: seeded packs (COE, IQAC) hide their own area workspaces too."""
	return hidden_workspaces(user) & {WORKSPACE}


class TestInstitution(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name, abbr in ((TRUST, "CTT"), (DEMO, "CTD"), (OTHER, "CTO")):
			make_company(name, abbr)
		make_user(USER_DEMO, [DEMO])
		make_user(USER_BOTH, [DEMO, OTHER])
		seed_module_packs()

	def setUp(self):
		frappe.db.savepoint("institution_test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="institution_test")
		clear_pack_cache()  # also the per-request hidden_workspaces answer, which the rollback made stale

	# seed and defaults
	def test_seed_packs_and_allowed_statuses(self):
		for code in SEED_PACKS:
			self.assertTrue(frappe.db.exists("Module Pack", code), code)
		self.assertEqual(len(SEED_PACKS), 11)
		statuses = frappe.get_all("Module Pack Status", filters={"parent": "GOVERNANCE"}, pluck="status")
		self.assertEqual(sorted(statuses), ["Autonomous", "Deemed"])
		# M06-10: the Examinations pack follows Examination Mode (seeded, or added by a patch on an upgraded site)
		statuses = frappe.get_all("Module Pack Status", filters={"parent": "COE"}, pluck="status")
		self.assertEqual(sorted(statuses), ["Affiliated", "Autonomous", "Deemed"])
		statuses = frappe.get_all("Module Pack Status", filters={"parent": "HOSTEL"}, pluck="status")
		self.assertEqual(sorted(statuses), ["Affiliated", "Autonomous", "Deemed"])

	def test_seed_is_idempotent_and_keeps_edits(self):
		frappe.db.set_value("Module Pack", "LABS", "title", "Edited")
		seed_module_packs()
		self.assertEqual(frappe.db.get_value("Module Pack", "LABS", "title"), "Edited")

	def test_certificate_issuer_defaults(self):
		profile = make_profile(DEMO)
		self.assertEqual(profile.degree_awarding_body, "University")
		self.assertEqual(profile.provisional_certificate_issuer, "College")

	def test_campus_settings_defaults(self):
		settings = frappe.get_single("Campus Settings")
		self.assertEqual(settings.default_attendance_threshold, 75)

	# one profile per company
	def test_only_one_profile_per_company(self):
		make_profile(DEMO)
		with self.assertRaises(frappe.DuplicateEntryError):
			make_profile(DEMO)

	def test_get_institution(self):
		make_profile(DEMO, segment="Engineering")
		self.assertEqual(get_institution(DEMO).segment, "Engineering")
		self.assertIsNone(get_institution(OTHER))

	# pack toggling by status
	def test_affiliated_hides_governance_but_keeps_examinations(self):
		make_profile(DEMO, "Affiliated")
		self.assertFalse(pack_enabled(DEMO, "GOVERNANCE"))
		self.assertTrue(pack_enabled(DEMO, "COE"))  # M06-10: CIA and the university exchange
		self.assertTrue(pack_enabled(DEMO, "HOSTEL"))

	def test_switch_to_autonomous_enables_without_data_change(self):
		profile = make_profile(DEMO, "Affiliated")
		self.assertFalse(pack_enabled(DEMO, "GOVERNANCE"))
		profile.institution_status = "Autonomous"
		profile.status_effective_from = today()
		profile.save()
		self.assertTrue(pack_enabled(DEMO, "COE"))
		self.assertTrue(pack_enabled(DEMO, "GOVERNANCE"))

	def test_future_effective_date_keeps_packs_off(self):
		make_profile(DEMO, "Autonomous", add_days(today(), 5))
		self.assertFalse(pack_enabled(DEMO, "GOVERNANCE"))

	def test_no_profile_means_disabled(self):
		self.assertFalse(pack_enabled(OTHER, "HOSTEL"))

	def test_explicit_row_switches_pack_off_for_one_college(self):
		profile = make_profile(DEMO, "Autonomous", packs=[{"pack": "HOSTEL", "enabled": 0}])
		self.assertFalse(pack_enabled(DEMO, "HOSTEL"))
		self.assertTrue(pack_enabled(DEMO, "LIBRARY"))
		profile.packs[0].enabled = 1
		profile.save()
		self.assertTrue(pack_enabled(DEMO, "HOSTEL"))

	def test_pack_disabled_globally(self):
		make_profile(DEMO)
		pack = frappe.get_doc("Module Pack", "LIBRARY")
		pack.enabled = 0
		pack.save()
		self.assertFalse(pack_enabled(DEMO, "LIBRARY"))

	def test_duplicate_pack_rows_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_profile(DEMO, packs=[{"pack": "HOSTEL"}, {"pack": "HOSTEL"}])

	# cache
	def test_pack_enabled_is_cached_and_invalidated_on_save(self):
		profile = make_profile(DEMO, "Affiliated")
		self.assertFalse(pack_enabled(DEMO, "GOVERNANCE"))
		# a write that bypasses hooks must not be seen: the answer comes from the cache
		frappe.db.set_value("Institution Profile", DEMO, "institution_status", "Autonomous")
		self.assertFalse(pack_enabled(DEMO, "GOVERNANCE"))
		profile.reload()
		profile.save()
		self.assertTrue(pack_enabled(DEMO, "GOVERNANCE"))

	def test_cache_invalidated_on_module_pack_save(self):
		make_profile(DEMO, "Affiliated")
		self.assertTrue(pack_enabled(DEMO, "LABS"))
		pack = frappe.get_doc("Module Pack", "LABS")
		pack.enabled = 0
		pack.save()
		self.assertFalse(pack_enabled(DEMO, "LABS"))

	# shared service agreement
	def test_service_provider_returns_trust(self):
		make_agreement("Hostel", [DEMO])
		self.assertEqual(service_provider("Hostel", DEMO), TRUST)

	def test_service_provider_none_without_agreement_or_other_service(self):
		make_agreement("Hostel", [DEMO])
		self.assertIsNone(service_provider("Transport", DEMO))
		self.assertIsNone(service_provider("Hostel", OTHER))

	def test_service_provider_respects_dates(self):
		make_agreement("Library", [DEMO], add_days(today(), -30), add_days(today(), -1))
		self.assertIsNone(service_provider("Library", DEMO))
		make_agreement("Transport", [DEMO], add_days(today(), 1))
		self.assertIsNone(service_provider("Transport", DEMO))

	def test_invoicing_company_defaults_to_provider(self):
		self.assertEqual(make_agreement("Hostel", [DEMO]).invoicing_company, TRUST)

	def test_agreement_overlap_rejected(self):
		make_agreement("Hostel", [DEMO, OTHER])
		with self.assertRaises(frappe.ValidationError):
			make_agreement("Hostel", [OTHER])

	def test_agreement_for_other_service_or_later_dates_allowed(self):
		make_agreement("Hostel", [DEMO], to_date=add_days(today(), 10))
		make_agreement("Transport", [DEMO])
		make_agreement("Hostel", [DEMO], from_date=add_days(today(), 11))

	def test_agreement_bad_dates_and_duplicate_members_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_agreement("Hostel", [DEMO], today(), add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			make_agreement("Hostel", [DEMO, DEMO])

	# navigation visibility
	def make_workspace_pack(self, roles=()):
		if not frappe.db.exists("Workspace", WORKSPACE):
			frappe.get_doc(
				{"doctype": "Workspace", "name": WORKSPACE, "label": WORKSPACE, "title": WORKSPACE,
				 "public": 1, "module": "Campus Platform", "content": "[]"}
			).insert()
		pack = frappe.get_doc("Module Pack", "HOSTEL")
		pack.workspaces = []
		pack.append("workspaces", {"workspace": WORKSPACE})
		pack.roles = []
		for role in roles:
			pack.append("roles", {"role": role})
		pack.save()

	def test_workspace_hidden_when_pack_disabled_for_all_user_companies(self):
		self.make_workspace_pack()
		make_profile(DEMO, "Affiliated", packs=[{"pack": "HOSTEL", "enabled": 0}])
		make_profile(OTHER, "Affiliated")
		self.assertEqual(hidden_test_workspaces(USER_DEMO), {WORKSPACE})
		self.assertEqual(hidden_test_workspaces(USER_BOTH), set())  # enabled for OTHER

	def test_workspace_visible_when_pack_enabled(self):
		self.make_workspace_pack()
		make_profile(DEMO)
		self.assertEqual(hidden_test_workspaces(USER_DEMO), set())

	def test_admin_never_hidden(self):
		self.make_workspace_pack()
		make_profile(DEMO, packs=[{"pack": "HOSTEL", "enabled": 0}])
		self.assertEqual(hidden_test_workspaces("Administrator"), set())

	def test_pack_roles_restrict_visibility(self):
		self.make_workspace_pack(roles=["Auditor"])
		make_profile(DEMO)
		self.assertEqual(hidden_test_workspaces(USER_DEMO), {WORKSPACE})

	def test_boot_session_filters_pages_sidebars_dock_and_icons(self):
		self.make_workspace_pack()
		make_profile(DEMO, packs=[{"pack": "HOSTEL", "enabled": 0}])
		hidden_link = {"type": "Link", "link_type": "Workspace", "link_to": WORKSPACE}
		other = {"type": "Link", "link_type": "Workspace", "link_to": "Other"}
		section = {"type": "Section Break", "label": "Setup"}
		thing = {"type": "Link", "link_type": "DocType", "link_to": "Route Thing"}
		bootinfo = frappe._dict(
			workspaces={"pages": [{"name": WORKSPACE}, {"name": "Other"}], "private_pages": []},
			module_sidebars={
				# the hidden workspace's own sidebar (its Home)
				"Area": {"module": "Campus Platform", "workspaces": [WORKSPACE], "items": [hidden_link, section, other]},
				# the same module's sidebar as Frappe ships it to a user without the workspace role: Home gone
				"Route Only": {"module": "Campus Platform", "workspaces": [], "items": [thing]},
				"Mixed": {"module": "Other Module", "workspaces": ["Other"], "items": [other, hidden_link]},
			},
			entity_module={"Thing": "Area", "Route Thing": "Route Only", "Other Thing": "Mixed"},
			canonical_shell={"DocType": {"Thing": "Area", "Route Thing": "Route Only", "Other Thing": "Mixed"}},
			home_shell="Area",
			dock={"campus": [
				{"link_type": "Workspace", "link_to": WORKSPACE},
				{"link_type": "Sidebar", "link_to": "Area"},
				{"link_type": "Sidebar", "link_to": "Mixed"},
			]},
			app_data=[{"app_name": "campus", "dock": [{"link_type": "Workspace", "link_to": WORKSPACE}, other]}],
			desktop_icons=[
				{"label": "Direct", "link_type": "Workspace Sidebar", "link_to": WORKSPACE},
				{"label": "Mixed", "link_type": "Workspace Sidebar", "link_to": "Other"},
			],
		)
		frappe.set_user(USER_DEMO)
		boot_session(bootinfo)
		self.assertEqual([p["name"] for p in bootinfo.workspaces["pages"]], ["Other"])
		self.assertEqual(list(bootinfo.module_sidebars), ["Mixed"])
		self.assertEqual(bootinfo.module_sidebars["Mixed"]["items"], [other])
		self.assertEqual(bootinfo.entity_module, {"Other Thing": "Mixed"})
		self.assertEqual(bootinfo.canonical_shell, {"DocType": {"Other Thing": "Mixed"}})
		self.assertIsNone(bootinfo.home_shell)
		self.assertEqual(bootinfo.dock["campus"], [{"link_type": "Sidebar", "link_to": "Mixed"}])
		self.assertEqual(bootinfo.app_data[0]["dock"], [other])
		self.assertEqual([i["label"] for i in bootinfo.desktop_icons], ["Mixed"])
