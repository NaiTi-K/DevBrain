import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    rows = await conn.fetch('SELECT title, schema FROM challenges')
    print(f"Challenges in DB: {[dict(r) for r in rows]}")
    await conn.close()

asyncio.run(check())
