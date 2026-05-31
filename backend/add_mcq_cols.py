import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    try:
        await conn.execute('ALTER TABLE challenges ADD COLUMN language VARCHAR(20) NOT NULL DEFAULT \'Python\';')
        print("Added language to challenges.")
    except Exception as e: print(e)
    try:
        await conn.execute('ALTER TABLE challenges ADD COLUMN mcqs JSONB;')
        print("Added mcqs to challenges.")
    except Exception as e: print(e)
    try:
        await conn.execute('ALTER TABLE challenge_attempts ADD COLUMN mcqs_passed INTEGER NOT NULL DEFAULT 0;')
        print("Added mcqs_passed to challenge_attempts.")
    except Exception as e: print(e)
    await conn.close()

asyncio.run(main())
