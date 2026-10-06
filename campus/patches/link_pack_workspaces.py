"""M17-01 Link the COE and IQAC Module Packs to their workspaces (hidden with the pack). Re-runnable."""

from campus.campus_platform.module_packs import link_pack_workspaces


def execute():
	link_pack_workspaces()
