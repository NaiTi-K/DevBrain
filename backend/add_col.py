import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    await conn.execute('ALTER TABLE users ADD COLUMN resume_text TEXT;')
    print("Column added successfully.")
    await conn.close()

asyncio.run(main())
