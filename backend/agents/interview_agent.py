"""
Adaptive Interview Agent
========================
Dynamic Q&A modes based on resume or DSA topics, with lenient scoring.
"""

from __future__ import annotations

import logging

from agents.orchestrator import DevBrainState
from services.llm_service import llm

logger = logging.getLogger(__name__)

# State constants
PHASE_RESUME = "RESUME"
PHASE_DSA = "DSA"
PHASE_SCORE = "SCORE"


def _get_resume(state: DevBrainState) -> str:
    user = state.get("user")
    if user and hasattr(user, "resume_text") and user.resume_text:
        return user.resume_text
    return "No resume provided."


def _get_mode(state: DevBrainState) -> str:
    structured = state.get("structured_output") or {}
    return structured.get("mode", "dsa")


def _get_current_phase(state: DevBrainState) -> str:
    structured = state.get("structured_output") or {}
    mode = _get_mode(state)
    return structured.get("phase", PHASE_RESUME if mode == "resume" else PHASE_DSA)


async def _generate_scorecard(scores: dict, history: list, final_feedback: str, structured: dict) -> tuple[str, dict]:
    total = sum(scores.values()) / max(len(scores), 1)
    agent_output = (
        f"{final_feedback}\n\n### Interview Complete\n\n**Average Score:** {total:.1f}/10\n\n**Scorecard:**\n"
    )
    for k, v in scores.items():
        agent_output += f"- {k}: {v}/10\n"

    prompt = f'Write an honest 3-sentence debrief based on these scores: {scores}. JSON: {{"debrief": "..."}}'
    res = await llm.structured_call(prompt)
    agent_output += f"\n**Debrief:**\n{res.get('debrief')}"

    structured["session_complete"] = True
    structured["final_report"] = {
        "overall_score": total,
        "summary": res.get("debrief", ""),
        "strengths": [k for k, v in scores.items() if v >= 7],
        "weak_areas": [k for k, v in scores.items() if v < 7],
    }
    return agent_output, structured


async def interview_agent_node(state: DevBrainState) -> DevBrainState:
    """
    Main state machine router.
    """
    phase = _get_current_phase(state)
    history = state.get("conversation_history", [])
    user_input = state.get("user_input", "")
    structured = state.get("structured_output") or {}
    resume = _get_resume(state)
    scores = structured.get("scores", {})

    agent_output = ""
    next_phase = phase

    if user_input:
        history.append({"role": "user", "content": user_input})

    last_question = ""
    for msg in reversed(history):
        if msg["role"] == "agent":
            last_question = msg["content"]
            break

    if phase == PHASE_RESUME:
        turn_count = structured.get("resume_turn", 0)

        if turn_count == 0:
            prompt = f'Resume:\n{resume}\n\nGenerate ONE challenging but fair behavioral interview question to start the interview. Return ONLY a JSON object: {{"question": "..."}}'
            res = await llm.structured_call(prompt, "You are a lenient Interviewer.")
            agent_output = res.get("question", "Tell me about a challenging project you worked on.")
            structured["resume_turn"] = 1
        elif turn_count < 4:
            prompt = f'Previous Question: \'{last_question}\'\n\nThe user answered: \'{user_input}\'. Evaluate it leniently (score 1-10). Don\'t expect a pro answer. Then, generate the NEXT question (a follow-up or a new project-specific question based on their resume: {resume}). If they score >= 7, make the next question a deeper, more advanced technical follow-up. If <= 4, make it a broader, foundational question. Make sure to dive deep and cover every aspect of their projects and technical decisions. Return JSON: {{"score": 1-10, "feedback": "...", "next_question": "..."}}'
            res = await llm.structured_call(prompt, "You are a lenient Interviewer.")
            score = res.get("score", 7)
            scores[f"Resume Q{turn_count}"] = score
            agent_output = f"*(Score for this answer: {score}/10)*\n\n{res.get('feedback', 'Good.')}\n\n**Next Question:**\n{res.get('next_question', 'Next question.')}"
            structured["resume_turn"] = turn_count + 1
        else:
            prompt = f'Previous Question: \'{last_question}\'\n\nThe user answered their final question: \'{user_input}\'. Evaluate leniently (score 1-10). Return JSON: {{"score": 1-10, "feedback": "..."}}'
            res = await llm.structured_call(prompt, "You are a lenient Interviewer.")
            score = res.get("score", 7)
            scores[f"Resume Q{turn_count}"] = score
            agent_output, structured = await _generate_scorecard(
                scores, history, f"*(Score for this answer: {score}/10)*\n\n{res.get('feedback', 'Good.')}", structured
            )
            next_phase = PHASE_SCORE

    elif phase == PHASE_DSA:
        turn_count = structured.get("dsa_turn", 0)
        difficulty = structured.get("dsa_difficulty", "Hard")

        if turn_count == 0:
            structured["dsa_difficulty"] = "Hard"
            prompt = 'Generate ONE challenging (Hard difficulty) Data Structures and Algorithms (DSA) question. Do not ask for system design or behavioral. Return JSON: {"question": "...", "topic": "..."}'
            res = await llm.structured_call(prompt, "You are a demanding DSA Interviewer.")
            agent_output = f"**DSA Question 1:**\n{res.get('question')}"
            structured["dsa_turn"] = 1
        elif turn_count < 3:
            prompt = f'Previous Question: \'{last_question}\'\n\nEvaluate user\'s DSA answer leniently: \'{user_input}\'. Provide brief feedback. If the user hasn\'t provided time and space complexity, explicitly remind them or ask for it in the feedback. If they score >= 7, set next_difficulty to a harder level. If <= 4, set to an easier level. Current difficulty is {difficulty}. Then provide a NEW DSA question on a different topic matching the next_difficulty. Return JSON: {{"score": 1-10, "feedback": "...", "next_difficulty": "...", "next_question": "..."}}'
            res = await llm.structured_call(prompt, "You are an adaptive DSA Interviewer.")
            score = res.get("score", 7)
            scores[f"DSA Q{turn_count}"] = score
            structured["dsa_difficulty"] = res.get("next_difficulty", difficulty)
            agent_output = f"*(Score for this answer: {score}/10)*\n\n{res.get('feedback')}\n\n**DSA Question {turn_count + 1} ({structured['dsa_difficulty']}):**\n{res.get('next_question')}"
            structured["dsa_turn"] = turn_count + 1
        else:
            prompt = f'Previous Question: \'{last_question}\'\n\nEvaluate user\'s final DSA answer leniently: \'{user_input}\'. Return JSON: {{"score": 1-10, "feedback": "..."}}'
            res = await llm.structured_call(prompt, "You are an adaptive DSA Interviewer.")
            score = res.get("score", 7)
            scores[f"DSA Q{turn_count}"] = score
            agent_output, structured = await _generate_scorecard(
                scores, history, f"*(Score for this answer: {score}/10)*\n\n{res.get('feedback', 'Good.')}", structured
            )
            next_phase = PHASE_SCORE

    elif phase == PHASE_SCORE:
        agent_output = "The interview is already complete."
        structured["session_complete"] = True

    structured["phase"] = next_phase
    structured["scores"] = scores

    state["structured_output"] = structured
    state["agent_output"] = agent_output

    if agent_output:
        history.append({"role": "agent", "content": agent_output})

    state["conversation_history"] = history

    return state
