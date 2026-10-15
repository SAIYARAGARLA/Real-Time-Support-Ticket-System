"""Seed default categories, SLA policies, and demo accounts."""

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.auth.security import get_password_hash
from app.database import AsyncSessionLocal, engine
from app.models import (
    Agent,
    AgentAvailability,
    Category,
    SLAPolicy,
    TicketPriority,
    User,
    UserRole,
)


DEFAULT_CATEGORIES = [
    ("Billing", "Invoices, payments, charges, and refunds."),
    ("Technical", "Technical issues, errors, and troubleshooting."),
    ("Account", "Login, profile, and account-access requests."),
    ("Delivery", "Shipping, delivery, and order-fulfilment issues."),
]

DEFAULT_SLA = [
    ("Low SLA", TicketPriority.LOW, 1440, 4320, 5),
    ("Medium SLA", TicketPriority.MEDIUM, 480, 2880, 5),
    ("High SLA", TicketPriority.HIGH, 120, 1440, 5),
    ("Urgent SLA", TicketPriority.URGENT, 30, 480, 5),
]

DEMO_USERS = [
    ("System Admin", "admin@example.com", "AdminPass123!", UserRole.ADMIN),
    ("Demo Agent", "agent@example.com", "AgentPass123!", UserRole.AGENT),
    (
        "Demo Customer",
        "customer@example.com",
        "CustomerPass123!",
        UserRole.CUSTOMER,
    ),
]


async def seed_data():
    async with AsyncSessionLocal() as db:
        try:
            # Create default categories.
            for name, description in DEFAULT_CATEGORIES:
                category_id = await db.scalar(
                    select(Category.id).where(
                        Category.category_name == name
                    )
                )

                if category_id is None:
                    db.add(
                        Category(
                            category_name=name,
                            description=description,
                            is_active=True,
                        )
                    )

            # Create default SLA policies.
            for name, priority, first_response, resolution, escalation in DEFAULT_SLA:
                policy_id = await db.scalar(
                    select(SLAPolicy.id).where(
                        SLAPolicy.priority == priority
                    )
                )

                if policy_id is None:
                    db.add(
                        SLAPolicy(
                            name=name,
                            priority=priority,
                            first_response_minutes=first_response,
                            resolution_minutes=resolution,
                            escalation_minutes=escalation,
                            is_active=True,
                        )
                    )

            await db.flush()

            # Create demo users if they do not already exist.
            users_by_role = {}

            for full_name, email, password, role in DEMO_USERS:
                user = await db.scalar(
                    select(User).where(User.email == email)
                )

                if user is None:
                    user = User(
                        full_name=full_name,
                        email=email,
                        hashed_password=get_password_hash(password),
                        role=role,
                        is_active=True,
                    )
                    db.add(user)
                    await db.flush()

                users_by_role[role] = user

            agent_user = users_by_role[UserRole.AGENT]

            # Load the categories relationship before updating it.
            result = await db.execute(
                select(Agent)
                .options(selectinload(Agent.categories))
                .where(Agent.user_id == agent_user.id)
            )
            agent = result.scalar_one_or_none()

            categories_result = await db.execute(
                select(Category).where(
                    Category.category_name.in_(
                        [name for name, _ in DEFAULT_CATEGORIES]
                    )
                )
            )
            categories = list(categories_result.scalars().all())

            if agent is None:
                agent = Agent(
                    user_id=agent_user.id,
                    name=agent_user.full_name,
                    email=agent_user.email,
                    availability=AgentAvailability.ONLINE,
                    max_open_tickets=10,
                    is_active=True,
                    categories=categories,
                )
                db.add(agent)
            else:
                agent.categories = categories
                agent.availability = AgentAvailability.ONLINE
                agent.is_active = True

            await db.commit()

        except Exception:
            await db.rollback()
            raise


async def main():
    try:
        await seed_data()
    finally:
        # Close the async connection pool before asyncio closes its loop.
        await engine.dispose()

    print("Seed completed.")
    print("Admin:    admin@example.com / AdminPass123!")
    print("Agent:    agent@example.com / AgentPass123!")
    print("Customer: customer@example.com / CustomerPass123!")
    print("Change the demo passwords before deployment.")


if __name__ == "__main__":
    asyncio.run(main())