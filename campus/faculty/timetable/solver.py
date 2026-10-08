"""M07-03 Timetable solver interface: `solve(problem) -> Result`.

The default backend is the pure-Python search in `backtracking` (greedy placement with limited backtracking for the
hard constraints, a cost function for the soft ones). OR-Tools is not a dependency: when it is installed and
`campus.faculty.timetable.cpsat` exists, that CP-SAT backend (same `solve(problem)` signature) is used instead.
"""

import importlib
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
	unmet: list = field(default_factory=list)  # one readable line per constraint the solver could not satisfy
	soft_issues: int = 0


def solve(problem):
	backend = cpsat_backend()
	if backend:
		return backend.solve(problem)
	from campus.faculty.timetable import backtracking

	return backtracking.solve(problem)


def cpsat_backend():
	try:
		import ortools  # noqa: F401
	except ImportError:
		return None
	try:
		return importlib.import_module("campus.faculty.timetable.cpsat")
	except ImportError:
		return None
