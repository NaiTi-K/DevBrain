import asyncio
import asyncpg
import json

async def main():
    conn = await asyncpg.connect('postgresql://devbrain_user:devbrain_pass@localhost:5432/devbrain_db')
    row = await conn.fetchrow('SELECT id, language, test_cases FROM challenges ORDER BY created_at DESC LIMIT 1')
    
    if not row:
        print("No challenges found")
        return
        
    print("Challenge ID:", row['id'])
    print("Language:", row['language'])
    
    # Check if test cases is a list of dicts or something else
    test_cases = row['test_cases']
    if isinstance(test_cases, str):
        test_cases = json.loads(test_cases)
        
    print("Test Cases type:", type(test_cases))
    print("First test case:", test_cases[0] if test_cases else None)
    
    # Manually run evaluate_submission
    from services.sandbox_service import evaluate_submission
    
    code = """def solution(arr, target):
    for i in range(len(arr)):
        if arr[i] == target:
            return i
    return -1"""

    print("Running evaluate_submission...")
    res = await evaluate_submission(user_code=code, test_cases=test_cases, language=row['language'], timeout_seconds=15.0)
    print("Passed:", res["passed"])
    print("Output:\n", res["output"].replace("\u274c", "X").replace("\u2705", "V"))
    print("Error:", res["error"])
    
    await conn.close()

asyncio.run(main())
