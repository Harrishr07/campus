frappe.query_reports["Feedback Analysis"] = {
	filters: [
		{ fieldname: "company", label: __("College"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Question\nCourse\nFaculty", default: "Question", reqd: 1 },
		{
			fieldname: "campaign", label: __("Campaign"), fieldtype: "Link", options: "Feedback Campaign",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{ fieldname: "academic_year", label: __("Academic Year"), fieldtype: "Link", options: "Academic Year" },
		{ fieldname: "course_offering", label: __("Course Offering"), fieldtype: "Link", options: "Student Group" },
		{ fieldname: "instructor", label: __("Instructor"), fieldtype: "Link", options: "Instructor" },
	],
};
