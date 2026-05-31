import asyncio
import json
from services.sandbox_service import evaluate_submission
from agents.challenge_agent import _build_challenge_prompt
from services.llm_service import llm

def _parse_json_safe(text: str) -> dict:
    import re
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

async def main():
    prompt = _build_challenge_prompt(topic="trees", difficulty="easy", language="C++", skill="C++")
    print("Requesting LLM...")
    raw = await llm.structured_call(prompt)
    parsed = _parse_json_safe(raw)
    
    if not parsed:
        print("Failed to parse JSON")
        return
        
    print(f"Title: {parsed.get('title')}")
    print("Language: C++")
    mcqs = parsed.get("mcqs", [])
    print(f"MCQs generated: {len(mcqs)}")
    for i, mcq in enumerate(mcqs):
        print(f"Q{i+1}: {mcq.get('question')}")
        
    code = parsed.get("solution")
    test_cases = parsed.get("test_cases")
    
    print("\nRunning C++ Docker Sandbox...")
    res = await evaluate_submission(user_code=code, test_cases=test_cases, language="C++")
    print(json.dumps(res, indent=2))

asyncio.run(main())
