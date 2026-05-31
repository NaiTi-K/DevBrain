import asyncio
import json
from services.sandbox_service import evaluate_submission
from agents.challenge_agent import _build_challenge_prompt
from services.llm_service import llm
import re

def _parse_json_safe(text: str) -> dict:
    if isinstance(text, dict):
        return text
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return None

async def test_language(lang):
    print(f"\n--- Testing {lang} Pipeline ---")
    prompt = _build_challenge_prompt(topic="arrays", difficulty="easy", language=lang, skill=lang)
    raw = await llm.structured_call(prompt)
    parsed = _parse_json_safe(raw)
    
    if not parsed:
        print(f"Failed to parse JSON for {lang}")
        return
        
    code = parsed.get("solution", "").replace("\\n", "\n")
    test_cases = parsed.get("test_cases", [])
    
    print("\nExecuting Sandbox...")
    res = await evaluate_submission(user_code=code, test_cases=test_cases, language=lang, timeout_seconds=15.0)
    print("Passed:", res["passed"])
    if not res["passed"]:
        # Safe print for Windows
        out = res["output"].replace("\u274c", "X").replace("\u2705", "V").replace("\u2014", "-")
        print("Output:\n", out)
        
async def main():
    await test_language("JavaScript")
    await test_language("C++")

asyncio.run(main())
