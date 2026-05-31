import asyncio
from agents.challenge_agent import evaluate_submission, _build_challenge_prompt
from services.llm_service import llm
import json
import re

def _parse_json_safe(text):
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None

async def main():
    prompt = _build_challenge_prompt("data structures", "medium", "Python", "Python")
    raw = await llm.structured_call(prompt)
    parsed = _parse_json_safe(raw)
    if not parsed:
        print("Failed to parse JSON")
        return
        
    solution_code = parsed.get("solution", "")
    test_cases = parsed.get("test_cases", [])
    
    print("Test Cases:")
    for i, tc in enumerate(test_cases):
        print(f"{i+1}: Input: {tc.get('input')} Expected: {tc.get('expected')}")
        
    print("\nSolution Code:")
    print(solution_code)
    
    eval_res = await evaluate_submission(user_code=solution_code, test_cases=test_cases, timeout_seconds=5.0)
    print(f"\nPassed: {eval_res['passed']}")
    print(f"Error: {eval_res.get('error')}")
    print(f"Output:\n{eval_res['output']}")

asyncio.run(main())
