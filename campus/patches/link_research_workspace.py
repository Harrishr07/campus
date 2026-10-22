"""M08-02 Link the Research Module Pack to the Research workspace (hidden with the pack). Re-runnable."""

from campus.campus_platform.module_packs import link_pack_workspaces


def execute():
	link_pack_workspaces()
