# Marta first-tenant staged acceptance

Technical automation passed on 2026-07-18. Human approval remains pending;
additional paying tenants must stay disabled until every applicable item below
is completed and the approver/date is recorded.

The live 2026-07-19 audit is recorded in
`docs/phase-12-marta-launch-acceptance.md`. It does not replace Marta's human
approval.

## Automated read-only gate

Run:

```bash
python manage.py verify_saas_rollout --expect-marta
python manage.py verify_app_extraction --strict --expect-marta
```

The first command protects Marta's historical minimums and verifies current
customer/card/Wallet relations, encrypted credential presence and tenant
isolation while allowing legitimate registrations and token refreshes to grow
the append-only aggregates. It resolves the marketing, registration, portal and
operations routes. It never creates a lead, enrollment, quote, print request,
provider job or external call.

## Human acceptance checklist

- [ ] Marta confirms the public brand name, legal/billing name and contact data.
- [ ] Marta signs in and confirms access only to Atelier-Café data.
- [ ] Marta reviews the published card proof on desktop and mobile.
- [ ] Marta confirms Dotykačka connects to Cloud ID `350830718` without exposing
  the Refresh Token.
- [ ] The platform operator runs the explicit Brevo tenant-connection test and
  confirms it passes without exposing the tenant API key.
- [ ] Marta confirms one controlled test enrollment using an explicitly approved
  unused card and test contact details.
- [ ] Marta confirms Wallet/email content and the follow-up status screen.
- [ ] Marta reviews an explicitly approved test quote/print request without
  production fulfillment unless separately requested.
- [ ] Platform operator records the acceptance date and approver outside secrets
  and customer data.

Additional paying tenants remain disabled until this human checklist is signed.
The technical Phase 11 implementation must not fabricate that approval.
