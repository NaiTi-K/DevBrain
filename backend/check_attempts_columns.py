import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    # Get column names of challenge_attempts
    columns = await conn.fetch('''
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'challenge_attempts'
    ''')
    for col in columns:
        print(dict(col))
    await conn.close()

asyncio.run(check())
