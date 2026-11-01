# Deployment guide

This app turns a Frappe/ERPNext bench into a multi-tenant SaaS platform:

- **Central site** (`shopzadmarket.com`) — bilingual marketing site, signup, plan
  selection, manual payments and the customer control panel. All tenants and
  subscriptions live here.
- **Tenant sites** (`<subdomain>.shopzadmarket.com`) — isolated ERPNext sites with
  their own database, files and users. Each one is cloned from the template site
  `saas-default.com`.

Tenant routing uses Frappe's native `dns_multitenant` feature, so no request
rewriting layer is required: nginx forwards the `Host` header and Frappe picks
the matching site folder.

---

## 1. Requirements

- Frappe bench v5 with ERPNext 15 (MariaDB, Redis, Node, wkhtmltopdf).
- Python 3.11+.
- Wildcard DNS: `*.shopzadmarket.com` → server IP (plus `shopzadmarket.com`).
- Wildcard TLS certificate for `*.shopzadmarket.com` (Let's Encrypt DNS-01 or a
  commercial certificate).
- The bench process user (`frappe`) must be able to run `bench` and write inside
  `sites/` (site creation, backups, nginx config).
- Database root (or equivalent) credentials for `bench new-site`.
- The template site `saas-default.com` already exists, is migrated, and contains
  the baseline ERPNext data you want every tenant to inherit.

---

## 2. Install the app

```bash
cd /home/frappe/frappe-bench
bench get-app /path/to/saaserpyemen        # or the git URL
bench --site shopzadmarket.com install-app saaserpyemen
bench --site shopzadmarket.com migrate
```

`after_install` / `after_migrate` create the roles, custom fields, four default
plans, the SaaS workspace, the Desk dashboard page and the default
`SaaS Settings` record.

After installing, open **SaaS Settings** in Desk and review every tab.

---

## 3. Enable multi-tenancy in the bench

`/home/frappe/frappe-bench/sites/common_site_config.json`:

```json
{
  "dns_multitenant": 1,
  "serve_default_site": false
}
```

Restart bench and nginx afterwards:

```bash
bench restart
sudo bench setup nginx
sudo nginx -t && sudo systemctl reload nginx
```

> Development note: `bench start` falls back to `default_site` for every host.
> Use real gunicorn/nginx (or a WSGI client) when testing tenant host routing.

---

## 4. Central site configuration

Open **SaaS Settings** and fill in:

### General
| Field | Value |
| --- | --- |
| Enabled | checked |
| Brand name / Arabic name | Shopzad / شوب زاد |
| Website domain | `shopzadmarket.com` |
| Central site | `shopzadmarket.com` |
| Default currency | `USD` |
| Default trial days | `30` |
| Grace days | e.g. `3` |

Currencies come from ERPNext **Currency** records with `enabled = 1`. Currently
enabled: `SAR`, `USD`, `YER`. Add more in Desk if needed; plan prices are seeded
per currency from the USD price and the ERPNext **Currency Exchange** rate.

### Website
Hero copy, footer, social links, testimonials/FAQ toggles and support contact
details. All copy has English and Arabic variants.

### Provisioning
| Field | Value |
| --- | --- |
| Template site | `saas-default.com` |
| Bench path | `/home/frappe/frappe-bench` |
| Sites path | `/home/frappe/frappe-bench/sites` |
| Bench command | `/usr/local/bin/bench` |
| Tenant site scheme | `https` (use `http` only for local testing) |
| DB root user | `root` |
| DB root password | your MariaDB root password |
| Install SaaS app on tenant | checked |
| Enable scheduler on tenant | checked |
| Run `bench setup nginx` | checked (production) |
| Add site to `/etc/hosts` | unchecked (production DNS) |
| Issue SSL certificate | optional (see §6) |
| Email workspace credentials | optional |
| Provisioning timeout | `1800` |

### Google login
1. Create an OAuth 2.0 Web client in Google Cloud Console.
2. Authorised redirect URI:
   `https://shopzadmarket.com/api/method/frappe.integrations.oauth2_logins.login_via_google`
3. Paste client ID / secret into **SaaS Settings → Google Login**, set the same
   redirect URI, enable **Enable Google Login** (and **Allow Google Signup** if
   desired), then save.
4. Saving syncs a **Social Login Key** named `google`. Verify it exists and is
   enabled. Google login is only offered on the central site; tenant sites keep
   the standard Frappe login.

### Billing
Select the **Company**, customer group, territory, invoice due days and whether
approved payments should create a Sales Invoice automatically. A hidden
`SaaS Service Item` flag on `Item` is used to reuse the subscription item
(`SAAS-SUBSCRIPTION`, or the first item flagged as the service item).

Replace the default **Bank Details** (English and Arabic) with the real account
information customers should use; the payment page renders them as HTML.

---

## 5. DNS, nginx and TLS

Wildcard DNS record:

```
A     shopzadmarket.com          <server-ip>
A     *.shopzadmarket.com        <server-ip>
```

Wildcard certificate (example with certbot DNS-01):

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d shopzadmarket.com -d '*.shopzadmarket.com'
```

Install the certificate on the central site:

```bash
bench --site shopzadmarket.com set-config ssl_certificate /etc/letsencrypt/live/shopzadmarket.com/fullchain.pem
bench --site shopzadmarket.com set-config ssl_certificate_key /etc/letsencrypt/live/shopzadmarket.com/privkey.pem
```

`bench setup nginx` regenerates the site's nginx config from
`site_config.json`. Because the wildcard certificate covers every subdomain,
new tenant sites do **not** need their own certificate. Disable **Issue SSL
Certificate** unless you really want per-site certificates; `enqueue_ssl`
exists for that case and uses `bench --site <site> ...` with certbot.

Reload after changes:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. Template site

`saas-default.com` is the source of every tenant. Keep it lean, and install the
lightweight tenant app on it once so every clone inherits it:

```bash
bench --site saas-default.com install-app saas_client
bench --site saas-default.com migrate
bench --site saas-default.com backup      # verify a backup works
```

`saas_client` is the only app that runs inside a tenant. It enforces plan
limits, guards suspended sites and performs the first-run tenant setup. The
full `saaserpyemen` platform app stays on the central site only.

Provisioning does the following for every tenant:

1. `bench --site saas-default.com backup` → fresh DB dump.
2. `bench new-site <subdomain>.shopzadmarket.com --source-sql <dump> ...`.
3. Copy `public/files` and `private/files` from the template.
4. Write tenant flags to `site_config.json` (`saas_tenant`, `saas_plan`,
   `saas_max_users`, `saas_max_branches`, `saas_max_companies`,
   `saas_storage_gb`, `host_name`, `pause_scheduler`).
5. Ensure `saas_client` is installed (and remove any legacy `saaserpyemen`
   installation from the tenant).
6. `bench --site <site> execute saas_client.setup.setup_tenant_site ...`
   — creates the Company + chart of accounts, Transit warehouse, currency,
   country, Global Defaults and the customer's System Manager user.
7. `bench set-admin-password` with a unique per-tenant password.

> **Encryption key:** passwords stored in the template database were encrypted
> with the template's `encryption_key`. If the template has one, it is copied to
> the tenant. If not, each tenant gets a new key and previously stored passwords
> (e.g. email account passwords) cannot be decrypted — re-enter them in the
> tenant.

---

## 7. Background jobs

The central scheduler must be enabled:

```bash
bench --site shopzadmarket.com enable-scheduler
```

Daily: mark past-due subscriptions, expire subscriptions, send expiry reminders,
sync usage snapshots, clean old logs.

Weekly: sync usage for every tenant.

Monthly: prune logs older than two years.

Provisioning, SSL and email delivery run as background jobs on the central site;
watch **SaaS Provisioning Log** for failures.

---

## 8. Manual billing workflow

1. Customer opens **Dashboard → Payment**, uploads a receipt or enters a transfer
   reference, and submits. A `SaaS Payment` is created with status
   `Pending Review`; the subscription shows `Pending Review`.
2. Admin reviews the payment in Desk (**SaaS Payment**) or via
   `saaserpyemen.api.approve_payment`.
3. Approval extends the subscription by one month/year, sets the tenant to
   `Active`, optionally creates a Sales Invoice, and pushes limits to the tenant
   site.
4. Rejection marks the payment `Rejected`; a still-valid paid period stays
   `Paid`, otherwise the subscription falls back to `Unpaid`.

Prices are always recalculated server-side from the plan and enabled currency;
the client cannot submit an arbitrary amount.

---

## 9. Tenant isolation and suspension

Every tenant site redirects `/` and all marketing routes to `/app` via
`before_request`; only `/app`, `/login`, `/logout`, `/api`, assets, files,
`/.well-known` and similar paths are allowed.

Limits are enforced inside the tenant by the `saas_client` app's `doc_events`:

- `max_users` — blocks creating users beyond the plan (including re-enabling a
  disabled user or converting a Website User into a desk user).
- `max_branches` / `max_companies` — blocks extra Branch/Company records.
- `storage_gb` — blocks new File uploads when the workspace storage is full.

The central site still reports usage and sends limit notifications through its
scheduled jobs.

Suspension sets `saas_suspended` in the tenant's `site_config.json`; the guard
then redirects users to `/suspended` on the central site. Unsuspending clears it.

---

## 10. Backups and upgrades

Back up the central site and every tenant database:

```bash
bench --site shopzadmarket.com backup --with-files
# tenants
for s in $(ls sites | grep '\.shopzadmarket\.com$'); do
  bench --site "$s" backup --with-files
done
```

Upgrade flow:

```bash
bench update --apps saaserpyemen
bench --site shopzadmarket.com migrate
for s in $(ls sites | grep '\.shopzadmarket\.com$'); do
  bench --site "$s" migrate
done
bench restart
```

---

## 11. Security checklist

- [ ] Change the MariaDB root password and update **SaaS Settings**.
- [ ] Use HTTPS everywhere (`site_scheme = https`, HSTS at nginx).
- [ ] Keep `developer_mode = 0` in production.
- [ ] Restrict Desk access to `SaaS Manager` / `System Manager` only.
- [ ] Rotate the template `encryption_key` policy deliberately; do not commit it.
- [ ] Store the template dump directory on encrypted storage; delete old dumps.
- [ ] Limit `bench` shell access to the `frappe` user.
- [ ] Monitor `SaaS Provisioning Log`, `Error Log` and disk usage.
- [ ] Keep the wildcard certificate renewal automated.

---

## 12. Troubleshooting

| Symptom | Check |
| --- | --- |
| Tenant shows central marketing pages | `dns_multitenant` is 0, or nginx `Host` header lost |
| `bench new-site` fails | DB root password, disk space, template backup path |
| Provisioning stuck in `Running` | `SaaS Provisioning Log`, `bench --site shopzadmarket.com execute saaserpyemen.provisioning.provision_tenant --args '["TENANT"]'` |
| Tenant redirects everything to `/app` | expected; only `/app`, `/login`, `/api`, assets are allowed |
| Google login redirect mismatch | redirect URI must match exactly and use the central domain |
| Invoice creation fails | Company, customer group, territory, currency exchange rate and service item |
| Payment approval does not reactivate tenant | subscription `end_date`, tenant `status`, provisioning log |

Useful commands:

```bash
bench --site shopzadmarket.com execute saaserpyemen.api.get_admin_dashboard
bench --site shopzadmarket.com execute saaserpyemen.tenant_ops.sync_usage
bench --site shopzadmarket.com execute saaserpyemen.provisioning.provision_tenant --args '["TENANT"]'
```

---

## 13. Local development notes

- Set **Tenant site scheme** to `http` while testing locally, and switch back to
  `https` before go-live.
- `bench start` forces `default_site` for every `Host` header, so tenant
  subdomains will resolve to the central site. Test tenant routing with a WSGI
  client (setting `HTTP_HOST`) or a real gunicorn/nginx setup.
- The dev server's port (`8000`) is not part of tenant URLs; provisioning only
  needs the site folder, DNS and nginx in production.
- When the template has no `encryption_key`, each tenant gets a new one and
  template-stored encrypted values (e.g. email account passwords) must be
  re-entered inside the tenant.

