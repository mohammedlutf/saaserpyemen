/* ==========================================================================
   Sahbix SaaS — public website & customer portal behaviour
   ========================================================================== */
(function () {
	"use strict";

	const root = document.documentElement;
	const DEFAULT_LANG = (window.saas && window.saas.lang) || "en";

	/* ----------------------------------------------------------------------
	   Small helpers
	   ---------------------------------------------------------------------- */
	function isArabic() {
		return root.classList.contains("saas-ar");
	}

	function t(en, ar) {
		return isArabic() ? ar || en : en;
	}

	function $(selector, scope) {
		return (scope || document).querySelector(selector);
	}

	function $$(selector, scope) {
		return Array.from((scope || document).querySelectorAll(selector));
	}

	function stripHtml(value) {
		if (!value) return "";
		const div = document.createElement("div");
		div.innerHTML = String(value);
		return (div.textContent || div.innerText || "").trim();
	}

	function serverMessage(payload) {
		if (!payload) return "";
		let messages = payload._server_messages;
		if (typeof messages === "string") {
			try { messages = JSON.parse(messages); } catch (e) { messages = null; }
		}
		if (Array.isArray(messages)) {
			for (const raw of messages) {
				try {
					const item = typeof raw === "string" ? JSON.parse(raw) : raw;
					if (item && item.message) return stripHtml(item.message);
				} catch (e) { /* ignore */ }
			}
		}
		if (payload.message && typeof payload.message === "string" && payload.exc_type) {
			return stripHtml(payload.message);
		}
		if (payload.exception) return stripHtml(payload.exception).split("\n").pop();
		if (payload.exc_type) return stripHtml(payload.exc_type);
		return "";
	}

	async function callFull(method, args) {
		args = args || {};
		const url = "/api/method/" + String(method).replace(/^\/+/, "");
		const body = new URLSearchParams();
		Object.keys(args).forEach(function (key) {
			const value = args[key];
			if (value === undefined || value === null) return;
			body.append(key, typeof value === "object" ? JSON.stringify(value) : String(value));
		});

		const headers = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
		if (window.saas && window.saas.csrf_token) {
			headers["X-Frappe-CSRF-Token"] = window.saas.csrf_token;
		}

		const response = await fetch(url, {
			method: "POST",
			headers: headers,
			body: body,
			credentials: "same-origin",
		});

		let data = {};
		try { data = await response.json(); } catch (e) { data = {}; }
		if (!response.ok) {
			const message = serverMessage(data) || t("Something went wrong. Please try again.", "حدث خطأ ما. يرجى المحاولة مرة أخرى.");
			const error = new Error(message);
			error.payload = data;
			error.status = response.status;
			throw error;
		}
		return data;
	}

	async function call(method, args) {
		const data = await callFull(method, args);
		return data.message;
	}

	async function uploadFile(file, isPrivate) {
		const form = new FormData();
		form.append("file", file);
		form.append("is_private", isPrivate ? "1" : "0");
		form.append("folder", "Home/Attachments");

		const headers = { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
		if (window.saas && window.saas.csrf_token) {
			headers["X-Frappe-CSRF-Token"] = window.saas.csrf_token;
		}
		const response = await fetch("/api/method/upload_file", {
			method: "POST",
			headers: headers,
			body: form,
			credentials: "same-origin",
		});
		let data = {};
		try { data = await response.json(); } catch (e) { data = {}; }
		if (!response.ok) {
			throw new Error(serverMessage(data) || t("Upload failed. Please try again.", "فشل الرفع. يرجى المحاولة مرة أخرى."));
		}
		return data.message || {};
	}

	function showError(form, message) {
		const box = form ? $("[data-form-error]", form) : $("[data-form-error]");
		if (!box) {
			toast(message, "error");
			return;
		}
		box.textContent = message;
		box.hidden = false;
		try { box.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (e) { /* ignore */ }
	}

	function clearError(form) {
		const box = form ? $("[data-form-error]", form) : $("[data-form-error]");
		if (box) { box.hidden = true; box.textContent = ""; }
	}

	function setLoading(button, loading) {
		if (!button) return;
		const spinner = $(".btn-spinner", button);
		button.classList.toggle("is-loading", !!loading);
		button.disabled = !!loading;
		if (spinner) spinner.hidden = !loading;
	}

	function toast(message, type) {
		if (!message) return;
		let host = $(".saas-toasts");
		if (!host) {
			host = document.createElement("div");
			host.className = "saas-toasts";
			host.setAttribute("role", "status");
			host.setAttribute("aria-live", "polite");
			document.body.appendChild(host);
		}
		const el = document.createElement("div");
		el.className = "saas-toast saas-toast--" + (type || "info");
		const icon = document.createElement("span");
		icon.className = "saas-toast__icon";
		icon.textContent = type === "success" ? "✓" : type === "error" ? "!" : "i";
		const text = document.createElement("span");
		text.textContent = message;
		el.appendChild(icon);
		el.appendChild(text);
		host.appendChild(el);
		window.setTimeout(function () {
			el.classList.add("is-leaving");
			window.setTimeout(function () { el.remove(); }, 260);
		}, 4200);
	}

	function confirmDialog(options) {
		options = options || {};
		return new Promise(function (resolve) {
			const modal = document.createElement("div");
			modal.className = "saas-modal open";
			modal.innerHTML =
				'<div class="saas-modal__backdrop" data-modal-cancel></div>' +
				'<div class="saas-modal__card" role="dialog" aria-modal="true">' +
				"<h3></h3><p></p>" +
				'<div class="saas-modal__actions">' +
				'<button type="button" class="saas-btn saas-btn--outline" data-modal-cancel></button>' +
				'<button type="button" class="saas-btn saas-btn--primary" data-modal-confirm></button>' +
				"</div></div>";

			$("h3", modal).textContent = options.title || t("Please confirm", "يرجى التأكيد");
			$("p", modal).textContent = options.message || "";
			$('.saas-btn--outline[data-modal-cancel]', modal).textContent =
   				 options.cancelText || t("Cancel", "إلغاء");
			$("[data-modal-confirm]", modal).textContent = options.confirmText || t("Confirm", "تأكيد");

			function close(result) {
				modal.remove();
				document.removeEventListener("keydown", onKey);
				resolve(result);
			}
			function onKey(event) {
				if (event.key === "Escape") close(false);
			}
			$$("[data-modal-cancel]", modal).forEach(function (el) {
				el.addEventListener("click", function () { close(false); });
			});
			$("[data-modal-confirm]", modal).addEventListener("click", function () { close(true); });
			document.addEventListener("keydown", onKey);
			document.body.appendChild(modal);
			const confirmButton = $("[data-modal-confirm]", modal);
			if (confirmButton) confirmButton.focus();
		});
	}

	function setBilingual(el, en, ar) {
		if (!el) return;
		el.setAttribute("data-en", en);
		el.setAttribute("data-ar", ar || en);
		el.textContent = isArabic() ? (ar || en) : en;
	}

	function normalizeSubdomain(value) {
		return String(value || "")
			.toLowerCase()
			.trim()
			.replace(/^https?:\/\//, "")
			.split("/")[0]
			.split(".")[0]
			.replace(/[^a-z0-9-]+/g, "-")
			.replace(/-{2,}/g, "-")
			.replace(/^-+|-+$/g, "");
	}

	function formatAmount(value) {
		const number = Number(value) || 0;
		const decimals = Math.abs(number - Math.round(number)) < 0.005 ? 0 : 2;
		return number.toLocaleString(isArabic() ? "ar-EG" : "en-US", {
			minimumFractionDigits: decimals,
			maximumFractionDigits: decimals,
		});
	}

	/* ----------------------------------------------------------------------
	   Language
	   ---------------------------------------------------------------------- */
	function setLanguageCookie(lang) {
		try {
			document.cookie = "preferred_language=" + encodeURIComponent(lang) + "; path=/; max-age=31536000; SameSite=Lax";
		} catch (e) { /* ignore */ }
	}

	function applyLanguage(lang) {
		const arabic = lang === "ar";
		root.classList.toggle("saas-ar", arabic);
		root.setAttribute("lang", arabic ? "ar" : "en");
		root.setAttribute("dir", arabic ? "rtl" : "ltr");
		if (window.saas) window.saas.lang = arabic ? "ar" : "en";

		$$("[data-en]").forEach(function (el) {
			if (el.children.length > 0) return;
			const text = arabic ? el.getAttribute("data-ar") : el.getAttribute("data-en");
			if (text !== null && text !== undefined) el.textContent = text;
		});

		$$("[data-en-placeholder]").forEach(function (el) {
			const text = arabic ? el.getAttribute("data-ar-placeholder") : el.getAttribute("data-en-placeholder");
			if (text) el.setAttribute("placeholder", text);
		});

		$$("[data-en-title]").forEach(function (el) {
			const text = arabic ? el.getAttribute("data-ar-title") : el.getAttribute("data-en-title");
			if (text) el.setAttribute("title", text);
		});

		$$("[data-lang-label]").forEach(function (el) {
			el.textContent = arabic ? "English" : "العربية";
		});

		document.dispatchEvent(new CustomEvent("saas:language", { detail: { lang: arabic ? "ar" : "en" } }));
	}

	function initLanguage() {
		applyLanguage(DEFAULT_LANG === "ar" ? "ar" : "en");
		$$("[data-lang-toggle]").forEach(function (button) {
			button.addEventListener("click", function () {
				const next = isArabic() ? "en" : "ar";
				setLanguageCookie(next);
				// Reload so Frappe serves the matching LTR/RTL stylesheet and
				// the server-rendered logo, instead of leaving the old
				// direction-specific bundles in place.
				window.location.reload();
			});
		});
	}

	/* ----------------------------------------------------------------------
	   Navigation & generic UI
	   ---------------------------------------------------------------------- */
	function initNavigation() {
		const toggle = $("[data-nav-toggle]");
		const links = $("[data-nav-links]");
		if (!toggle || !links) return;
		toggle.addEventListener("click", function () {
			const open = links.classList.toggle("open");
			toggle.setAttribute("aria-expanded", open ? "true" : "false");
		});
		$$("a", links).forEach(function (link) {
			link.addEventListener("click", function () {
				links.classList.remove("open");
				toggle.setAttribute("aria-expanded", "false");
			});
		});
		document.addEventListener("click", function (event) {
			if (!links.classList.contains("open")) return;
			if (links.contains(event.target) || toggle.contains(event.target)) return;
			links.classList.remove("open");
			toggle.setAttribute("aria-expanded", "false");
		});
	}

	function initLogout() {
		$$("[data-logout]").forEach(function (button) {
			button.addEventListener("click", async function (event) {
				event.preventDefault();
				button.disabled = true;
				button.classList.add("is-loading");
				try {
					await call("logout");
				} catch (error) {
					// The session may already be gone; still send the user home.
				}
				window.location.href = "/";
			});
		});
	}

	function initPasswordToggles() {
		$$("[data-toggle-password]").forEach(function (button) {
			button.addEventListener("click", function () {
				const control = button.closest(".field__control");
				const input = control ? $("input", control) : null;
				if (!input) return;
				const show = input.type === "password";
				input.type = show ? "text" : "password";
				button.setAttribute("aria-label", show ? t("Hide password", "إخفاء كلمة المرور") : t("Show password", "إظهار كلمة المرور"));
				button.textContent = show ? "🙈" : "👁";
			});
		});
	}

	function initPasswordMeter() {
		const inputs = [$("#signup-password")].concat($$("[data-password-meter]"));
		inputs.filter(Boolean).forEach(function (input) {
			const field = input.closest(".field");
			const meter = field ? $(".password-meter", field) : null;
			if (!meter) return;
			input.addEventListener("input", function () {
				const value = input.value || "";
				let score = 0;
				if (value.length >= 8) score += 1;
				if (value.length >= 12) score += 1;
				if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score += 1;
				if (/[0-9]/.test(value) && /[^A-Za-z0-9]/.test(value)) score += 1;
				meter.setAttribute("data-score", String(Math.min(score, 4)));
			});
		});
	}

	/* ----------------------------------------------------------------------
	   Sign in
	   ---------------------------------------------------------------------- */
	function initlogin() {
		const form = $("#login-form");
		if (!form) return;
		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);
			const usr = (form.usr.value || "").trim();
			const pwd = form.pwd.value || "";
			if (!usr || !pwd) {
				showError(form, t("Please enter your email or username and password.", "يرجى إدخال البريد الإلكتروني أو اسم المستخدم وكلمة المرور."));
				return;
			}
			const button = $('button[type="submit"]', form);
			setLoading(button, true);
			try {
				await call("login", { usr: usr, pwd: pwd });
				const redirect = form.getAttribute("data-redirect") || "/dashboard";
				window.location.href = redirect;
			} catch (error) {
				showError(form, error.message);
				setLoading(button, false);
			}
		});
	}

	/* ----------------------------------------------------------------------
	   Forgot password (login#forgot) & update password
	   ---------------------------------------------------------------------- */
	function initAuthPanes() {
		const forgot = $('[data-pane="forgot"]');
		if (!forgot || !forgot.parentElement) return;
		const wrap = forgot.parentElement;

		function apply() {
			const active = window.location.hash === "#forgot";
			forgot.hidden = !active;
			wrap.setAttribute("data-pane-active", active ? "forgot" : "");
			if (active) {
				const input = $("#forgot-form input", forgot);
				if (input) {
					try { input.focus({ preventScroll: true }); } catch (e) { input.focus(); }
				}
			}
		}

		window.addEventListener("hashchange", apply);
		apply();
	}

	function initForgot() {
		const form = $("#forgot-form");
		if (!form) return;
		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);
			const email = (form.usr.value || "").trim();
			if (!email) {
				showError(form, t("Please enter your email address.", "يرجى إدخال عنوان بريدك الإلكتروني."));
				return;
			}
			const button = $('button[type="submit"]', form);
			setLoading(button, true);
			try {
				const data = await callFull("frappe.core.doctype.user.user.reset_password", { user: email });
				const message = serverMessage(data) || t(
					"If this email is registered with us, we have sent password reset instructions to it. Please check your inbox.",
					"إذا كان هذا البريد مسجلاً لدينا، فأرسلنا تعليمات إعادة تعيين كلمة المرور إليه. يرجى فتح صندوق الوارد."
				);
				const box = $("[data-forgot-message]");
				if (box) box.textContent = message;
				form.hidden = true;
				const success = $("[data-forgot-success]");
				if (success) success.hidden = false;
			} catch (error) {
				showError(form, error.message);
				setLoading(button, false);
			}
		});
	}

	function initUpdatePassword() {
		const form = $("#update-password-form");
		if (!form) return;
		const key = form.getAttribute("data-key") || "";

		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);
			const oldPassword = form.old_password ? form.old_password.value || "" : "";
			const newPassword = form.new_password.value || "";
			const confirmPassword = form.confirm_password.value || "";

			if (!key && !oldPassword) return showError(form, t("Please enter your current password.", "يرجى إدخال كلمة مرورك الحالية."));
			if (!newPassword) return showError(form, t("Please enter your new password.", "يرجى إدخال كلمة مرورك الجديدة."));
			if (newPassword.length < 8) return showError(form, t("Password must be at least 8 characters long.", "يجب أن تكون كلمة المرور 8 أحرف على الأقل."));
			if (!key && oldPassword && newPassword === oldPassword) {
				return showError(form, t("The new password cannot be the same as your current password.", "لا يمكن أن تكون كلمة المرور الجديدة نفس الحالية."));
			}
			if (newPassword !== confirmPassword) return showError(form, t("The passwords do not match.", "كلمتا المرور غير متطابقتين."));

			const button = $('button[type="submit"]', form);
			setLoading(button, true);
			try {
				const result = await call("frappe.core.doctype.user.user.update_password", {
					key: key || "",
					old_password: oldPassword,
					new_password: newPassword,
					confirm_password: confirmPassword,
					logout_all_sessions: 1
				});
				form.hidden = true;
				const success = $("[data-update-success]");
				if (success) success.hidden = false;
				let target = typeof result === "string" ? result.trim() : "";
				if (!target || target === "/") {
					target = form.getAttribute("data-fallback") || "/dashboard";
				}
				window.setTimeout(function () { window.location.href = target; }, 1800);
			} catch (error) {
				showError(form, error.message);
				setLoading(button, false);
			}
		});
	}

	/* ----------------------------------------------------------------------
	   Sign up
	   ---------------------------------------------------------------------- */
	function initSignup() {
		const form = $("#signup-form");
		if (!form) return;

		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);

			const data = {
				full_name: (form.full_name.value || "").trim(),
				email: (form.email.value || "").trim(),
				company_name: (form.company_name.value || "").trim(),
				password: form.password.value || "",
				username: (form.username.value || "").trim(),
				phone: (form.phone.value || "").trim(),
				country: form.country.value || "",
				language: form.language.value || (isArabic() ? "ar" : "en"),
				redirect: "/plans",
			};

			if (!data.full_name) return showError(form, t("Please enter your full name.", "يرجى إدخال اسمك الكامل."));
			if (!data.email) return showError(form, t("Please enter your work email.", "يرجى إدخال بريد العمل."));
			if (!data.company_name) return showError(form, t("Please enter your company name.", "يرجى إدخال اسم الشركة."));
			if (data.password.length < 8) return showError(form, t("Password must be at least 8 characters long.", "يجب أن تكون كلمة المرور 8 أحرف على الأقل."));
			if (data.password !== form.confirm_password.value) return showError(form, t("The passwords do not match.", "كلمتا المرور غير متطابقتين."));
			if (!form.terms.checked) return showError(form, t("Please accept the Terms of Service and Privacy Policy.", "يرجى قبول شروط الخدمة وسياسة الخصوصية."));

			const button = $('button[type="submit"]', form);
			setLoading(button, true);
			try {
				const result = await call("saaserpyemen.api.signup", data);
				const plan = form.getAttribute("data-plan") || "";
				const cycle = form.getAttribute("data-cycle") || "Monthly";
				const currency = form.getAttribute("data-currency") || "";
				let target = (result && result.redirect) || "/plans";
				if (plan && target.indexOf("plan=") === -1) {
					const params = new URLSearchParams({ plan: plan, cycle: cycle, currency: currency });
					target = "/subscribe?" + params.toString();
				}
				window.location.href = target;
			} catch (error) {
				showError(form, error.message);
				setLoading(button, false);
			}
		});
	}

	/* ----------------------------------------------------------------------
	   Subscribe / choose workspace
	   ---------------------------------------------------------------------- */
	function initSubscribe() {
		const form = $("#subscribe-form");
		if (!form) return;

		const amountEl = $("[data-price-amount]");
		const currencyEl = $("[data-price-currency]");
		const summaryEl = $("[data-summary-amount]");

		function currentCurrencyButton() {
			return $(".currency-switch__item.active", form.closest(".subscribe") || document);
		}

		function refreshPrice() {
			const currencyButton = currentCurrencyButton();
			if (!currencyButton) return;
			const cycle = form.getAttribute("data-cycle") || "Monthly";
			const amount = cycle === "Yearly" ? currencyButton.getAttribute("data-yearly") : currencyButton.getAttribute("data-monthly");
			const currency = currencyButton.getAttribute("data-currency") || currencyButton.textContent.trim();
			if (amountEl) amountEl.textContent = formatAmount(amount);
			if (currencyEl) currencyEl.textContent = currency;
			if (summaryEl) summaryEl.textContent = currency + " " + formatAmount(amount);
		}

		$$("[data-cycle]").forEach(function (button) {
			button.addEventListener("click", function () {
				$$("[data-cycle]", document).forEach(function (item) { item.classList.remove("active"); });
				button.classList.add("active");
				form.setAttribute("data-cycle", button.getAttribute("data-cycle"));
				refreshPrice();
			});
		});

		$$(".currency-switch__item[data-currency]").forEach(function (button) {
			button.addEventListener("click", function () {
				$$(".currency-switch__item[data-currency]", document).forEach(function (item) { item.classList.remove("active"); });
				button.classList.add("active");
				form.setAttribute("data-currency", button.getAttribute("data-currency"));
				refreshPrice();
			});
		});

		document.addEventListener("saas:language", refreshPrice);

		// Live subdomain availability
		const input = $("#subdomain-input");
		const status = $("#subdomain-status");
		const control = input ? input.closest(".field__control") : null;
		let timer = null;
		let lastChecked = "";

		function setStatus(kind, message) {
			if (!control || !status) return;
			control.classList.remove("is-available", "is-taken", "is-checking");
			if (kind) control.classList.add("is-" + kind);
			status.textContent = message || "";
		}

		function checkSubdomain() {
			if (!input || !control) return;
			const value = normalizeSubdomain(input.value);
			input.value = value;
			if (!value) { setStatus("", ""); return; }
			if (value.length < 3) {
				setStatus("taken", t("Too short", "قصير جدًا"));
				return;
			}
			if (value === lastChecked) return;
			lastChecked = value;
			setStatus("checking", t("Checking…", "جارٍ التحقق…"));
			call("saaserpyemen.api.check_subdomain", { subdomain: value })
				.then(function (result) {
					if (!result) return;
					if (result.available) {
						setStatus("available", t("✓ Available", "✓ متاح"));
					} else {
						setStatus("taken", t("✕ Unavailable", "✕ غير متاح"));
					}
				})
				.catch(function () {
					setStatus("", "");
				});
		}

		if (input) {
			input.addEventListener("input", function () {
				const normalized = normalizeSubdomain(input.value);
				if (normalized !== input.value) input.value = normalized;
				lastChecked = "";
				window.clearTimeout(timer);
				timer = window.setTimeout(checkSubdomain, 450);
			});
			input.addEventListener("blur", checkSubdomain);
		}

		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);

			const isChange = form.getAttribute("data-is-change") === "1";
			const data = {
				plan: form.getAttribute("data-plan") || "",
				billing_cycle: form.getAttribute("data-cycle") || "Monthly",
				currency: form.getAttribute("data-currency") || "USD",
				company_name: (form.company_name && form.company_name.value || "").trim(),
				phone: (form.phone && form.phone.value || "").trim(),
				country: form.country ? form.country.value : "",
				language: form.language ? form.language.value : (isArabic() ? "ar" : "en"),
				existing_tenant: form.getAttribute("data-existing-tenant") || "",
			};

			if (!isChange) {
				const subdomain = normalizeSubdomain(input ? input.value : "");
				if (!subdomain) return showError(form, t("Please choose a workspace address.", "يرجى اختيار عنوان مساحة العمل."));
				if (!/^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])?$/.test(subdomain)) {
					return showError(form, t("Use lowercase letters, numbers and hyphens only. It must start and end with a letter or number.", "استخدم أحرفًا صغيرة وأرقامًا وشرطات فقط. يجب أن يبدأ وينتهي بحرف أو رقم."));
				}
				data.subdomain = subdomain;
				if (!data.company_name) return showError(form, t("Please enter your company or workspace name.", "يرجى إدخال اسم الشركة أو مساحة العمل."));
			}

			if (form.terms && !form.terms.checked) {
				return showError(form, t("Please accept the Terms of Service and Privacy Policy.", "يرجى قبول شروط الخدمة وسياسة الخصوصية."));
			}

			const button = $('button[type="submit"]', form);
			setLoading(button, true);
			try {
				const result = await call("saaserpyemen.api.create_subscription", data);
				const target = (result && result.redirect) || (isChange ? "/dashboard?tab=billing" : "/dashboard");
				window.location.href = target;
			} catch (error) {
				showError(form, error.message);
				setLoading(button, false);
			}
		});
	}

	/* ----------------------------------------------------------------------
	   Customer dashboard: profile, reveal password, cancel subscription
	   ---------------------------------------------------------------------- */
	function initDashboard() {
		const profile = $("[data-profile-form]");
		if (profile) {
			profile.addEventListener("submit", async function (event) {
				event.preventDefault();
				clearError(profile);
				const button = $('button[type="submit"]', profile);
				setLoading(button, true);
				try {
					await call("saaserpyemen.api.update_profile", {
						tenant: profile.getAttribute("data-tenant"),
						company_name: (profile.company_name.value || "").trim(),
						phone: (profile.phone.value || "").trim(),
						country: profile.country.value || "",
						language: profile.language.value || "en",
					});
					toast(t("Your profile has been updated.", "تم تحديث ملفك بنجاح."), "success");
				} catch (error) {
					showError(profile, error.message);
				} finally {
					setLoading(button, false);
				}
			});
		}

		const cancel = $("[data-cancel-subscription]");
		if (cancel) {
			cancel.addEventListener("click", async function () {
				const isPending = cancel.getAttribute("data-pending") === "1";
				const confirmed = await confirmDialog({
					title: isPending
						? t("Cancel this workspace?", "إلغاء مساحة العمل؟")
						: t("Cancel auto-renewal?", "إلغاء التجديد التلقائي؟"),
					message: isPending
						? t(
							"This workspace has not been activated yet. Cancelling it will close this request and it cannot be paid for later.",
							"لم يتم تفعيل مساحة العمل هذه بعد. سيؤدي إلغاؤها إلى إغلاق هذا الطلب ولن يمكن الدفع مقابلها لاحقًا."
						)
						: t(
							"Your workspace will stay active until the end of the current paid period. You can re-enable auto-renewal by making a new payment.",
							"ستبقى مساحة عملك نشطة حتى نهاية الفترة المدفوعة الحالية. يمكنك إعادة تفعيل التجديد التلقائي بإجراء دفعة جديدة."
						),
					confirmText: isPending
						? t("Cancel workspace", "إلغاء مساحة العمل")
						: t("Cancel renewal", "إلغاء التجديد"),
					cancelText: t("Keep it", "الإبقاء عليه"),
				});
				if (!confirmed) return;
				cancel.disabled = true;
				try {
					const result = await call("saaserpyemen.api.cancel_subscription", {
						tenant: cancel.getAttribute("data-tenant"),
					});
					toast((result && result.message) || t("Auto-renewal cancelled.", "تم إلغاء التجديد التلقائي."), "success");
					window.setTimeout(function () { window.location.reload(); }, 900);
				} catch (error) {
					toast(error.message, "error");
					cancel.disabled = false;
				}
			});
		}
	}

	function initRevealPassword() {
		$$("[data-reveal-password]").forEach(function (button) {
			button.addEventListener("click", async function () {
				const container = button.closest(".credentials, .provision__credentials, .credential-row, .panel") || document;
				const secret = $("[data-secret]", container);
				if (!secret) return;

				if (button.getAttribute("data-revealed") === "1" && button.dataset.password) {
					secret.textContent = "••••••••••••";
					button.setAttribute("data-revealed", "0");
					setBilingual(button, "Reveal", "إظهار");
					return;
				}

				const original = button.textContent;
				button.disabled = true;
				button.textContent = t("Loading…", "جارٍ التحميل…");
				try {
					const result = await call("saaserpyemen.api.get_tenant_credentials", {
						tenant: button.getAttribute("data-tenant"),
					});
					const password = (result && result.password) || "";
					if (!password) {
						toast(t("No password is available. Please reset it from your ERP.", "لا تتوفر كلمة مرور. يرجى إعادة تعيينها من نظام ERP."), "error");
						button.textContent = original;
						return;
					}
					secret.textContent = password;
					button.dataset.password = password;
					button.setAttribute("data-revealed", "1");
					setBilingual(button, "Hide", "إخفاء");
				} catch (error) {
					toast(error.message, "error");
					button.textContent = original;
				} finally {
					button.disabled = false;
				}
			});
		});
	}

	/* ----------------------------------------------------------------------
	   Manual payment
	   ---------------------------------------------------------------------- */
	function initPayment() {
		const form = $("[data-payment-form]");
		if (!form) return;

		const zone = $("[data-upload-zone]", form);
		const input = $("[data-upload-input]", form);
		const fileName = $("[data-upload-file]", form);
		const submit = $('button[type="submit"]', form);
		const monthsSelect = $("[data-months-select]", form);
		const totalAmountEls = $$("[data-total-amount]");
		const periodEls = $$("[data-period-range]");
		const durationEls = $$("[data-duration-label]");
		let receiptUrl = "";
		let uploading = false;

		function updateSelection() {
			if (!monthsSelect) return;
			const option = monthsSelect.options[monthsSelect.selectedIndex];
			if (!option) return;
			const amount = option.getAttribute("data-amount") || "";
			const period = option.getAttribute("data-period") || "";
			const label = option.getAttribute("data-label") || "";
			totalAmountEls.forEach(function (el) { el.textContent = amount; });
			periodEls.forEach(function (el) { el.textContent = period; });
			durationEls.forEach(function (el) { el.textContent = label; });
		}

		if (monthsSelect) {
			monthsSelect.addEventListener("change", updateSelection);
			updateSelection();
		}

		function setFileLabel(name, ok) {
			if (!fileName) return;
			fileName.hidden = !name;
			fileName.textContent = name || "";
			if (zone) zone.classList.toggle("is-selected", !!ok);
		}

		async function handleFile(file) {
			if (!file) return;
			const allowed = ["image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"];
			if (allowed.indexOf(file.type) === -1) {
				toast(t("Please upload a PDF, JPG or PNG file.", "يرجى رفع ملف PDF أو JPG أو PNG."), "error");
				return;
			}
			if (file.size > 10 * 1024 * 1024) {
				toast(t("The file is larger than 10 MB.", "حجم الملف أكبر من 10 ميجابايت."), "error");
				return;
			}
			uploading = true;
			setFileLabel(t("Uploading…", "جارٍ الرفع…"), false);
			setLoading(submit, true);
			try {
				const result = await uploadFile(file, true);
				receiptUrl = result.file_url || "";
				setFileLabel(file.name, true);
				toast(t("Receipt uploaded.", "تم رفع الإيصال."), "success");
			} catch (error) {
				receiptUrl = "";
				setFileLabel("", false);
				toast(error.message, "error");
			} finally {
				uploading = false;
				setLoading(submit, false);
			}
		}

		if (input) {
			input.addEventListener("change", function () { handleFile(input.files && input.files[0]); });
		}

		if (zone) {
			["dragenter", "dragover"].forEach(function (name) {
				zone.addEventListener(name, function (event) {
					event.preventDefault();
					zone.classList.add("is-dragover");
				});
			});
			["dragleave", "drop"].forEach(function (name) {
				zone.addEventListener(name, function (event) {
					event.preventDefault();
					zone.classList.remove("is-dragover");
				});
			});
			zone.addEventListener("drop", function (event) {
				const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
				if (file) handleFile(file);
			});
		}

		form.addEventListener("submit", async function (event) {
			event.preventDefault();
			clearError(form);
			if (uploading) {
				toast(t("Please wait for the receipt to finish uploading.", "يرجى الانتظار حتى ينتهي رفع الإيصال."), "info");
				return;
			}
			const reference = (form.reference_no.value || "").trim();
			if (!reference && !receiptUrl) {
				showError(form, t("Please enter the transfer reference or upload your payment receipt.", "يرجى إدخال مرجع التحويل أو رفع إيصال الدفع."));
				return;
			}

			setLoading(submit, true);
			try {
				const result = await call("saaserpyemen.api.submit_payment", {
					tenant: form.getAttribute("data-tenant"),
					invoice: form.getAttribute("data-invoice") || undefined,
					months: monthsSelect ? monthsSelect.value : undefined,
					reference_no: reference,
					payment_method: form.payment_method.value || "Bank Transfer",
					notes: (form.notes.value || "").trim(),
					receipt: receiptUrl,
				});
				toast((result && result.message) || t("Payment submitted for review.", "تم إرسال الدفعة للمراجعة."), "success");
				window.setTimeout(function () { window.location.reload(); }, 1000);
			} catch (error) {
				showError(form, error.message);
				setLoading(submit, false);
			}
		});
	}

	/* ----------------------------------------------------------------------
	   Provisioning progress
	   ---------------------------------------------------------------------- */
	function initProvisioning() {
		const app = $("#provisioning-app");
		if (!app) return;

		const tenant = app.getAttribute("data-tenant");
		const logEl = $("[data-log]", app);
		const toggle = $("[data-log-toggle]", app);

		if (toggle && logEl) {
			toggle.addEventListener("click", function () {
				const open = logEl.classList.toggle("open");
				toggle.classList.toggle("open", open);
			});
		}

		const completed = !!$(".provision__orb.done", app);
		const failed = !!$(".provision__orb.failed", app);
		if (completed || failed || !tenant) return;

		let attempts = 0;
		let stopped = false;

		async function poll() {
			if (stopped) return;
			attempts += 1;
			try {
				const result = await call("saaserpyemen.api.get_provisioning_status", { tenant: tenant });
				if (logEl && result && result.log) {
					logEl.textContent = result.log;
					logEl.scrollTop = logEl.scrollHeight;
				}
				if (result && (result.completed || result.failed)) {
					stopped = true;
					window.setTimeout(function () { window.location.reload(); }, 900);
					return;
				}
			} catch (error) {
				// Keep polling through transient errors; stop after ~3 minutes.
			}
			if (attempts < 45) {
				window.setTimeout(poll, 4000);
			}
		}

		window.setTimeout(poll, 2500);
	}

	/* ----------------------------------------------------------------------
	   Init
	   ---------------------------------------------------------------------- */
	function init() {
		initLanguage();
		initNavigation();
		initLogout();
		initPasswordToggles();
		initPasswordMeter();
		initlogin();
		initAuthPanes();
		initForgot();
		initUpdatePassword();
		initSignup();
		initSubscribe();
		initDashboard();
		initRevealPassword();
		initPayment();
		initProvisioning();
	}

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();
