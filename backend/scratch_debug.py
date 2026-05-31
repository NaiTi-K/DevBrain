import asyncio
import uuid
from sqlalchemy import select
from httpx import AsyncClient, ASGITransport

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app
from models.database import async_session
from models.user import User
from core.security import create_access_token

async def main():
    async with async_session() as session:
        # Get the first user
        result = await session.execute(select(User))
        user = result.scalars().first()
        if not user:
            print("No users found in database! Let's create a temporary user.")
            user = User(
                id=uuid.uuid4(),
                github_id=12345,
                github_username="testdev",
                display_name="Test Dev",
                avatar_url="https://avatars.githubusercontent.com/u/12345"
            )
            session.add(user)
            await session.commit()
            print(f"Created user: {user.github_username} (github_id: {user.github_id})")
        else:
            print(f"Found user in DB: {user.github_username} (github_id: {user.github_id})")
        
        github_id = user.github_id

    token = create_access_token({"sub": str(github_id)})
    print(f"Generated JWT token: Bearer {token}")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("Sending POST /github/analyze...")
        try:
            response = await client.post(
                "/github/analyze",
                json={"github_token": ""},
                headers={"Authorization": f"Bearer {token}"}
            )
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")
        except Exception:
            print("Error during request:")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
