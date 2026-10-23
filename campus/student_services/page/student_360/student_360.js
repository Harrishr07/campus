// M05-11 Student 360: one page per student; the server sends only the sections the user may read.
frappe.pages["student-360"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Student 360"), single_column: true });
	const body = $('<div class="student-360 p-3"></div>').appendTo(page.main);
	const field = page.add_field({
		fieldname: "student", label: __("Student"), fieldtype: "Link", options: "Student",
		change: () => load(field.get_value()),
	});

	function load(student) {
		if (!student) return;
		frappe.set_route("student-360", student);
		frappe.call({
			method: "campus.student_services.student_360.desk_view",
			args: { student },
			callback: (r) => render(r.message),
		});
	}

	function table(columns, rows, link) {
		if (!rows || !rows.length) return `<p class="text-muted">${__("None")}</p>`;
		const head = columns.map((c) => `<th>${frappe.utils.escape_html(__(frappe.model.unscrub(c)))}</th>`).join("");
		const lines = rows.map((row) => "<tr>" + columns.map((c) => {
			const value = frappe.utils.escape_html(frappe.format(row[c], { fieldtype: "Data" }) || "");
			return c === "name" && link ? `<td><a href="/app/${frappe.router.slug(link)}/${encodeURIComponent(row[c])}">${value}</a></td>` : `<td>${value}</td>`;
		}).join("") + "</tr>").join("");
		return `<table class="table table-bordered table-sm"><thead><tr>${head}</tr></thead><tbody>${lines}</tbody></table>`;
	}

	function card(title, html) {
		return `<div class="card mb-3"><div class="card-body"><h5>${frappe.utils.escape_html(title)}</h5>${html}</div></div>`;
	}

	function render(data) {
		const s = data.sections;
		const parts = [];
		const p = s.profile;
		parts.push(card(__("Profile"), `<p><strong>${frappe.utils.escape_html(p.student_name || "")}</strong> (${frappe.utils.escape_html(data.student)})</p>` +
			table(["guardian", "guardian_name", "relation"], p.guardians) +
			`<p>${__("Register No")}: ${frappe.utils.escape_html(p.oc_register_no || "-")} | ${__("Roll No")}: ${frappe.utils.escape_html(p.oc_roll_no || "-")} | ${__("Aadhaar")}: ${frappe.utils.escape_html(p.oc_aadhaar_masked || "-")}</p>`));
		if (s.lifecycle) parts.push(card(__("Lifecycle Status"), `<p>${__("Current")}: <strong>${frappe.utils.escape_html(s.lifecycle.status || "-")}</strong></p>` +
			table(["name", "kind", "from_status", "to_status", "effective_date", "reason"], s.lifecycle.history, "Lifecycle Transition")));
		if (s.enrollments) parts.push(card(__("Enrollments"), table(["name", "program", "academic_year", "enrollment_date"], s.enrollments, "Program Enrollment")));
		if (s.attendance) parts.push(card(__("Attendance"), s.attendance.summary
			? `<p>${frappe.utils.escape_html(s.attendance.academic_term)}: ${s.attendance.summary.overall_pct}% (${frappe.utils.escape_html(s.attendance.summary.status || "")})</p>`
			: `<p class="text-muted">${__("No attendance summary")}</p>`));
		if (s.results) parts.push(card(__("Results"), `<p>${__("CGPA")}: ${s.results.cgpa == null ? "-" : s.results.cgpa}</p>` + table(["name", "exam_session", "sgpa", "cgpa"], s.results.results, "Student Result")));
		if (s.fees) parts.push(card(__("Fees"), `<p>${__("Outstanding")}: ${s.fees.total_outstanding}</p>` + table(["name", "posting_date", "grand_total", "outstanding_amount"], s.fees.invoices, "Sales Invoice")));
		if (s.certificates) parts.push(card(__("Certificates"), table(["name", "certificate_type", "issued_on", "certificate_number"], s.certificates, "Certificate Request")));
		if (s.mentoring) {
			const m = s.mentoring;
			const links = (rows, dt) => (rows ? rows.names.map((n) => `<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(n)}">${frappe.utils.escape_html(n)}</a>`).join(", ") : "");
			parts.push(card(__("Mentoring"), (m.counselling_notes ? `<p>${__("Counselling Notes")}: ${m.counselling_notes.count} ${links(m.counselling_notes, "Counselling Note")}</p>` : "") +
				(m.parent_interactions ? `<p>${__("Parent Interactions")}: ${m.parent_interactions.count} ${links(m.parent_interactions, "Parent Interaction")}</p>` : "")));
		}
		if (s.corrections) parts.push(card(__("Corrections"), table(["name", "category", "field_name", "status"], s.corrections, "Student Record Correction")));
		body.html(parts.join(""));
	}

	const route = frappe.get_route();
	if (route[1]) field.set_value(route[1]);
};
