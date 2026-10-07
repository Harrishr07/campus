/* P1-T26 Student portal: posts a form (with its optional file) to a whitelisted method with the CSRF token. */
document.querySelectorAll("form[data-method]").forEach(function (form) {
	form.addEventListener("submit", function (event) {
		event.preventDefault();
		var message = form.querySelector(".cp-message");
		var button = form.querySelector("button[type=submit]");
		button.disabled = true;
		message.textContent = "";
		fetch("/api/method/" + form.dataset.method, {
			method: "POST",
			headers: {"X-Frappe-CSRF-Token": frappe.csrf_token, "Accept": "application/json"},
			body: new FormData(form),
		}).then(function (response) {
			if (response.ok) { window.location.reload(); return; }
			return response.json().then(function (body) {
				var text = "";
				try { text = JSON.parse(JSON.parse(body._server_messages)[0]).message; } catch (e) { text = body.exception || ""; }
				var holder = document.createElement("div");
				holder.innerHTML = text;
				message.textContent = holder.textContent;
				button.disabled = false;
			});
		});
	});
});

document.querySelectorAll("button[data-pay]").forEach(function (button) {
	button.addEventListener("click", function () {
		var message = button.parentElement.querySelector(".cp-message");
		var body = new FormData();
		body.append("invoice", button.dataset.pay);
		body.append("student", button.dataset.student);
		button.disabled = true;
		fetch("/api/method/campus.student_services.portal.pay_invoice", {
			method: "POST",
			headers: {"X-Frappe-CSRF-Token": frappe.csrf_token, "Accept": "application/json"},
			body: body,
		}).then(function (response) {
			return response.json().then(function (data) {
				if (response.ok && data.message && data.message.url) { window.location.href = data.message.url; return; }
				var text = "";
				try { text = JSON.parse(JSON.parse(data._server_messages)[0]).message; } catch (e) { text = data.exception || ""; }
				var holder = document.createElement("div");
				holder.innerHTML = text;
				message.textContent = holder.textContent;
				button.disabled = false;
			});
		});
	});
});
