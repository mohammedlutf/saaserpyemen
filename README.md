### Saaserpyemen

Turn ERPNext 15 into a multi-tenant SaaS platform.

- Bilingual (Arabic / English, RTL) marketing site, plans, signup and manual
  payment flow.
- Google and username/password authentication on the central site.
- Customer control panel: plan, usage, subscription dates, payments, workspace
  credentials and subdomain.
- Automatic tenant provisioning: each customer gets an isolated ERPNext site
  (`<subdomain>.shopzadmarket.com`) cloned from `saas-default.com`, with its own
  database, files, Company, chart of accounts and System Manager user.
- Plan limits (users, branches, companies, storage), suspension, usage snapshots
  and scheduled lifecycle jobs.
- Manual billing with receipt upload, admin approval/rejection, subscription
  extension and optional ERPNext Sales Invoices.
- Desk workspace and dashboard for managing plans, tenants, payments and
  provisioning logs.

### Documentation

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for installation, wildcard DNS/SSL,
nginx, `dns_multitenant`, template-site requirements and the production
checklist.

### Installation

```bash
cd /home/frappe/frappe-bench
bench get-app /path/to/saaserpyemen
bench --site shopzadmarket.com install-app saaserpyemen
bench --site shopzadmarket.com migrate
```

Then configure **SaaS Settings** in Desk. The first migrate seeds four plans
(Starter, Growth, Business, Enterprise), the `SaaS Manager` and `SaaS Customer`
roles, the SaaS workspace and the default settings.

### License

mit
