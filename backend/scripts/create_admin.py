"""Create the first admin (enterprise) user."""
import asyncio
import uuid

from app.core.security import get_password_hash, generate_api_key
from app.db.session import async_session_factory
from app.models.models import User


async def create_admin():
    email = "admin@hcd.local"
    password = "changeme"
    async with async_session_factory() as db:
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=get_password_hash(password),
            full_name="Administrator",
            plan="enterprise",
            is_superuser=True,
            is_verified=True,
            api_key=generate_api_key(),
        )
        db.add(user)
        await db.commit()
        print(f"Created admin user: {email} / {password}")
        print(f"API Key: {user.api_key}")


if __name__ == "__main__":
    asyncio.run(create_admin())
