"""State manager for persisting chat sessions and messages using Postgres."""
from typing import Dict, Any, List

from app.core.logging import get_logger
from app.core.database import SessionLocal
from app.core.models import ChatMessage, ChatSession

logger = get_logger(__name__)


def save_message(session_id: str, role: str, text: str) -> Dict[str, Any]:
    """Save a chat message to the database."""
    db = SessionLocal()
    try:
        msg = ChatMessage(session_id=session_id, role=role, text=text)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        logger.info("Saved message session=%s role=%s", session_id, role)
        # Return dict matching original interface
        return {"session_id": msg.session_id, "role": msg.role, "text": msg.text}
    finally:
        db.close()


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    """Retrieve all messages for a session."""
    db = SessionLocal()
    try:
        msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()
        return [{"role": m.role, "text": m.text, "session_id": m.session_id} for m in msgs]
    finally:
        db.close()


def save_session_meta(session_id: str, meta: Dict[str, Any]) -> None:
    """Save session metadata."""
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if session:
            # Merge existing metadata with new meta
            current_meta = dict(session.meta_data or {})
            current_meta.update(meta)
            # Assigning a new dict detects change in some JSON types, but explicit update is safer
            session.meta_data = current_meta
        else:
            session = ChatSession(session_id=session_id, meta_data=meta)
            db.add(session)
        db.commit()
        logger.info("Saved session meta for %s", session_id)
    except Exception as e:
        logger.error("Failed to save session meta: %s", e)
    finally:
        db.close()


def get_session_meta(session_id: str) -> Dict[str, Any] | None:
    """Retrieve session metadata."""
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if session:
            data = {"session_id": session.session_id}
            data.update(session.meta_data or {})
            return data
        return None
    finally:
        db.close()
