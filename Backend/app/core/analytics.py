"""Analytics helpers: record questions, categorize via LLM, and produce simple stats."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import func

from app.core.logging import get_logger
from app.llm.llm import get_llm
from app.core.database import SessionLocal
from app.core.models import Question

logger = get_logger(__name__)


def _categorize_with_llm(text: str) -> List[str]:
    """Use the project's LLM to produce a short list of categories/tags for the question.

    Returns a list of short tags (strings). If LLM fails, returns an empty list.
    """
    try:
        llm = get_llm()
        prompt = (
            "You are a classifier. Given the following DevOps user question, return a comma-separated"
            " list of short tags describing the topic(s). Only return tags, no extra text."
            f"\n\nQuestion: {text}\n\nTags:"
        )
        response = llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        # split by comma or newline
        parts = [p.strip() for p in content.replace('\n', ',').split(',') if p.strip()]
        # keep up to 5 tags
        tags = parts[:5]
        return tags
    except Exception as e:
        logger.warning("Analytics: LLM categorization failed: %s", e)
        return []


def record_question(username: str, question: str, agent_steps: List[Dict[str, Any]], final_answer: str, used_mcp: Optional[str], mcp_results: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Record a question and its metadata into the DB and return the saved record."""
    db = SessionLocal()
    try:
        tags = _categorize_with_llm(question)
        
        new_q = Question(
            username=username,
            question=question,
            # timestamp is handled by server_default=func.now(), but we can set it if we want exact python time
            timestamp=datetime.utcnow(),
            tags=tags,
            agent_steps=agent_steps or [],
            final_answer=final_answer,
            used_mcp=used_mcp,
            mcp_results=mcp_results or []
        )
        
        db.add(new_q)
        db.commit()
        db.refresh(new_q)
        
        logger.info("Analytics: recorded question id=%s user=%s tags=%s", new_q.id, username, tags)
        
        # Return dict representation
        return {
            "id": new_q.id,
            "username": new_q.username,
            "question": new_q.question,
            "timestamp": new_q.timestamp.isoformat() if new_q.timestamp else None,
            "tags": new_q.tags,
            "agent_steps": new_q.agent_steps,
            "final_answer": new_q.final_answer,
            "used_mcp": new_q.used_mcp,
            "mcp_results": new_q.mcp_results
        }
    finally:
        db.close()


def list_questions(username: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return recorded questions. If `username` is provided, filter by user."""
    db = SessionLocal()
    try:
        query = db.query(Question)
        if username:
            query = query.filter(Question.username == username)
        
        questions = query.all()
        
        # Convert to dicts
        results = []
        for q in questions:
            results.append({
                "id": q.id,
                "username": q.username,
                "question": q.question,
                "timestamp": q.timestamp.isoformat() if q.timestamp else None,
                "tags": q.tags,
                "agent_steps": q.agent_steps,
                "final_answer": q.final_answer,
                "used_mcp": q.used_mcp,
                "mcp_results": q.mcp_results
            })
        return results
    finally:
        db.close()


def stats_summary() -> Dict[str, Any]:
    """Return simple aggregated stats useful for visualizations."""
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        total = len(questions)
        by_user: Dict[str, int] = {}
        by_tag: Dict[str, int] = {}
        mcp_usage: Dict[str, int] = {}

        for q in questions:
            user = q.username or "unknown"
            by_user[user] = by_user.get(user, 0) + 1
            
            for tag in (q.tags or []):
                by_tag[tag] = by_tag.get(tag, 0) + 1
            
            mcp = q.used_mcp
            if mcp:
                mcp_usage[mcp] = mcp_usage.get(mcp, 0) + 1

        return {
            "total_questions": total,
            "by_user": by_user,
            "by_tag": by_tag,
            "mcp_usage": mcp_usage,
        }
    finally:
        db.close()
