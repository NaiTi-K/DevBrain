"""
Adaptive Interview Agent (State Machine)
========================================
Strict Phases: BEHAVIORAL → PROBLEM → CLARIFICATION → APPROACH_AND_BIGO → CODE → TESTING → SCORE
"""

from __future__ import annotations

import logging

from agents.orchestrator import DevBrainState
from services.llm_service import llm

logger = logging.getLogger(__name__)

# State constants
PHASE_BEHAVIORAL = "BEHAVIORAL"
PHASE_PROBLEM = "PROBLEM"
PHASE_CLARIFICATION = "CLARIFICATION"
PHASE_APPROACH = "APPROACH_AND_BIGO"
PHASE_CODE = "CODE"
PHASE_TESTING = "TESTING"
PHASE_SCORE = "SCORE"

def _get_resume(state: DevBrainState) -> str:
    user = state.get("user")
    if user and hasattr(user, "resume_text") and user.resume_text:
        return user.resume_text
    return "No resume provided."

def _get_current_phase(state: DevBrainState) -> str:
    structured = state.get("structured_output") or {}
    return structured.get("phase", PHASE_BEHAVIORAL)

def _get_scores(state: DevBrainState) -> dict:
    structured = state.get("structured_output") or {}
    return structured.get("scores", {
        "Behavioral": 3,
        "Algorithm Design": 3,
        "Complexity": 3,
        "Code Quality": 3,
        "Testing": 3
    })

async def interview_agent_node(state: DevBrainState) -> DevBrainState:
    """
    Main state machine router.
    """
    phase = _get_current_phase(state)
    history = state.get("conversation_history", [])
    user_input = state.get("user_input", "")
    structured = state.get("structured_output") or {}
    resume = _get_resume(state)
    scores = _get_scores(state)

    agent_output = ""
    next_phase = phase

    if phase == PHASE_BEHAVIORAL:
        if not history:
            # First turn: Generate behavioral question based on resume
            prompt = f"Resume:\n{resume}\n\nGenerate ONE challenging behavioral interview question about a specific project listed (or a general one if no resume). Ask them to defend technical choices honestly (I vs We). Return ONLY a JSON object: {{\"question\": \"...\"}}"
            res = await llm.structured_call(prompt, "You are a tough Principal Engineer.")
            agent_output = res.get("question", "Tell me about a challenging project you worked on.")
            history.append({"role": "agent", "content": agent_output})
        else:
            # Evaluate answer and move to PROBLEM
            prompt = f"Evaluate this behavioral answer: {user_input}. Score 1-5. Return JSON: {{\"score\": 4, \"feedback\": \"...\"}}"
            res = await llm.structured_call(prompt, "You are a tough Principal Engineer.")
            scores["Behavioral"] = res.get("score", 3)
            agent_output = f"{res.get('feedback', 'Good.')}\n\nLet's move on to a coding problem. Are you ready?"
            next_phase = PHASE_PROBLEM

    elif phase == PHASE_PROBLEM:
        # Give the problem
        prompt = "Generate a medium difficulty DSA question. Return JSON: {\"question\": \"...\", \"topic\": \"...\"}"
        res = await llm.structured_call(prompt)
        structured["problem"] = res
        agent_output = f"**Problem:**\n{res.get('question')}\n\nDo you have any clarifying questions before we discuss the approach?"
        next_phase = PHASE_CLARIFICATION

    elif phase == PHASE_CLARIFICATION:
        if "approach" in user_input.lower() or "big-o" in user_input.lower() or "ready" in user_input.lower():
            next_phase = PHASE_APPROACH
            agent_output = "Great. Before you write any code, please describe your approach and explicitly state the Time and Space Complexity (Big-O)."
        else:
            prompt = f"The user asked a clarifying question: {user_input} about the problem: {structured.get('problem')}. Answer concisely. JSON: {{\"answer\": \"...\"}}"
            res = await llm.structured_call(prompt)
            agent_output = f"{res.get('answer')}\n\n(Ask more questions or say 'ready' to move to the approach)."

    elif phase == PHASE_APPROACH:
        # Hard Gate: Must state Big-O
        prompt = f"Analyze if the user explicitly stated correct Time AND Space complexity for this problem: {structured.get('problem')} in their answer: {user_input}. JSON: {{\"has_correct_time\": bool, \"has_correct_space\": bool, \"feedback\": \"...\", \"score\": 1-5}}"
        res = await llm.structured_call(prompt)
        scores["Algorithm Design"] = res.get("score", 3)
        scores["Complexity"] = res.get("score", 3)
        
        if res.get("has_correct_time") and res.get("has_correct_space"):
            next_phase = PHASE_CODE
            agent_output = f"{res.get('feedback')}\n\nYour complexities are correct. You may now write the code."
        else:
            agent_output = f"{res.get('feedback')}\n\n**GATE:** You must explicitly state both Time and Space complexity before coding."

    elif phase == PHASE_CODE:
        prompt = f"Evaluate the user's code for this problem. {user_input}. JSON: {{\"score\": 1-5, \"feedback\": \"...\"}}"
        res = await llm.structured_call(prompt)
        scores["Code Quality"] = res.get("score", 3)
        agent_output = f"{res.get('feedback')}\n\nNow, how would you test this code? Write out a few test cases."
        next_phase = PHASE_TESTING

    elif phase == PHASE_TESTING:
        prompt = f"Evaluate the user's test cases: {user_input}. JSON: {{\"score\": 1-5, \"feedback\": \"...\"}}"
        res = await llm.structured_call(prompt)
        scores["Testing"] = res.get("score", 3)
        agent_output = f"{res.get('feedback')}\n\nWe have finished the interview. Let me compute your scorecard."
        next_phase = PHASE_SCORE

    elif phase == PHASE_SCORE:
        # Honest Debrief
        total = sum(scores.values()) / 5
        agent_output = f"### Interview Complete\n\n**Final Score:** {total:.1f}/5\n\n**5-Axis Scorecard:**\n"
        for k, v in scores.items():
            agent_output += f"- {k}: {v}/5\n"
        
        prompt = f"Write an honest 3-sentence debrief quoting one specific thing they did wrong and one they did right. History: {history}. JSON: {{\"debrief\": \"...\", \"ideal_answer\": \"...\"}}"
        res = await llm.structured_call(prompt)
        agent_output += f"\n**Debrief:**\n{res.get('debrief')}\n\n**Ideal Solution:**\n```python\n{res.get('ideal_answer')}\n```"
        
        structured["session_complete"] = True
        structured["final_report"] = {
            "overall_score": total * 2, # map 5 to 10 scale
            "summary": res.get("debrief", ""),
            "strengths": [k for k, v in scores.items() if v >= 4],
            "weak_areas": [k for k, v in scores.items() if v < 4]
        }

    structured["phase"] = next_phase
    structured["scores"] = scores
    
    state["structured_output"] = structured
    state["agent_output"] = agent_output
    
    return state