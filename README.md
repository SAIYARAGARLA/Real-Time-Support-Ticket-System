Real-Time Support Ticket System
A FastAPI backend for customer support tickets, agent assignment, customer/agent messaging, SLA monitoring and escalation, notifications, attachments, feedback, and admin reporting.
Objectives and technology stack
This project is designed around the mentor assignment's 12 levels: project setup and migrations; authentication and authorization; category/SLA management; ticket lifecycle; automatic assignment; WebSocket chat; live notifications; scheduled SLA processing; customer feedback; validation and error handling; search/filtering/pagination/sorting; and reports/dashboard.
- Python 3.9+ (Python 3.11–3.14 recommended)
- FastAPI, Pydantic
- SQLAlchemy async sessions and create_async_engine
- MySQL 8.x with aiomysql
- Alembic migrations
- JWT authentication and password hashing
- WebSockets
- APScheduler
- Uvicorn
Project structure
Real_Time_Support_Ticket_System_Complete/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── auth/
│   ├── routers/
│   ├── services/
│   ├── websockets/
│   ├── jobs/
│   └── seed.py
├── alembic/
│   └── versions/
├── scripts/
│   └── check_database.py
├── static/
│   └── chat_test.html
├── uploads/
├── screenshots/
├── alembic.ini
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
Windows PowerShell setup
Run the following commands from the folder containing requirements.txt and alembic.ini.
1. Create and activate a virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
If PowerShell blocks activation for the current terminal, run this and activate again:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
2. Configure the environment
Create the local .env file from the template:
Copy-Item .env.example .env
Generate a strong JWT secret:
python -c "import secrets; print(secrets.token_urlsafe(48))"
Edit .env and set JWT_SECRET_KEY to the newly generated secret. Configure DATABASE_URL with your own MySQL username/password. URL-encode special characters in a password used in the URL (for example, @ as %40). Never commit .env or share its contents. Only .env.example belongs in Git.
Typical settings (adjust the username/password to your local setup):
DATABASE_URL=mysql+aiomysql://root:YOUR_MYSQL_PASSWORD@localhost:3306/support_ticket_db_complete
JWT_SECRET_KEY=replace_with_a_random_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM=
3. Create a fresh MySQL database
In MySQL Workbench, run:
CREATE DATABASE support_ticket_db_complete
CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
Use this fresh database for this project because its schema matches the included initial migration. Do not point it at a database from a different/older project.
4. Test the connection, migrate, and seed data
From the project root with .venv active:
python -m scripts.check_database
alembic upgrade head
python -m app.seed
The connection check should print Database connection successful: 1. Alembic applies the versioned migration; do not use Base.metadata.create_all() to create application tables. The seed command creates default categories, SLA policies, and local demo accounts if they are missing.
Useful migration commands:
alembic current
alembic history
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
Review any autogenerate migration before applying it.
5. Start the API
python -m uvicorn app.main:app --reload
Keep the terminal running while testing. Open:
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json
- Health check: http://127.0.0.1:8000/health
- Chat test page: http://127.0.0.1:8000/chat-test
Run one Uvicorn worker for this local assignment because APScheduler is started in the API process; multiple workers can run duplicate scheduled jobs.
Demo accounts
After seeding, these local-only demo accounts are available if they were not already present:
Role	Email	Password
Admin	admin@example.com	AdminPass123!
Agent	agent@example.com	AgentPass123!
Customer	customer@example.com	CustomerPass123!


These credentials are for local demonstration only. Change them before any deployment or public demonstration. Public POST /auth/register should create Customer accounts only. Agent/Admin account management is restricted to Admins (the first Admin is bootstrapped by the local seed script).
Roles and access expectations
- Admin: manage agents, categories, SLA policies, ticket reassignment, and reports; view all tickets and authorized conversations.
- Agent: access assigned tickets, update ticket status/priority within allowed transitions, manage availability, and communicate with customers.
- Customer: create tickets, view their own tickets, communicate on their tickets, and submit feedback for eligible tickets.
Access tokens expire after 30 minutes. Protected endpoints should reject invalid/expired tokens with 401 and requests without the required role with 403. Do not share JWTs or include them in screenshots.
API reference overview
Swagger at /docs lists request schemas and response details for the running version of the code. The main HTTP routes are grouped below.
Authentication
- POST /auth/register — public Customer registration
- POST /auth/login — obtain JWT access token
- GET /auth/me — current user's profile
- POST /auth/admin/users — Admin-only creation of another Admin account
Agents
- POST /agents — Admin creates an Agent
- GET /agents — list agents with pagination
- PUT /agents/{agent_id} — Admin updates agent details/categories
- PUT /agents/me/availability — Agent updates Online/Offline status
- GET /agents/me/tickets — current Agent's assigned tickets
Categories and SLA policies
- POST /categories — Admin creates a category
- GET /categories — list categories
- PUT /categories/{category_id} — Admin updates a category
- DELETE /categories/{category_id} — Admin deletes a category when allowed
- GET /sla-policies — list SLA policies
- PUT /sla-policies/{priority} — Admin updates the policy for a priority
Default SLA targets from the mentor assignment:
Priority	First response	Resolution
Low	24 hours	72 hours
Medium	8 hours	48 hours
High	2 hours	24 hours
Urgent	30 minutes	8 hours


Tickets, history, and feedback
- POST /tickets — Customer creates a ticket
- GET /tickets — list tickets with applicable role scope, filtering, sorting and pagination
- GET /tickets/{ticket_id} — retrieve an authorized ticket
- PUT /tickets/{ticket_id}/status — update ticket status
- PUT /tickets/{ticket_id}/priority — update priority and related SLA deadlines
- PUT /tickets/{ticket_id}/assign — Admin manual assignment/reassignment
- PUT /tickets/{ticket_id}/reopen — Customer reopens an eligible resolved ticket
- GET /tickets/{ticket_id}/history — status/action history
- POST /tickets/{ticket_id}/feedback — customer feedback for eligible tickets
- GET /tickets/{ticket_id}/feedback — retrieve ticket feedback
Ticket rules in the assignment include a 5–150 character subject, a description of at least 10 characters, generated unique ticket numbers, SLA deadline calculation, status history, and reopening within seven days of resolution at most twice. Closed tickets must not be updated or reopened.
Messages and attachments
- GET /tickets/{ticket_id}/messages — paginated messages
- POST /tickets/{ticket_id}/messages — send a message through HTTP
- POST /tickets/{ticket_id}/attachments — upload a permitted image/PDF attachment (limit 5 MB)
- GET /attachments/{filename} — retrieve an authorized attachment
Notifications
- GET /notifications — list persisted notifications with pagination
- PUT /notifications/{notification_id}/read — mark one notification as read
- PUT /notifications/read-all — mark all current user's notifications as read
Admin reports
- GET /reports/dashboard — totals, status counts, unassigned tickets, SLA breaches, and online agents
- GET /reports/agent-performance — agent response/resolution metrics, outcomes, SLA performance, ratings for a date range
- GET /reports/category-summary — ticket counts and resolution metrics by category
- GET /reports/sla-summary — met/breached counts by priority
- GET /reports/customer-satisfaction — average rating and rating distribution
Report routes are Admin-only. Use the date parameters shown in Swagger for the running version.
WebSocket chat
Ticket chat endpoint:
ws://127.0.0.1:8000/ws/tickets/{ticket_id}?token=<ACCESS_TOKEN>
Notifications endpoint:
ws://127.0.0.1:8000/ws/notifications?token=<ACCESS_TOKEN>
WebSocket routes do not appear as regular HTTP operations in Swagger. Use /chat-test or a WebSocket-capable client such as Postman.
Browser test page steps
1. Start the API and open http://127.0.0.1:8000/chat-test in two browser tabs.
2. Log in as Customer through Swagger and copy the access token locally. Paste it in tab 1 and enter the ticket ID.
3. Log in as the assigned Agent through Swagger. Paste the Agent token in tab 2 and enter the same ticket ID.
4. Click Connect in both tabs. Each should receive message history; the project requirement is to provide the last 50 messages on connection.
5. Send a public message from the Customer tab and verify it arrives in the Agent tab without a refresh. Reply from the Agent and verify it appears in the Customer tab.
6. Select Typing indicator and verify that a typing event is delivered but not stored as a message.
7. Select Internal note as Agent/Admin and verify it is visible to authorized staff but never delivered to the Customer.
8. Disconnect and reconnect to confirm the server handles disconnects cleanly.
Example public message event:
{"type":"message","message":"Hello from the support desk","is_internal_note":false}
Example internal note (Agent/Admin only):
{"type":"message","message":"Internal follow-up needed","is_internal_note":true}
Example typing event (not persisted as a chat message):
{"type":"typing","is_typing":true}
The implementation may emit events such as history, message, typing, notification, open_ticket_count, and error.
SLA jobs and notifications
The assignment calls for:
- An SLA check every five minutes to mark first-response/resolution breaches.
- Priority escalation after breach, with history and Admin notification; each breach should be escalated only once. Urgent tickets cannot escalate further but should still notify Admin.
- Daily closure of Resolved tickets that have not been reopened within seven days.
- Pausing resolution-time counting while a ticket is in Waiting on Customer.
- Automatic retry/assignment when matching agents become available, without exceeding capacity.
Jobs are scheduled by APScheduler when the application starts. SLA/escalation behavior is periodic, not immediate; testing it may require controlled short SLA deadlines in a separate non-production test database. Avoid changing production data for a demonstration.
Validation and expected HTTP errors
The API should validate required fields and enforce access rules, uniqueness, subject/description/message lengths, rating range 1–5, attachment size/type, ticket status flows, and single feedback per ticket. Expected status codes include 200, 201, 400, 401, 403, 404, 409, and 422 depending on the operation and failure.
End-to-end verification checklist
Use Swagger and the chat test page to capture evidence for these scenarios:
- [ ] Admin, Agent, and Customer logins; /auth/me; unauthorized/forbidden access tests.
- [ ] Category list and Admin category/SLA management.
- [ ] Customer creates a ticket; ticket number, initial status, SLA deadlines, and automatic agent assignment are returned.
- [ ] Agent retrieves assigned tickets, replies, updates status, and history is recorded.
- [ ] Customer and Agent exchange live WebSocket messages in both directions.
- [ ] Internal notes are excluded from Customer history/events; typing indicator is not persisted.
- [ ] Notification records and live notification delivery work for relevant events.
- [ ] Customer can submit one rating (1–5) only for a Resolved/Closed ticket.
- [ ] Reports return appropriate Admin-only results and respect date filters.
- [ ] SLA breach/escalation and auto-close jobs are verified in a controlled test environment.
- [ ] Attachments reject unsupported types and files larger than 5 MB.
- [ ] Pagination, ticket filters, sorting, and validation errors are checked.
Do not claim an item is tested until you have observed the expected behavior.
Submission artifacts
The mentor requests:
1. GitHub repository containing the source, requirements, .env.example, README, and Alembic migration files.
2. Swagger API test screenshots.
3. Screenshots showing a Customer and assigned Agent exchanging messages in separate chat tabs.
4. Setup, migration, demo credential, and WebSocket instructions (this README).
Store local credentials in .env only. Do not commit .env, .venv/, access tokens, MySQL passwords, or secrets in screenshots. The repository should include .env.example, not your real .env.
Operational notes and assumptions
- Run migrations with alembic upgrade head; do not create application tables with create_all().
- The included baseline migration is 0001_initial_schema.py. Review future autogenerate migrations before applying them.
- Seed data is for local development only. Change demo passwords and JWT secret before deployment.
- SMTP email delivery is optional and requires valid SMTP environment variables. If they are blank, email delivery is not configured.
- The local uploads folder stores files; configure appropriate access controls and storage for real deployment.
- Use one Uvicorn worker for this assignment while APScheduler runs in the API process, or configure an external/singleton scheduler before scaling to multiple workers.
- Confirm the configured database name before running migrations. If another project has a separate schema, use a fresh database rather than mixing its migration history.