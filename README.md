# Real-Time Support Ticket System

A FastAPI backend for support tickets, customer/agent conversations, automatic assignment, JWT authentication, role-based permissions, MySQL async persistence, SLA monitoring/escalation, notifications, attachments, and admin reports.

## Implemented mentor requirements

- Async SQLAlchemy sessions using `create_async_engine`, MySQL through `aiomysql`, and Alembic-managed schema (no application `create_all`).
- JWT access tokens that expire after 30 minutes; hashed passwords; Customer, Agent, and Admin roles.
- Admin agent/category/SLA management; agent availability; agent skill categories; least-open-ticket automatic assignment; capacity limits; reassignment audit records and notifications.
- Ticket create/list/detail/status/priority/reopen/history endpoints; category and SLA validations; ticket number generation; response/resolution due dates; pause-aware resolution SLA while waiting for the customer.
- Ticket messages through HTTP and WebSockets; persisted chat; last-50-message history; internal notes restricted to Agents/Admin; typing events; read flags; attachment uploads for images/PDFs up to 5 MB.
- Persisted and live notifications, WebSocket unread/open-ticket count events, SLA check and escalation jobs every five minutes, daily auto-close, and periodic retry of unassigned tickets.
- Customer feedback, filtered/paginated/sorted tickets, admin dashboard and performance/category/SLA/satisfaction reports.
- Optional SMTP email notifications when SMTP environment variables are configured; `/chat-test` HTML test page.

## Requirements

- Python 3.9+ (Python 3.11–3.14 recommended)
- MySQL 8.x
- VS Code or another Python editor

## Windows PowerShell setup

Run commands from this project directory (`Real_Time_Support_Ticket_System_Complete`).

**Use this ZIP as a complete, standalone project.** It has a schema matching the included `0001_initial` migration. For this reason, use the fresh database name `support_ticket_db_complete` configured below; do not point it at the older partially built `support_ticket_db` database. Keep your earlier project as a backup until the new project runs successfully.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Create a random JWT secret and paste it into `JWT_SECRET_KEY` in `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Edit `DATABASE_URL` in `.env` with your local MySQL username and password. URL-encode special characters in the password (for example, `@` as `%40`). Keep `.env` private and never commit it.

Create the database in MySQL Workbench:

```sql
CREATE DATABASE support_ticket_db_complete
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
```

Test the connection if needed, then apply migrations and seed standard data:

```powershell
python -m scripts.check_database
alembic upgrade head
python -m app.seed
```

Start the application:

```powershell
python -m uvicorn app.main:app --reload
```

Open Swagger UI at <http://127.0.0.1:8000/docs> and health check at <http://127.0.0.1:8000/health>.

## Demo credentials

After `python -m app.seed`, these local-only demo accounts are created if missing:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@example.com` | `AdminPass123!` |
| Agent | `agent@example.com` | `AgentPass123!` |
| Customer | `customer@example.com` | `CustomerPass123!` |

Change these credentials before sharing or deploying the system. Public `POST /auth/register` always creates a Customer. Only an Admin can create Agent accounts via `POST /agents` and additional Admin accounts via `POST /auth/admin/users`. The seed script is intended only for local development and demo testing.

## API overview

### Authentication
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/admin/users` (Admin-only endpoint to create another Admin; bootstrap the first Admin with the seed script)

### Agents and categories
- `POST /agents`, `GET /agents`, `PUT /agents/{agent_id}`
- `PUT /agents/me/availability`, `GET /agents/me/tickets`
- `POST /categories`, `GET /categories`, `PUT /categories/{category_id}`, `DELETE /categories/{category_id}`
- `GET /sla-policies`, `PUT /sla-policies/{priority}`

### Tickets, chat and feedback
- `POST /tickets`, `GET /tickets`, `GET /tickets/{ticket_id}`
- `PUT /tickets/{ticket_id}/status`, `/priority`, `/reopen`, `/assign`
- `GET /tickets/{ticket_id}/history`
- `GET/POST /tickets/{ticket_id}/messages`
- `POST /tickets/{ticket_id}/attachments`, authenticated `GET /attachments/{filename}`
- `POST/GET /tickets/{ticket_id}/feedback`

### Notifications and reports
- `GET /notifications`, `PUT /notifications/{notification_id}/read`, `PUT /notifications/read-all`
- Admin only: `GET /reports/dashboard`, `/agent-performance`, `/category-summary`, `/sla-summary`, `/customer-satisfaction`

### WebSockets
- Ticket chat: `ws://localhost:8000/ws/tickets/{ticket_id}?token=<access_token>`
- Notifications: `ws://localhost:8000/ws/notifications?token=<access_token>`

## Suggested end-to-end verification

1. Log in as Admin at `POST /auth/login`, click **Authorize** in Swagger, and create categories if desired. The seed script creates Billing, Technical, Account, and Delivery and an Online demo Agent skilled in all four.
2. Log in as Customer, create a ticket with an active `category_id`, subject (5–150 characters), description (at least 10 characters), and priority. The ticket receives a ticket number and calculated SLA deadlines; if the demo agent is Online and below capacity, assignment happens automatically.
3. Use the returned ticket ID and the customer token with `/ws/tickets/{id}?token=...`. Log in as the Agent in another browser/profile, then connect the assigned agent token. Send messages in both directions. Customer connections do not receive internal notes.
4. Visit <http://127.0.0.1:8000/chat-test> to test with token and ticket ID fields.
5. Update ticket status as the assigned agent (Assigned → In Progress → Waiting on Customer or Resolved; Waiting on Customer → In Progress or Resolved; Resolved → Closed). Customer reopening is allowed only within seven days of resolution and a maximum of two times.
6. Submit feedback for a Resolved/Closed ticket as the customer. Use the Admin token for the dashboard and reports.
7. For SLA testing, in a non-production test database, set very short policy deadlines and let the scheduled jobs run. SLA checks and escalation jobs run every five minutes; auto-close runs daily. Do not expect instant escalation.

## Chat message format

Public message:

```json
{"type":"message", "message":"Hello from the support desk", "is_internal_note":false}
```

Internal note (Agents/Admin only):

```json
{"type":"message", "message":"Internal follow-up needed", "is_internal_note":true}
```

Typing indicator (not saved to the database):

```json
{"type":"typing", "is_typing":true}
```

WebSocket messages include `type` values such as `history`, `message`, `typing`, `notification`, `open_ticket_count`, and `error`. The browser test page is served at `GET /chat-test`.

## Important operational notes

- Run `alembic upgrade head` after every new migration. Do not run schema creation through `Base.metadata.create_all`.
- The APScheduler instance runs inside the API process. For this local assignment run one Uvicorn worker; multiple workers would each schedule duplicate jobs.
- SMTP is optional. Fill the SMTP settings in `.env` to enable email. Without SMTP settings, email hooks safely do nothing.
- `uploads/` files and `.env` are excluded from Git by `.gitignore`. Uploaded content types are limited to PDF and common image formats and uploads are limited to 5 MB.
- The included demo credentials are for local testing only. Use a strong secret, private credentials, and a production server/configuration before deployment.
- If you receive a migration error that a table already exists, confirm your `.env` points to the fresh `support_ticket_db_complete` database and that you ran `alembic upgrade head` only once for this project.
- Do not copy the older `686070763bbf_create_support_ticket_tables.py` migration from the previous partial project into this project's `alembic/versions` folder. This ZIP includes its own complete baseline migration.
