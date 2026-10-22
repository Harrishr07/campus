"""M17-01 desk navigation: every area has a Workspace, a Workspace Sidebar and a Desktop Icon that agree, every
link resolves, every campus DocType has exactly one home area, and icons follow the user's roles."""

import glob
import json
import os
from collections import Counter

import frappe
from frappe.boot import get_bootinfo

from campus.campus_platform.api import clear_pack_cache
from campus.campus_platform.pack_visibility import hidden_workspaces
from campus.setup.permission_matrix import TEST_ONLY_DOCTYPES
from campus.tests.factories import make_company, make_user
from campus.tests.utils import CampusTestCase

APP_ICON = "OneBook Campus"
COLLEGE = "Campus Nav Test College"  # autonomous: the COE pack (Examinations) is open to it
RESEARCH_USER = "campus-nav-research@example.com"
SECTIONS = ["Masters", "Transactions", "Reports", "Settings"]
USERS = {
	"accounts": ("campus-nav-accounts@example.com", ["Accounts User"]),
	"coe": ("campus-nav-coe@example.com", ["COE"]),
	"officer": ("campus-nav-officer@example.com", ["Admission Officer"]),
}


def campus_sidebars():
	return [frappe.get_doc("Workspace Sidebar", n) for n in frappe.get_all("Workspace Sidebar", {"app": "campus"}, pluck="name")]


def campus_workspaces():
	return [frappe.get_doc("Workspace", n) for n in frappe.get_all("Workspace", {"app": "campus", "public": 1}, pluck="name")]


def link_items(sidebar):
	return [i for i in sidebar.items if i.type == "Link"]


def campus_modules():
	return frappe.get_all("Module Def", {"app_name": "campus"}, pluck="name")


class TestNavigation(CampusTestCase):
	def test_areas_are_complete_and_agree(self):
		sidebars = {s.name for s in campus_sidebars()}
		icon_files = glob.glob(frappe.get_app_path("campus", "desktop_icon", "*.json"))
		self.assertEqual(len(sidebars), len(icon_files) - 1)  # every icon file but the app tile is an area
		self.assertGreaterEqual(len(sidebars), 12)
		self.assertEqual(sidebars, {w.name for w in campus_workspaces()})
		self.assertEqual(sidebars, set(frappe.get_all("Desktop Icon", {"app": "campus", "icon_type": "Link"}, pluck="name")))
		self.assertTrue(frappe.db.exists("Desktop Icon", {"name": APP_ICON, "icon_type": "App", "app": "campus"}))
		for name in sidebars:
			icon = frappe.get_doc("Desktop Icon", name)
			self.assertEqual((icon.parent_icon, icon.link_type, icon.link_to), (APP_ICON, "Workspace Sidebar", name))
			self.assertTrue(icon.standard)

	def test_no_area_is_open_to_every_desk_user(self):
		for name in frappe.get_all("Desktop Icon", {"app": "campus", "icon_type": "Link"}, pluck="name"):
			self.assertTrue(frappe.get_doc("Desktop Icon", name).roles, f"icon {name} has no roles")
		for workspace in campus_workspaces():
			self.assertTrue(workspace.roles, f"workspace {workspace.name} has no roles")
			icon = frappe.get_doc("Desktop Icon", workspace.name)
			self.assertEqual({r.role for r in icon.roles}, {r.role for r in workspace.roles}, workspace.name)

	def test_students_and_guardians_have_no_desk_access(self):
		for role in ("Student", "Guardian"):
			self.assertEqual(frappe.db.get_value("Role", role, "desk_access"), 0, role)

	def test_sidebar_sections_follow_the_standard_order(self):
		for sidebar in campus_sidebars():
			self.assertEqual((sidebar.items[0].type, sidebar.items[0].link_type, sidebar.items[0].link_to),
				("Link", "Workspace", sidebar.name), sidebar.name)
			sections = [i.label for i in sidebar.items if i.type == "Section Break"]
			self.assertEqual(sections, [s for s in SECTIONS if s in sections], sidebar.name)

	def test_every_link_target_exists(self):
		for sidebar in campus_sidebars():
			for item in link_items(sidebar):
				if item.link_type == "URL":
					self.assertTrue(item.url.startswith("/"), item.label)
				else:
					self.assertTrue(frappe.db.exists(item.link_type, item.link_to), f"{sidebar.name}: {item.link_type} {item.link_to}")
		for workspace in campus_workspaces():
			for link in workspace.links:
				if link.type == "Link":
					self.assertTrue(frappe.db.exists(link.link_type, link.link_to), f"{workspace.name}: {link.link_to}")
			for shortcut in workspace.shortcuts:
				if shortcut.type != "URL":
					self.assertTrue(frappe.db.exists(shortcut.type, shortcut.link_to), f"{workspace.name}: {shortcut.link_to}")

	def test_every_campus_doctype_has_exactly_one_home_area(self):
		homes = Counter(  # a filtered link is a saved view of its DocType, not a second home
			i.link_to for s in campus_sidebars() for i in link_items(s) if i.link_type == "DocType" and not i.filters
		)
		doctypes = frappe.get_all(
			"DocType", {"module": ["in", campus_modules()], "istable": 0, "custom": 0, "name": ["not in", list(TEST_ONLY_DOCTYPES)]}, pluck="name"
		)
		self.assertTrue(doctypes)
		self.assertEqual({d: homes.get(d, 0) for d in doctypes if homes.get(d, 0) != 1}, {})

	def test_every_campus_report_has_exactly_one_home_area(self):
		homes = Counter(i.link_to for s in campus_sidebars() for i in link_items(s) if i.link_type == "Report")
		reports = frappe.get_all("Report", {"module": ["in", campus_modules()]}, pluck="name")
		self.assertTrue(reports)
		self.assertEqual({r: homes.get(r, 0) for r in reports if homes.get(r, 0) != 1}, {})

	def test_workspace_page_mirrors_the_sidebar(self):
		workspaces = {w.name: w for w in campus_workspaces()}
		for sidebar in campus_sidebars():
			workspace = workspaces[sidebar.name]
			in_sidebar = {(i.link_type, i.link_to) for i in link_items(sidebar) if i.link_type in ("DocType", "Report")}
			on_page = {(l.link_type, l.link_to) for l in workspace.links if l.type == "Link"}
			self.assertEqual(on_page, in_sidebar, sidebar.name)
			self.assertEqual([l.label for l in workspace.links if l.type == "Card Break"],
				[i.label for i in sidebar.items if i.type == "Section Break"], sidebar.name)
			shortcuts = [s.label for s in workspace.shortcuts]
			self.assertTrue(4 <= len(shortcuts) <= 6, sidebar.name)
			self.assertEqual(
				[b["data"]["shortcut_name"] for b in json.loads(workspace.content) if b["type"] == "shortcut"], shortcuts
			)

	def test_module_packs_hide_their_area(self):
		for code, area in (
			("COE", "Examinations"), ("GOVERNANCE", "Academic Governance"), ("IQAC", "IQAC"), ("RESEARCH", "Research")
		):  # fmt: skip
			self.assertIn(area, frappe.get_all("Module Pack Workspace", {"parent": code}, pluck="workspace"), code)

	def test_research_area_hidden_when_its_pack_is_off(self):
		make_user(RESEARCH_USER, [COLLEGE])  # sees only this college, so the college's switch decides
		self.assertNotIn("Research", hidden_workspaces(RESEARCH_USER))
		profile = frappe.get_doc("Institution Profile", COLLEGE)
		profile.append("packs", {"pack": "RESEARCH", "enabled": 0})
		profile.save()
		clear_pack_cache()
		self.assertIn("Research", hidden_workspaces(RESEARCH_USER))

	# role mapping
	def desk_areas(self, key):
		email = USERS[key][0]
		frappe.set_user(email)
		frappe.cache.hdel("desktop_icons", email)
		frappe.cache.hdel("bootinfo", email)
		bootinfo = get_bootinfo()
		return {i["label"] for i in bootinfo.desktop_icons if i.get("app") == "campus"}, bootinfo

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_company(COLLEGE, "CNTC")  # a pack shows only to users of an institution it is enabled for
		if not frappe.db.exists("Institution Profile", COLLEGE):
			frappe.get_doc({"doctype": "Institution Profile", "company": COLLEGE, "institution_status": "Autonomous"}).insert()

	def setUp(self):
		frappe.db.savepoint("navigation_test")
		clear_pack_cache()
		self.addCleanup(clear_pack_cache)
		for email, roles in USERS.values():
			if not frappe.db.exists("User", email):
				frappe.get_doc({"doctype": "User", "email": email, "first_name": "nav", "send_welcome_email": 0,
					"roles": [{"role": r} for r in roles]}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="navigation_test")

	def test_accounts_user_sees_finance_but_not_examinations(self):
		areas, bootinfo = self.desk_areas("accounts")
		self.assertIn("Fees and Finance", areas)
		self.assertIn(APP_ICON, areas)
		self.assertTrue({"Examinations", "Admissions", "IQAC", "Administration"}.isdisjoint(areas), areas)
		self.assertNotIn("Examinations", [p["name"] for p in bootinfo.workspaces["pages"]])

	def test_coe_sees_examinations_only_of_the_campus_areas_it_is_for(self):
		areas, bootinfo = self.desk_areas("coe")
		self.assertIn("Examinations", areas)
		self.assertTrue({"Fees and Finance", "Admissions", "IQAC"}.isdisjoint(areas), areas)
		sidebar = bootinfo.workspace_sidebar_item["examinations"]
		self.assertIn("Student Result", [i["link_to"] for i in sidebar["items"]])

	def test_admission_officer_sees_admissions(self):
		areas, _ = self.desk_areas("officer")
		self.assertIn("Admissions", areas)
		self.assertTrue({"Examinations", "Fees and Finance", "IQAC"}.isdisjoint(areas), areas)
