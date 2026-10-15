"""Check that the configured async database is reachable.

Run from the project root after creating .env:
    python -m scripts.check_database
"""
import asyncio

from sqlalchemy import text

from app.database import engine


async def main() -> None:
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            print(f"Database connection successful: {result.scalar()}")
    except Exception as exc:
        print(f"Database connection failed: {exc}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
