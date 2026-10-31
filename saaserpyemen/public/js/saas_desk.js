// Shopzad SaaS — shared Desk helpers.
// Loaded globally in Desk via app_include_js, so keep it defensive and side-effect free.
(function () {
	if (window.saas_desk) {
		return;
	}

	const STATUS_CLASS = {
		Active: "is-success",
		Trial: "is-info",
		Paid: "is-success",
		Completed: "is-success",
		Success: "is-success",
		Provisioning: "is-info",
		Running: "is-info",
		"Pending Review": "is-warning",
		Pending: "is-warning",
		"Past Due": "is-warning",
		"Not Requested": "is-muted",
		Draft: "is-muted",
		Issued: "is-success",
		Suspended: "is-danger",
		Expired: "is-danger",
		Cancelled: "is-muted",
		Failed: "is-danger",
		Rejected: "is-danger",
		Refunded: "is-muted",
	};

	function escape_html(value) {
		return String(value === undefined || value === null ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

	function money(value, currency) {
		const amount = Number(value || 0);
		const code = currency || frappe.boot.sysdefaults.currency || "USD";
		try {
			return new Intl.NumberFormat(frappe.boot.lang || "en", {
				style: "currency",
				currency: code,
				maximumFractionDigits: 2,
			}).format(amount);
		} catch (e) {
			return `${code} ${amount.toFixed(2)}`;
		}
	}

	function number(value) {
		return new Intl.NumberFormat(frappe.boot.lang || "en").format(Number(value || 0));
	}

	function date(value) {
		if (!value) {
			return "—";
		}
		try {
			return frappe.datetime.str_to_user(String(value).slice(0, 10));
		} catch (e) {
			return String(value);
		}
	}

	function status_class(status) {
		return STATUS_CLASS[status] || "is-muted";
	}

	function badge(status) {
		if (!status) {
			return '<span class="saas-badge is-muted">—</span>';
		}
		return `<span class="saas-badge ${status_class(status)}">${escape_html(__(status))}</span>`;
	}

	function call(method, args) {
		return frappe
			.call({
				method,
				args: args || {},
				freeze: true,
				freeze_message: __("Please wait…"),
			})
			.then((response) => response.message);
	}

	function run(method, args, success_message) {
		return call(method, args).then((message) => {
			if (success_message) {
				frappe.show_alert({ message: __(success_message), indicator: "green" }, 5);
			}
			return message;
		});
	}

	function confirm(message, label) {
		return new Promise((resolve) => {
			frappe.confirm(__(message), () => resolve(true), () => resolve(false));
		});
	}

	function prompt(options) {
		return new Promise((resolve) => {
			const dialog = new frappe.ui.Dialog({
				title: options.title,
				fields: options.fields || [
					{
						fieldname: "value",
						fieldtype: "Small Text",
						label: options.label || __("Reason"),
						reqd: options.reqd || 0,
					},
				],
				primary_action_label: options.primary_action_label || __("Submit"),
				primary_action(values) {
					dialog.hide();
					resolve(values || {});
				},
			});
			dialog.show();
			dialog.$wrapper.on("hidden.bs.modal", () => resolve(null));
		});
	}

	function error_message(error) {
		if (!error) {
			return __("Something went wrong.");
		}
		if (typeof error === "string") {
			return error;
		}
		if (error.message) {
			return error.message;
		}
		return __("Something went wrong.");
	}

	function handle_error(error) {
		frappe.show_alert(
			{ message: escape_html(error_message(error)), indicator: "red" },
			8
		);
	}

	window.saas_desk = {
		escape_html,
		money,
		number,
		date,
		status_class,
		badge,
		call,
		run,
		confirm,
		prompt,
		error_message,
		handle_error,
	};
})();
