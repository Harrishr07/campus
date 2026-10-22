"""M02-01 Link the Governance Module Pack to the Academic Governance workspace (hidden with the pack). Re-runnable."""

from campus.campus_platform.module_packs import link_pack_workspaces


def execute():
	link_pack_workspaces()
