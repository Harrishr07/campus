/* P3-T07 Feedback page: posts the answers as JSON {question row: value} with the campaign and, for an invited member, the signed link. */
(function () {
	var form = document.getElementById("cp-feedback");
	if (!form) return;
	form.addEventListener("submit", function (event) {
		event.preventDefault();
		var answers = {};
		form.querySelectorAll("[data-question]").forEach(function (block) {
			var name = block.dataset.question;
			var picked = block.querySelector("input:checked");
			var text = block.querySelector("textarea");
			answers[name] = picked ? picked.value : (text ? text.value : null);
		});
		var body = new FormData();
		body.append("campaign", form.dataset.campaign);
		body.append("answers", JSON.stringify(answers));
		if (form.dataset.member) {
			body.append("member", form.dataset.member);
			body.append("signature", form.dataset.signature);
		}
		cpPost("campus.iqac.feedback.submit_response", body, form.querySelector(".cp-message"),
			form.querySelector("button[type=submit]"), function () { window.location.reload(); });
	});
})();
