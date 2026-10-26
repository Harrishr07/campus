/* P2-T11 Faculty portal: attendance (all present, ticked absentees) and CIA marks posted as JSON through cpPost (campus_portal.js). */
function cpReload() {
	window.location.reload();
}

document.querySelectorAll("form[data-attendance]").forEach(function (form) {
	var count = form.querySelector("[data-count]");
	function boxes() {
		return Array.prototype.slice.call(form.querySelectorAll("input[name=absent]"));
	}
	function absentees() {
		return boxes()
			.filter(function (box) {
				return box.checked;
			})
			.map(function (box) {
				return box.value;
			});
	}
	function showCount() {
		var absent = absentees().length;
		count.textContent =
			count.dataset.labelPresent +
			" " +
			(boxes().length - absent) +
			" / " +
			count.dataset.labelAbsent +
			" " +
			absent;
	}
	form.addEventListener("change", showCount);
	showCount();
	form.addEventListener("submit", function (event) {
		event.preventDefault();
		var body = new FormData();
		body.append("course_schedule", form.elements.course_schedule.value);
		body.append("absent", JSON.stringify(absentees()));
		body.append("version", form.elements.version.value); // refused if someone marked the period since the page loaded
		cpPost(
			"campus.faculty.portal.mark_attendance",
			body,
			form.querySelector(".cp-message"),
			form.querySelector("button[type=submit]"),
			cpReload
		);
	});
});

document.querySelectorAll("form[data-cia]").forEach(function (form) {
	form.addEventListener("submit", function (event) {
		event.preventDefault();
		var rows = [];
		form.querySelectorAll("input[data-question]").forEach(function (input) {
			var absent = input.parentElement.querySelector("input[data-absent]");
			var cleared = input.value === "" && input.dataset.initial !== "";
			if (input.value === "" && !cleared && !absent.checked) {
				return;
			} // never entered: not posted as 0
			rows.push({
				student: input.dataset.student,
				component: input.dataset.component,
				question: input.dataset.question,
				marks: input.value === "" ? null : input.value,
				absent: absent.checked ? 1 : 0,
			});
		});
		form.querySelectorAll("input[data-cia]").forEach(function (input) {
			if (input.value === "") {
				return;
			}
			rows.push({ student: input.dataset.student, cia: input.value });
		});
		var body = new FormData();
		body.append("mark_sheet", form.elements.mark_sheet.value);
		body.append("marks", JSON.stringify(rows));
		cpPost(
			"campus.faculty.portal_cia.save_cia_marks",
			body,
			form.querySelector(".cp-message"),
			form.querySelector("button[type=submit]"),
			cpReload
		);
	});
});
