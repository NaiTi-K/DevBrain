import asyncio
import asyncpg
import sys

# Configure your DB URL here if it changes
DB_URL = "postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db"

async def clear_db():
    print(f"Connecting to {DB_URL}...")
    try:
        conn = await asyncpg.connect(DB_URL)
        
        print("Clearing challenge_attempts...")
        await conn.execute("DELETE FROM challenge_attempts")
        
        print("Clearing challenges...")
        await conn.execute("DELETE FROM challenges")
        
        print("Database cleared successfully!")
        await conn.close()
    except Exception as e:
        print(f"Error clearing database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(clear_db())
