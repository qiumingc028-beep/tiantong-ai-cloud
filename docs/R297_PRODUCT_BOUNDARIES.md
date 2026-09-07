# R297 candidate boundaries (release remains BLOCK)

Backend, Worker, Runtime and Runtime Nginx must be upgraded together. This is a
candidate contract, not evidence of real JD acceptance.

## Owner grant and Viewer lifetime

The four Owner operations retain the existing durable PENDING/receipt saga.
Runtime binds a session to the create operation ID, and sends that ID separately
from the unchanged five-field scope to Backend authorization. Backend checks the
original Owner's active role, write membership, tenant, company and store. Legacy
sessions without this grant are rejected. A new create grant replaces old Viewer
authority. Unknown authorization results fail closed after a five-second request
timeout. Active sessions are rechecked every 30 seconds and on access; revocation
therefore has a bounded polling delay, not synchronous database notification.
Runtime owns upgraded Viewer sockets, closes them on revocation/expiry and does
not forward browser cookies to websockify. Existing operation receipts, recovery
claims and manual recovery fencing remain unchanged.

## Credential destinations and deployment identity

Capture/control requests use only
`http://jd-browser-runtime:8787/internal/jd-browser`; Runtime authorization uses
only `http://backend:8000/api/jd-workbench/internal/browser-session-authorize`.
Python transports disable environment proxies and HTTP redirects. Authorization
fetch rejects redirects. An explicitly enabled non-production controlled canary
may use `http://127.0.0.1:<port>` with the same fixed paths; production rejects it.

Production `JD_SESSION_NAMESPACE` must be `r297-` followed by 24 lowercase random
hex digits (96 bits). Generate it once per deployment with
`python -c 'import secrets; print("r297-" + secrets.token_hex(12))'`, provision the
same value to Backend/Worker/Runtime, and retain it across restart. Do not reuse a
namespace or clone the archive volume between independent deployments. Runtime
pins the identity in its existing archive volume and refuses a changed value.
The production Compose explicitly enables this check. Generic placeholders and
old non-conforming production identifiers require planned migration before use;
do not delete the pin to bypass it.

## Independent dataset schemas

Every numeric observation below is required; missing or null is not zero.
Integer count fields accept exact non-negative integers; decimal fields must
match database precision/scale. Booleans, non-finite values, extra fields,
invalid types and duplicate metric aliases fail the entire batch before writes.

| Dataset | Required fields | Optional fields |
| --- | --- | --- |
| metrics | gmv, profit_amount, visitors_count, paid_orders_count, ad_spend, roi, refunds_count, after_sales_count, favorites_count, cart_add_count, conversion_rate | none |
| orders | order_no, paid_amount, profit_amount | order_date, order_status |
| products | sku_id, stock_quantity, sales_amount, sales_quantity, visitors_count, conversion_rate | stat_date, product_name, category_name |
| ads | campaign_id, ad_spend, clicks, impressions, roi, cpa, deal_amount | campaign_name |

Metrics retain the existing aliases `today_sales→gmv`, `visitors→visitors_count`,
`orders→paid_orders_count`, `refunds→refunds_count`, `after_sales→after_sales_count`;
alias and canonical field cannot both appear. Optional dates use the requested
sync date, or the existing current-date batch default; supplied dates must be ISO
calendar dates. Optional text follows the existing empty-description behavior.
An adapter lacking a required observation must report collection failure, not
invent a value. Controlled fixtures contain explicit synthetic observations.

0054 and atomic business-key upsert are retained. Sequential/concurrent replays
update existing rows; saved counts distinct business keys in a batch, not inserts
or repeated rows. This does not certify the selectors against real JD pages.

## Open infrastructure evidence blockers

The integrated infrastructure source still has two review findings: a process
crash between hard-link publication and temporary-link cleanup can leave an
unrecoverable two-link body; and delayed 900/1800/3600-second policy observations
cannot fit the current five-minute signed-event freshness chain. These require
producer/recovery fixes from role ⑤. Do not relax link safety or evidence age
checks, or claim these long-cycle scenarios passed. Same-head full CI and
protected Process/Windows/real JD evidence remain separate release requirements.
