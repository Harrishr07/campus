/* P1-T26 Student portal: posts a form (with its optional file) or a pay request to a whitelisted method, with the CSRF token. */
function cpPost(method, body, message, button, onDone) {
	function fail(text) {
		message.textContent = text || "";
		button.disabled = false;
	}
	button.disabled = true;
	message.textContent = "";
	fetch("/api/method/" + method, {
		method: "POST",
		headers: {"X-Frappe-CSRF-Token": frappe.csrf_token, "Accept": "application/json"},
		body: body,
	}).then(function (response) {
		return response.json().catch(function () { return {}; }).then(function (data) {
			if (response.ok) { onDone(data.message); return; }
			var text = "";
			try { text = JSON.parse(JSON.parse(data._server_messages)[0]).message; } catch (e) { text = data.exception || ""; }
			fail(new DOMParser().parseFromString(text, "text/html").body.textContent);
		});
	}).catch(function () { fail(document.body.dataset.cpError || "Network error. Please try again."); });
}

document.querySelectorAll("form[data-method]").forEach(function (form) {
	form.addEventListener("submit", function (event) {
		event.preventDefault();
		var body = new FormData(form);
		(form.dataset.list || "").split(",").filter(Boolean).forEach(function (name) {  // checkbox groups post as one JSON list
			body.set(name, JSON.stringify(body.getAll(name)));
		});
		cpPost(form.dataset.method, body, form.querySelector(".cp-message"),
			form.querySelector("button[type=submit]"), function () { window.location.reload(); });
	});
});

document.querySelectorAll("button[data-pay]").forEach(function (button) {
	button.addEventListener("click", function () {
		var body = new FormData();
		body.append("invoice", button.dataset.pay);
		body.append("student", button.dataset.student);
		cpPost("campus.student_services.portal.pay_invoice", body, button.parentElement.querySelector(".cp-message"), button,
			function (result) { if (result && result.url) { window.location.href = result.url; } });
	});
});
