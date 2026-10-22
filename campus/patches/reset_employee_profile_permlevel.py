"""P2-T05 fix 2: put the Employee faculty profile fields back at permlevel 0 and remove the Custom DocPerm rows the
earlier permlevel-1 move created (see campus.faculty.setup.undo_permlevel_one for how the rows are told apart)."""

from campus.faculty.setup import undo_permlevel_one


def execute():
	undo_permlevel_one()
