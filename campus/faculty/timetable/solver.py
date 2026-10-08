"""M07-03 Timetable solver interface: `solve(problem) -> Result`.

OR-Tools CP-SAT (`cpsat`) is used when it imports; otherwise the pure-Python search in `backtracking` (greedy placement
with limited backtracking for the hard constraints, a cost function for the soft ones). Both return a `Result`.
"""

from dataclasses import dataclass, field
from typing import NamedTuple

DEFAULT_TIME_LIMIT = 120  # seconds the search may use before it settles for the best partial result


class Session(NamedTuple):
	"""One class to place: `length` consecutive periods of `kind` for `offering`, taught by `faculty`."""

	id: int
	offering: str
	section: str
	faculty: str
	kind: str
	length: int
	strength: int


@dataclass
class Problem:
	grid: object
	sessions: list
	time_limit: int = DEFAULT_TIME_LIMIT


@dataclass
class Result:
	entries: list = field(default_factory=list)
	unmet: list = field(default_factory=list)  # one readable line per class the solver did not place
	soft_issues: int = 0
	status: str = "heuristic"  # optimal / feasible / infeasible (CP-SAT, proven) or heuristic (the search)
	backend: str = "search"
	unplaced: int = 0  # classes (sessions) left out
	placements: dict = field(default_factory=dict)  # session id -> (day, start period, room)


def solve(problem):
	"""CP-SAT when OR-Tools imports, else the pure-Python search. A CP-SAT backend that errors falls back to the search."""
	if ortools_available():
		from campus.faculty.timetable import cpsat

		return cpsat.solve(problem)
	from campus.faculty.timetable import backtracking

	return backtracking.solve(problem)


def ortools_available():
	try:
		import ortools  # noqa: F401
	except ImportError:
		return False
	return True
