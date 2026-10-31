frappe.pages["saas-control-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("SaaS Control Center"),
		single_column: true,
	});

	wrapper.saas_control_center = new SaasControlCenter(page, wrapper);
};

frappe.pages["saas-control-center"].on_page_show = function (wrapper) {
	const control = wrapper.saas_control_center;
	if (control && !control.data) {
		control.refresh();
	}
};

class SaasControlCenter {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.data = null;
		this.$root = $(frappe.templates["saas_control_center"]).appendTo(page.body);
		this.make_toolbar();
		this.bind_events();
		this.refresh();
	}

	make_toolbar() {
		this.page.set_primary_action(__("New Tenant"), () => frappe.new_doc("SaaS Tenant"), "add");

		this.page.add_inner_button(__("Sync Usage"), () => {
			saas_desk
				.run("saaserpyemen.api.sync_usage", {}, __("Usage synced for all workspaces."))
				.then(() => this.refresh())
				.catch((error) => saas_desk.handle_error(error));
		});

		this.page.add_inner_button(__("New Plan"), () => frappe.new_doc("SaaS Plan"));
		this.page.add_inner_button(__("SaaS Settings"), () => frappe.set_route("Form", "SaaS Settings"));
	}

	bind_events() {
		this.$root.on("click", "[data-action]", (event) => {
			const $target = $(event.currentTarget);
			const action = $target.attr("data-action");
			if (!action || action === "open-website") {
				return;
			}
			event.preventDefault();
			this.handle_action(action, $target);
		});
	}

	refresh() {
		this.set_loading(true);
		saas_desk
			.call("saaserpyemen.api.get_admin_dashboard")
			.then((data) => {
				this.data = data;
				this.render(data);
				this.set_loading(false);
			})
			.catch((error) => {
				this.set_loading(false, error);
			});
	}

	set_loading(loading, error) {
		this.$root.find('[data-region="loading"]').prop("hidden", !loading);
		this.$root.find('[data-region="content"]').prop("hidden", loading || Boolean(error));
		const $error = this.$root.find('[data-region="error"]');
		if (error) {
			$error
				.prop("hidden", false)
				.html(
					`<strong>${__("Could not load the dashboard.")}</strong><br>${saas_desk.escape_html(
						saas_desk.error_message(error)
					)}`
				);
		} else {
			$error.prop("hidden", true).empty();
		}
	}

	render(data) {
		this.render_kpis(data.kpis, data.currency);
		this.render_bars(
			this.$root.find('[data-region="signups"]'),
			month_series(data.signups || [], "total"),
			{ format: (value) => saas_desk.number(value) }
		);
		this.render_bars(
			this.$root.find('[data-region="revenue"]'),
			month_series(data.revenue || [], "total"),
			{ format: (value) => saas_desk.money(value, data.currency) }
		);
		this.render_pending_payments(data.pending_payments_list || [], data.currency);
		this.render_by_plan(data.by_plan || []);
		this.render_recent_tenants(data.recent_tenants || []);
		this.render_expiring(data.expiring || [], data.currency);

		const website = data.website_url || "/";
		this.$root.find('[data-action="open-website"]').attr("href", website);
	}

	render_kpis(kpis, currency) {
		const cards = [
			{
				label: __("Monthly recurring revenue"),
				value: saas_desk.money(kpis.mrr, currency),
				hint: __("Normalised to {0}", [currency]),
				tone: "violet",
			},
			{
				label: __("Annual recurring revenue"),
				value: saas_desk.money(kpis.arr, currency),
				hint: __("Projected 12 months"),
				tone: "blue",
			},
			{
				label: __("Collected this month"),
				value: saas_desk.money(kpis.paid_this_month, currency),
				hint: __("Approved payments"),
				tone: "green",
			},
			{
				label: __("Total workspaces"),
				value: saas_desk.number(kpis.total_tenants),
				hint: __("{0} active", [saas_desk.number(kpis.active_tenants)]),
				tone: "slate",
			},
			{
				label: __("On trial"),
				value: saas_desk.number(kpis.trial_tenants),
				hint: __("Free trial workspaces"),
				tone: "cyan",
			},
			{
				label: __("Pending payments"),
				value: saas_desk.number(kpis.pending_payments),
				hint: __("Awaiting review"),
				tone: "amber",
				action: "open-payments",
			},
			{
				label: __("Past due"),
				value: saas_desk.number(kpis.past_due),
				hint: __("Grace period"),
				tone: "orange",
			},
			{
				label: __("Suspended"),
				value: saas_desk.number(kpis.suspended),
				hint: __("{0} failed provisions", [saas_desk.number(kpis.failed)]),
				tone: "red",
			},
		];

		const html = cards
			.map(
				(card) => `
			<div class="saas-desk-kpi is-${card.tone}" ${
					card.action ? `data-action="${card.action}" role="button" tabindex="0"` : ""
				}>
				<span class="saas-desk-kpi-label">${saas_desk.escape_html(card.label)}</span>
				<strong class="saas-desk-kpi-value">${saas_desk.escape_html(card.value)}</strong>
				<span class="saas-desk-kpi-hint">${saas_desk.escape_html(card.hint)}</span>
			</div>`
			)
			.join("");

		this.$root.find('[data-region="kpis"]').html(html);
	}

	render_bars($el, series, options) {
		if (!series.length || series.every((row) => !row.value)) {
			$el.html(`<div class="saas-desk-empty">${__("No data yet.")}</div>`);
			return;
		}

		const max = Math.max.apply(
			null,
			series.map((row) => Number(row.value) || 0)
		);
		const formatter = options.format || ((value) => saas_desk.number(value));

		const bars = series
			.map((row) => {
				const value = Number(row.value) || 0;
				const height = max > 0 ? Math.max((value / max) * 100, value > 0 ? 4 : 0) : 0;
				return `
				<div class="saas-desk-bar" title="${saas_desk.escape_html(formatter(value))}">
					<span class="saas-desk-bar-value">${saas_desk.escape_html(formatter(value))}</span>
					<div class="saas-desk-bar-track">
						<span style="height:${height}%"></span>
					</div>
					<span class="saas-desk-bar-label">${saas_desk.escape_html(short_month(row.month))}</span>
				</div>`;
			})
			.join("");

		$el.html(`<div class="saas-desk-bars">${bars}</div>`);
	}

	render_pending_payments(rows, currency) {
		const $el = this.$root.find('[data-region="pending-payments"]');
		if (!rows.length) {
			$el.html(`<div class="saas-desk-empty">${__("No payments waiting for review. 🎉")}</div>`);
			return;
		}

		const body = rows
			.map(
				(row) => `
			<tr>
				<td>
					<button class="saas-desk-linkbtn" data-action="open-payment" data-payment="${saas_desk.escape_html(
						row.name
					)}">${saas_desk.escape_html(row.name)}</button>
					<div class="saas-desk-muted">${saas_desk.escape_html(row.reference_no || "—")}</div>
				</td>
				<td>
					<button class="saas-desk-linkbtn" data-action="open-tenant" data-tenant="${saas_desk.escape_html(
						row.tenant
					)}">${saas_desk.escape_html(row.tenant_name || row.tenant || "—")}</button>
				</td>
				<td class="is-numeric">${saas_desk.escape_html(saas_desk.money(row.amount, row.currency || currency))}</td>
				<td>${saas_desk.date(row.creation)}</td>
				<td class="saas-desk-actions">
					<button class="saas-desk-btn is-success is-small" data-action="approve-payment" data-payment="${saas_desk.escape_html(
						row.name
					)}">${__("Approve")}</button>
					<button class="saas-desk-btn is-danger is-small" data-action="reject-payment" data-payment="${saas_desk.escape_html(
						row.name
					)}">${__("Reject")}</button>
					${
						row.receipt
							? `<a class="saas-desk-btn is-ghost is-small" href="${saas_desk.escape_html(
									row.receipt
							  )}" target="_blank" rel="noopener">${__("Receipt")}</a>`
							: ""
					}
				</td>
			</tr>`
			)
			.join("");

		$el.html(`
			<table class="saas-desk-table">
				<thead>
					<tr>
						<th>${__("Payment")}</th>
						<th>${__("Workspace")}</th>
						<th class="is-numeric">${__("Amount")}</th>
						<th>${__("Submitted")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>`);
	}

	render_by_plan(rows) {
		const $el = this.$root.find('[data-region="by-plan"]');
		if (!rows.length) {
			$el.html(`<div class="saas-desk-empty">${__("No workspaces yet.")}</div>`);
			return;
		}

		const total = rows.reduce((sum, row) => sum + (Number(row.total) || 0), 0) || 1;
		const html = rows
			.map((row) => {
				const value = Number(row.total) || 0;
				const percent = Math.round((value / total) * 100);
				return `
				<div class="saas-desk-plan-row">
					<div class="saas-desk-plan-meta">
						<span>${saas_desk.escape_html(row.plan || __("No plan"))}</span>
						<span class="saas-desk-muted">${saas_desk.number(value)}</span>
					</div>
					<div class="saas-desk-progress"><span style="width:${percent}%"></span></div>
				</div>`;
			})
			.join("");

		$el.html(html);
	}

	render_recent_tenants(rows) {
		const $el = this.$root.find('[data-region="recent-tenants"]');
		if (!rows.length) {
			$el.html(`<div class="saas-desk-empty">${__("No workspaces yet.")}</div>`);
			return;
		}

		const body = rows
			.map((row) => {
				const is_suspended = ["Suspended", "Expired", "Cancelled"].includes(row.status);
				const provision_label = ["Failed", "Draft"].includes(row.status)
					? __("Provision")
					: __("Re-provision");

				return `
				<tr>
					<td>
						<button class="saas-desk-linkbtn" data-action="open-tenant" data-tenant="${saas_desk.escape_html(
							row.name
						)}">${saas_desk.escape_html(row.tenant_name || row.subdomain || row.name)}</button>
						<div class="saas-desk-muted">${saas_desk.escape_html(row.subdomain || "—")}</div>
					</td>
					<td>${saas_desk.escape_html(row.plan || "—")}</td>
					<td>${saas_desk.badge(row.status)}</td>
					<td class="is-numeric">${saas_desk.number(row.users_count)}</td>
					<td class="is-numeric">${saas_desk.number(row.storage_used_mb)} MB</td>
					<td>${saas_desk.date(row.creation)}</td>
					<td class="saas-desk-actions">
						<button class="saas-desk-btn is-ghost is-small" data-action="open-tenant" data-tenant="${saas_desk.escape_html(
							row.name
						)}">${__("Open")}</button>
						<details class="saas-desk-menu">
							<summary aria-label="${__("More actions")}">⋯</summary>
							<div class="saas-desk-menu-list">
								<button data-action="provision-tenant" data-tenant="${saas_desk.escape_html(
									row.name
								)}">${provision_label}</button>
								<button data-action="sync-tenant-usage" data-tenant="${saas_desk.escape_html(
									row.name
								)}">${__("Sync usage")}</button>
								<button data-action="extend-subscription" data-tenant="${saas_desk.escape_html(
									row.name
								)}" data-subdomain="${saas_desk.escape_html(row.subdomain || "")}">${__(
									"Extend subscription"
								)}</button>
								<button data-action="request-ssl" data-tenant="${saas_desk.escape_html(
									row.name
								)}">${__("Request SSL")}</button>
								${
									is_suspended
										? `<button data-action="unsuspend-tenant" data-tenant="${saas_desk.escape_html(
												row.name
										  )}">${__("Reactivate")}</button>`
										: `<button data-action="suspend-tenant" data-tenant="${saas_desk.escape_html(
												row.name
										  )}">${__("Suspend")}</button>`
								}
								<button class="is-danger" data-action="delete-tenant" data-tenant="${saas_desk.escape_html(
									row.name
								)}" data-subdomain="${saas_desk.escape_html(row.subdomain || "")}">${__(
									"Delete workspace"
								)}</button>
							</div>
						</details>
					</td>
				</tr>`;
			})
			.join("");

		$el.html(`
			<table class="saas-desk-table">
				<thead>
					<tr>
						<th>${__("Workspace")}</th>
						<th>${__("Plan")}</th>
						<th>${__("Status")}</th>
						<th class="is-numeric">${__("Users")}</th>
						<th class="is-numeric">${__("Storage")}</th>
						<th>${__("Created")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>`);
	}

	render_expiring(rows, currency) {
		const $el = this.$root.find('[data-region="expiring"]');
		if (!rows.length) {
			$el.html(`<div class="saas-desk-empty">${__("Nothing expires in the next 14 days.")}</div>`);
			return;
		}

		const body = rows
			.map(
				(row) => `
			<tr>
				<td>
					<button class="saas-desk-linkbtn" data-action="open-subscription" data-subscription="${saas_desk.escape_html(
						row.name
					)}">${saas_desk.escape_html(row.tenant_name || row.tenant || row.name)}</button>
				</td>
				<td>${saas_desk.escape_html(row.plan || "—")}</td>
				<td>${saas_desk.badge(row.status)}</td>
				<td>${saas_desk.date(row.end_date)}</td>
				<td class="is-numeric">${saas_desk.escape_html(saas_desk.money(row.amount, row.currency || currency))}</td>
				<td class="saas-desk-actions">
					<button class="saas-desk-btn is-ghost is-small" data-action="extend-subscription" data-tenant="${saas_desk.escape_html(
						row.tenant
					)}">${__("Extend")}</button>
				</td>
			</tr>`
			)
			.join("");

		$el.html(`
			<table class="saas-desk-table">
				<thead>
					<tr>
						<th>${__("Workspace")}</th>
						<th>${__("Plan")}</th>
						<th>${__("Status")}</th>
						<th>${__("Ends on")}</th>
						<th class="is-numeric">${__("Amount")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>`);
	}

	handle_action(action, $target) {
		const tenant = $target.attr("data-tenant");
		const payment = $target.attr("data-payment");
		const subdomain = $target.attr("data-subdomain");

		switch (action) {
			case "refresh":
				this.refresh();
				break;
			case "open-payments":
				frappe.set_route("List", "SaaS Payment", { status: "Pending Review" });
				break;
			case "open-tenants":
				frappe.set_route("List", "SaaS Tenant");
				break;
			case "open-tenant":
				frappe.set_route("Form", "SaaS Tenant", tenant);
				break;
			case "open-payment":
				frappe.set_route("Form", "SaaS Payment", payment);
				break;
			case "open-subscription":
				frappe.set_route("Form", "SaaS Subscription", $target.attr("data-subscription"));
				break;
			case "approve-payment":
				this.approve_payment(payment);
				break;
			case "reject-payment":
				this.reject_payment(payment);
				break;
			case "provision-tenant":
				this.provision_tenant(tenant);
				break;
			case "suspend-tenant":
				this.suspend_tenant(tenant);
				break;
			case "unsuspend-tenant":
				this.unsuspend_tenant(tenant);
				break;
			case "sync-tenant-usage":
				this.run_action("saaserpyemen.api.sync_usage", { tenant }, __("Usage synced."));
				break;
			case "extend-subscription":
				this.extend_subscription(tenant);
				break;
			case "request-ssl":
				this.request_ssl(tenant);
				break;
			case "delete-tenant":
				this.delete_tenant(tenant, subdomain);
				break;
			default:
				break;
		}
	}

	run_action(method, args, message) {
		saas_desk
			.run(method, args, message)
			.then(() => this.refresh())
			.catch((error) => saas_desk.handle_error(error));
	}

	approve_payment(payment) {
		saas_desk
			.confirm(
				__("Approve this payment? The subscription will be extended and the workspace reactivated."),
				__("Approve")
			)
			.then((confirmed) => {
				if (!confirmed) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.approve_payment",
					{ payment },
					__("Payment approved and subscription extended.")
				);
			});
	}

	reject_payment(payment) {
		saas_desk
			.prompt({
				title: __("Reject payment"),
				label: __("Reason (shared with the customer)"),
				primary_action_label: __("Reject payment"),
			})
			.then((values) => {
				if (!values) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.reject_payment",
					{ payment, reason: values.value || "" },
					__("Payment rejected.")
				);
			});
	}

	provision_tenant(tenant) {
		saas_desk
			.confirm(
				__(
					"Provision this workspace now? A new site and database will be created from the template. This can take a few minutes."
				),
				__("Provision")
			)
			.then((confirmed) => {
				if (!confirmed) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.provision_tenant",
					{ tenant },
					__("Provisioning queued. Track progress in the provisioning log.")
				);
			});
	}

	suspend_tenant(tenant) {
		saas_desk
			.prompt({
				title: __("Suspend workspace"),
				label: __("Reason"),
				primary_action_label: __("Suspend"),
			})
			.then((values) => {
				if (!values) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.suspend_tenant",
					{ tenant, reason: values.value || "" },
					__("Workspace suspended.")
				);
			});
	}

	unsuspend_tenant(tenant) {
		saas_desk
			.confirm(__("Reactivate this workspace?"), __("Reactivate"))
			.then((confirmed) => {
				if (!confirmed) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.unsuspend_tenant",
					{ tenant },
					__("Workspace reactivated.")
				);
			});
	}

	extend_subscription(tenant) {
		saas_desk
			.prompt({
				title: __("Extend subscription"),
				primary_action_label: __("Extend"),
				fields: [
					{
						fieldname: "cycle",
						fieldtype: "Select",
						label: __("Billing cycle"),
						options: ["Monthly", "Yearly"],
						default: "Monthly",
						reqd: 1,
					},
				],
			})
			.then((values) => {
				if (!values) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.extend_subscription",
					{ tenant, cycle: values.cycle || "Monthly" },
					__("Subscription extended.")
				);
			});
	}

	request_ssl(tenant) {
		saas_desk
			.confirm(__("Request an SSL certificate for this workspace?"), __("Request SSL"))
			.then((confirmed) => {
				if (!confirmed) {
					return;
				}
				this.run_action(
					"saaserpyemen.api.request_ssl",
					{ tenant },
					__("SSL request queued.")
				);
			});
	}

	delete_tenant(tenant, subdomain) {
		saas_desk
			.prompt({
				title: __("Delete workspace"),
				primary_action_label: __("Delete permanently"),
				fields: [
					{
						fieldname: "confirm",
						fieldtype: "Data",
						label: __("Type “{0}” to confirm", [subdomain || tenant]),
						reqd: 1,
					},
				],
			})
			.then((values) => {
				if (!values) {
					return;
				}
				const expected = subdomain || tenant;
				if ((values.confirm || "").trim() !== expected) {
					frappe.show_alert(
						{ message: __("The confirmation text does not match."), indicator: "red" },
						6
					);
					return;
				}
				this.run_action(
					"saaserpyemen.api.delete_tenant",
					{ tenant, confirm: values.confirm.trim() },
					__("Workspace deleted.")
				);
			});
	}
}

function month_series(rows, value_key) {
	const map = {};
	(rows || []).forEach((row) => {
		if (row && row.month) {
			map[row.month] = Number(row[value_key]) || 0;
		}
	});

	const series = [];
	const now = new Date();
	for (let index = 11; index >= 0; index -= 1) {
		const date = new Date(now.getFullYear(), now.getMonth() - index, 1);
		const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
		series.push({ month: key, value: map[key] || 0 });
	}
	return series;
}

function short_month(key) {
	if (!key) {
		return "";
	}
	const parts = String(key).split("-");
	const date = new Date(Number(parts[0]), Number(parts[1]) - 1, 1);
	try {
		return new Intl.DateTimeFormat(frappe.boot.lang || "en", { month: "short" }).format(date);
	} catch (error) {
		return key;
	}
}
