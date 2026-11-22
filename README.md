# Visit Nigeria Customer Care

Odoo 20 module (`vn_care`) that gives the Customer Care team one dashboard for
every enquiry and service request submitted on VisitNigeria.io. It runs on its
own Odoo instance: care users log in to Odoo only and have no access to the
website administration backend.

Built and tested on Odoo 20.0 Community with PostgreSQL 16. It depends on the
`mail` module only, so it needs no Enterprise licence.

## What it does

| Requirement | Where it is |
| --- | --- |
| Central inbox for every service category | *Customer Care > Enquiries*. Categories are records: a code the website sends for the first time creates its category, flagged "To Review". |
| Overview on login | *Customer Care > Overview*: total, outstanding, to assign, overdue follow-ups, one counter per status, breakdown by category and by agent. Each figure opens the list behind it. |
| Enquiry record | Customer, contact details, category, request, category-specific fields, dates, reference (`VN-ENQ-000001`), status, agent, and the full history of emails, notes, changes and follow-ups. |
| Statuses | New, Assigned, In Progress, Awaiting Customer, Awaiting Partner, Resolved, Closed. Assigning moves New to Assigned; a customer reply moves the enquiry back to In Progress and reopens a resolved or closed one; resolved enquiries close by themselves after a set number of days. |
| Assignment | Managers assign and reassign from the form, in bulk from the list, or by dragging cards in *Team > Workload*. |
| Customer communication | "Send message" on the enquiry emails the customer; replies come back onto the same enquiry. A receipt with the reference number is sent automatically. Three reply templates are included. |
| Search and filters | By customer name, email, reference, category, status, agent and date received, with saved filters and grouping. |
| Real time | New enquiries and changes appear in the overview, the list and the kanban without refreshing the page. |
| Notifications | Managers for each new enquiry, the agent on assignment and on each customer reply. |
| Reports | *Customer Care > Reports*: by category, booking conversion, outstanding requests, response and resolution times, agent performance. All export to Excel. |
| Access levels | Customer Care Agent, Customer Care Manager, Super Admin / Management (see below). |
| Staff management | *Team > Members* and *Add Member*: Management adds people, changes their level and deactivates them, without holding Odoo administrator rights. |
| Website synchronisation | Authenticated API in, signed webhook out, nightly reconciliation. |

The module records whether an enquiry became a booking and the partner's
booking reference. It takes no bookings and no payments: those stay with the
service partners.

## Service categories

The starting categories mirror VisitNigeria.io as it stood on 22 November 2026:

- the request types of its request form: flight booking support, hotel booking
  support, visa support, eSIM setup help, concierge request, event ticket sales
  request, car rental support, partner inquiry, insurance, packages, package request;
- its two other request forms: apartment enquiry and Trip Builder request;
- the services bought on the site, for after-sales questions: medical services,
  currency and travel card, shop;
- the topics of its contact form: general questions, partnerships, media and
  press, Nigerians abroad, website or account help.

Management edits the list under *Configuration > Service Categories*.

## Access levels

| Level | Sees | Can do |
| --- | --- | --- |
| Customer Care Agent | Enquiries assigned to them | Reply, add notes, update status, record follow-ups and outcome |
| Customer Care Manager | Every enquiry | The above, plus assign, reassign and monitor the team |
| Super Admin / Management | Everything | The above, plus reports, exports, categories and staff management |

The agent restriction is an access rule on the data, so it also applies to
search, export and reports. Odoo settings and technical menus stay with the
technical administrator account.

Optional: *Settings > Customer Care > Agents Pick Up Unassigned Enquiries* lets
agents see unassigned enquiries and take one for themselves.

## Installation

1. Put the `vn_care` folder in the addons path of an Odoo 20 server.
2. Update the apps list and install **Visit Nigeria Customer Care**.
3. Configure the outgoing mail server and the incoming mail (alias domain and
   catch-all) so that emails leave from the customer care address and replies
   are routed back to their enquiry.
4. Open *Customer Care > Configuration > Settings* (technical administrator).

Run the tests:

```
odoo-bin -d <database> -i vn_care --test-tags /vn_care --stop-after-init
```

## Website integration

### 1. Create the integration account

1. Create an internal user, for example "Website Integration", and give it the
   group **Website Integration (API)** only. It sees nothing of the dashboard.
2. Log in as that user, open *My Preferences > Security > New API Key* and
   choose the scope **Customer Care API**. Keys of this scope open the
   endpoints below and nothing else. They last one year at most.
3. Store the key on the website server. Send it with every call:
   `Authorization: Bearer <key>`.

### 2. Send each submission to Odoo

`POST /vn_care/api/v1/enquiries`

```json
{
  "submission_id": "web-9001",
  "category": "Hotel booking support",
  "customer": {"name": "Ada Obi", "email": "ada.obi@example.com", "phone": "+2348000000001"},
  "message": "Two rooms in Lagos for five nights",
  "travel_date": "2026-12-20",
  "received_at": "2026-11-22T15:00:00+01:00",
  "fields": {"City": "Lagos", "Guests": 4, "Nights": 5}
}
```

| Field | Required | Note |
| --- | --- | --- |
| `submission_id` | yes | The website's own identifier. Sending it again returns the existing enquiry, so a retry is always safe. |
| `category` | yes | The request type as the website labels it ("Hotel booking support") or its code (`hotel_booking_support`); both match the same category. An unknown one creates the category. |
| `category_name` | no | Display name used when a category is created. |
| `customer.name` | yes | |
| `customer.email`, `customer.phone` | no | Without an email, the agent cannot reply by email. |
| `message` | no | The request as typed by the customer. |
| `travel_date` | no | `YYYY-MM-DD`. |
| `received_at` | no | ISO 8601. Defaults to the time of the call. |
| `fields` | no | Category-specific details, as an object or a list of `{"label", "value"}`. |
| `historical` | no | `true` when importing old enquiries: no receipt is sent and no manager is notified. |
| `status` | no | For historical imports, one of `new`, `assigned`, `in_progress`, `awaiting_customer`, `awaiting_partner`, `resolved`, `closed`. |

Answers: `201` created, `200` already there, `422` invalid, `401` bad key,
`403` key not allowed. The body holds `reference`, `status` and `created`.

To send several at once (up to 500), for example to import the existing
enquiries: `{"enquiries": [ {...}, {...} ]}`. The answer lists one result per
submission, with status `207` if any of them was refused.

Other endpoints:

- `GET /vn_care/api/v1/enquiries/<submission_id>`: current status of an enquiry.
- `GET /vn_care/api/v1/categories`: category codes and names.

### 3. Receive status changes from Odoo

Set *Status Webhook URL* and *Shared Secret* in the settings. Each change of
status, agent, outcome or booking reference is sent within moments:

```
POST <webhook url>
X-VN-Care-Event: enquiry.updated
X-VN-Care-Signature: <hex HMAC-SHA256 of the raw body, keyed with the shared secret>

{"submission_id":"web-9001","reference":"VN-ENQ-000027","status":"assigned",
 "category":"hotel_booking_support","assigned_agent":"Agent Name","outcome":"pending",
 "booking_reference":null,"received_at":"2026-11-22T14:00:00Z","updated_at":"2026-11-22T14:46:10Z"}
```

Answer with any `2xx`. Anything else is retried every hour and shows under the
filter *Website Sync Failed*.

### 4. Nightly reconciliation

Set *Reconciliation URL* to a website endpoint that returns the submissions
received since a date:

```
GET <reconciliation url>?since=2026-11-20T00:00:00Z
Authorization: Bearer <shared secret>

{"enquiries": [ {...same format as above...} ]}
```

Every night Odoo asks for the last two days and creates whatever is missing.

## Website side, still to do

The website must add three things for the integration to be complete: the call
in step 2 on every form submission (with a retry queue), the webhook receiver
in step 3, and the listing endpoint in step 4.
