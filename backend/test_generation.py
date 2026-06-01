import sys
import os
import asyncio
import logging
import json
from pprint import pprint

# Setup path
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv('backend/.env')

from agents.challenge_agent import _build_challenge_prompt, validate_and_fix_challenge, _parse_json_safe
from services.llm_service import llm
from services.sandbox_service import run_code

logging.basicConfig(level=logging.DEBUG)

async def main():
    print("Building prompt...")
    prompt = _build_challenge_prompt(
        topic="dynamic programming", 
        difficulty="medium", 
        language="Python", 
        skill="Python", 
        search_context=""
    )
    
    print("Calling LLM...")
    try:
        raw = await llm.structured_call(prompt, temperature=0.8)
    except Exception as e:
        print(f"LLM call failed: {e}")
        return
    
    print("LLM RAW OUTPUT:")
    pprint(raw)
    
    parsed = _parse_json_safe(raw)
    if not parsed:
        print("FAILED TO PARSE JSON")
        return
        
    print("\nValidating and fixing challenge...")
    try:
        validate_and_fix_challenge(parsed)
        print("Validation successful!")
    except Exception as e:
        print(f"Validation failed: {e}")
        return
        
    solution_code = parsed.get("solution", "").replace("\\n", "\n")
    test_cases = parsed.get("test_cases", [])
    schema = parsed.get("schema", {})
    judge = schema.get("judge", "exact")
    
    print("\n--- SOLUTION CODE ---")
    print(solution_code)
    print("\n--- TEST CASES ---")
    print(json.dumps(test_cases, indent=2))
    
    print("\nRunning Sandbox Evaluator (Python)...")
    try:
        eval_result = run_code("python", solution_code, schema, test_cases, judge)
        print("SANDBOX RESULT:")
        pprint(eval_result)
    except Exception as e:
        print(f"Sandbox crash: {e}")
    
if __name__ == "__main__":
    asyncio.run(main())
