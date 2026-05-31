import asyncio
import httpx
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    row = await conn.fetchrow('SELECT id FROM challenges ORDER BY created_at DESC LIMIT 1')
    await conn.close()
    
    challenge_id = row['id']
    code = """def solution(arr, target):
    for i in range(len(arr)):
        if arr[i] == target:
            return i
    return -1"""

    print("Submitting to API...")
    async with httpx.AsyncClient() as client:
        # We need auth token. Let's just mock the current user or bypass it?
        # Without auth token, this will return 401.
        # Let's check if we can bypass auth or we need a token.
        print("Need auth token to test API.")

asyncio.run(main())
