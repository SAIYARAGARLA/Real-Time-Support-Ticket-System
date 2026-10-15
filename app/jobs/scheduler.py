import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import (
    Agent, SLAPolicy, Ticket, TicketHistory, TicketPriority, TicketStatus,
    User, UserRole, utcnow,
)
from app.services.assignment import OPEN_STATUSES, assign_waiting_tickets, publish_open_ticket_counts
from app.services.email_service import send_email
from app.services.notifications import queue_admin_notifications

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")
PRIORITY_ORDER = [TicketPriority.LOW, TicketPriority.MEDIUM, TicketPriority.HIGH, TicketPriority.URGENT]


async def check_sla_job() -> None:
    now = utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Ticket).where(Ticket.status.in_(OPEN_STATUSES)))
        tickets = list(result.scalars().all())
        changed = False
        admin_notifications = []
        breach_emails: list[tuple[str, str, str]] = []
        admin_rows = await db.execute(select(User.email).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
        admin_emails = [row[0] for row in admin_rows.all()]
        for ticket in tickets:
            breached_now: list[str] = []
            if ticket.first_response_at is None and not ticket.first_response_breached and now > ticket.first_response_due:
                ticket.first_response_breached = True
                breached_now.append("first response")
            pause_seconds = ticket.total_waiting_seconds
            if ticket.status == TicketStatus.WAITING_ON_CUSTOMER and ticket.waiting_started_at:
                pause_seconds += max(0, int((now - ticket.waiting_started_at).total_seconds()))
            effective_resolution_due = ticket.resolution_due + timedelta(seconds=pause_seconds)
            if ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED) and not ticket.resolution_breached and now > effective_resolution_due:
                ticket.resolution_breached = True
                breached_now.append("resolution")
            if breached_now:
                ticket.sla_breached = True
                changed = True
                db.add(TicketHistory(
                    ticket_id=ticket.id, changed_by_id=None,
                    old_status=ticket.status.value, new_status=ticket.status.value,
                    action="SLA_BREACH", details="SLA breached: " + ", ".join(breached_now),
                ))
                admin_notifications.extend(await queue_admin_notifications(
                    db,
                    "SLA breached",
                    f"Ticket {ticket.ticket_number} breached its " + " and ".join(breached_now) + " SLA.",
                    ticket.id,
                ))
                for email in admin_emails:
                    breach_emails.append((email, f"SLA breached: {ticket.ticket_number}", f"Ticket {ticket.ticket_number} breached: {', '.join(breached_now)}."))
        if changed:
            await db.commit()
        else:
            await db.rollback()
    for email, subject, body in breach_emails:
        await send_email(email, subject, body)
    if changed:
        async with AsyncSessionLocal() as db:
            await publish_open_ticket_counts(db)


async def escalation_job() -> None:
    now = utcnow()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Ticket).where(Ticket.status.in_(OPEN_STATUSES), Ticket.sla_breached.is_(True)))
        tickets = list(result.scalars().all())
        changed = False
        admin_emails_result = await db.execute(select(User.email).where(User.role == UserRole.ADMIN, User.is_active.is_(True)))
        admin_emails = [row[0] for row in admin_emails_result.all()]
        emails_to_send: list[tuple[str, str, str]] = []
        for ticket in tickets:
            pending_breaches = []
            if ticket.first_response_breached and not ticket.first_response_escalated:
                pending_breaches.append("first-response")
                ticket.first_response_escalated = True
            if ticket.resolution_breached and not ticket.resolution_escalated:
                pending_breaches.append("resolution")
                ticket.resolution_escalated = True
            for breach_name in pending_breaches:
                old_priority = ticket.priority
                index = PRIORITY_ORDER.index(old_priority)
                if index < len(PRIORITY_ORDER) - 1:
                    ticket.priority = PRIORITY_ORDER[index + 1]
                    policy = await db.scalar(select(SLAPolicy).where(SLAPolicy.priority == ticket.priority, SLAPolicy.is_active.is_(True)))
                    if policy:
                        ticket.sla_policy_id = policy.id
                        ticket.first_response_due = now + timedelta(minutes=policy.first_response_minutes)
                        ticket.resolution_due = now + timedelta(minutes=policy.resolution_minutes)
                        # The escalated SLA begins a new window.
                        ticket.total_waiting_seconds = 0
                db.add(TicketHistory(
                    ticket_id=ticket.id, changed_by_id=None,
                    old_status=ticket.status.value, new_status=ticket.status.value,
                    action="SLA_ESCALATION",
                    details=f"{breach_name} SLA breach escalated from {old_priority.value} to {ticket.priority.value}.",
                ))
                await queue_admin_notifications(
                    db,
                    "Ticket SLA escalated",
                    f"Ticket {ticket.ticket_number}: {breach_name} SLA breach. Priority is {ticket.priority.value}.",
                    ticket.id,
                )
                for email in admin_emails:
                    emails_to_send.append((email, f"Ticket SLA escalated: {ticket.ticket_number}", f"Ticket {ticket.ticket_number} had a {breach_name} SLA breach. Priority: {ticket.priority.value}."))
                changed = True
        if changed:
            await db.commit()
        else:
            await db.rollback()
    for email, subject, body in emails_to_send:
        await send_email(email, subject, body)


async def auto_close_job() -> None:
    cutoff = utcnow() - timedelta(days=7)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Ticket).where(Ticket.status == TicketStatus.RESOLVED, Ticket.resolved_at.is_not(None), Ticket.resolved_at <= cutoff))
        tickets = list(result.scalars().all())
        for ticket in tickets:
            previous = ticket.status
            ticket.status = TicketStatus.CLOSED
            ticket.closed_at = utcnow()
            db.add(TicketHistory(
                ticket_id=ticket.id, changed_by_id=None,
                old_status=previous.value, new_status=TicketStatus.CLOSED.value,
                action="AUTO_CLOSED", details="Automatically closed 7 days after resolution.",
            ))
            from app.services.notifications import queue_notification
            await queue_notification(db, ticket.customer_id, "Ticket automatically closed", f"Ticket {ticket.ticket_number} was automatically closed.", ticket.id)
        if tickets:
            await db.commit()
        else:
            await db.rollback()
    if tickets:
        async with AsyncSessionLocal() as db:
            await publish_open_ticket_counts(db)


async def assign_unassigned_job() -> None:
    async with AsyncSessionLocal() as db:
        assigned = await assign_waiting_tickets(db)
        if assigned:
            await db.commit()
            await publish_open_ticket_counts(db)
        else:
            await db.rollback()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(check_sla_job, "interval", minutes=5, id="sla_check", replace_existing=True)
    scheduler.add_job(escalation_job, "interval", minutes=5, id="sla_escalation", replace_existing=True)
    scheduler.add_job(auto_close_job, "cron", hour=0, minute=0, id="auto_close", replace_existing=True)
    scheduler.add_job(assign_unassigned_job, "interval", minutes=1, id="assign_unassigned", replace_existing=True)
    scheduler.start()
    logger.info("Background jobs started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
