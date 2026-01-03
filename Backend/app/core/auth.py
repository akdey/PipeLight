import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from io import BytesIO
import jwt

from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core import vector_store
from app.core.logging import get_logger
from app.core.config import settings
from app.core.database import SessionLocal, engine, Base
from app.core.models import User, Doc

logger = get_logger(__name__)

# Verify tables exist on startup
Base.metadata.create_all(bind=engine)

def init_db():
    db = SessionLocal()
    try:
        # Check if users exist. If not, create defaults.
        # Note: In a real app, you might want to use Alembic for migrations instead of create_all.
        if db.query(User).count() == 0:
            pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            admin_hash = pwd_ctx.hash("Admin@123")
            user_hash = pwd_ctx.hash("User@123")
            
            admin = User(username="admin", password_hash=admin_hash, role="admin")
            user = User(username="user", password_hash=user_hash, role="user")
            
            db.add(admin)
            db.add(user)
            db.commit()
            logger.info("Created initial admin and user (Postgres/NeonDB).")
    except Exception as e:
        logger.error("DB Init failed: %s", e)
    finally:
        db.close()

# Initialize DB (create tables/users if needed)
init_db()


def extract_pdf_text(pdf_content: bytes) -> str:
    """Extract text from PDF content (bytes)."""
    try:
        from PyPDF2 import PdfReader
        
        pdf_file = BytesIO(pdf_content)
        pdf_reader = PdfReader(pdf_file)
        
        text = ""
        for page_num, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text()
            if page_text:
                text += f"\n--- Page {page_num + 1} ---\n{page_text}"
        
        if not text.strip():
            raise ValueError("No text could be extracted from PDF")
        
        logger.info("Extracted %d characters from PDF with %d pages", len(text), len(pdf_reader.pages))
        return text
        
    except ImportError:
        logger.error("PyPDF2 not installed. Install with: pip install PyPDF2")
        raise RuntimeError("PDF support not available. Please install PyPDF2.")
    except Exception as e:
        logger.error("Error extracting PDF text: %s", str(e))
        raise


def add_user(username: str, password: Optional[str] = None, role: Optional[str] = None) -> Dict[str, Any]:
    """Create a new user in Postgres."""
    db = SessionLocal()
    try:
        role = role or "user"
        password_hash = None
        if password:
            # truncate to 72 chars for bcrypt safety
            password_truncated = password[:72]
            pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
            password_hash = pwd_ctx.hash(password_truncated)
        
        new_user = User(username=username, password_hash=password_hash, role=role)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info("Created user %s with role %s", username, role)
        return {"username": new_user.username, "role": new_user.role, "id": new_user.id}
    finally:
        db.close()


def has_role(user: Dict[str, Any], required_role: str) -> bool:
    role = user.get("role")
    return role == required_role


def is_admin(user: Dict[str, Any]) -> bool:
    return has_role(user, "admin")


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Fetch user from Postgres and return as dict."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user:
            return {
                "username": user.username,
                "role": user.role,
                "password_hash": user.password_hash,
                "id": user.id
            }
        return None
    finally:
        db.close()


def verify_user_credentials(username: str, password: str) -> bool:
    user_data = get_user_by_username(username)
    if not user_data:
        return False
    stored = user_data.get("password_hash")
    if not stored:
        return False
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    try:
        password_truncated = password[:72]
        return pwd_ctx.verify(password_truncated, stored)
    except Exception:
        return False


# Document storage and search (Postgres + Vector Store)
def add_doc(title: str, content: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        new_doc = Doc(title=title, content=content)
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        logger.info("Added doc %s id=%s", title, new_doc.id)
        
        # Add to vector store if available
        try:
            if vector_store.is_ready():
                vector_store.add_document(
                    str(new_doc.id), 
                    title, 
                    content, 
                    metadata={"id": new_doc.id, "title": title}
                )
        except Exception as e:
            logger.warning("Failed to add doc to vector store: %s", e)
            
        return {"id": new_doc.id, "title": new_doc.title, "content": new_doc.content}
    finally:
        db.close()


def list_docs() -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        docs = db.query(Doc).all()
        return [{"id": d.id, "title": d.title, "content": d.content} for d in docs]
    finally:
        db.close()


def search_docs(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Search documents using Vector store first, falling back to basic SQL ILIKE."""
    # 1. Try vector request
    try:
        if vector_store.is_ready():
            vs_results = vector_store.query(query, top_k=top_k)
            out = []
            db = SessionLocal()
            try:
                for r in vs_results:
                    meta = r.get("metadata", {}) or {}
                    # Attempt to resolve ID
                    doc_id = meta.get("id") or r.get("id")
                    
                    db_doc = None
                    if doc_id:
                        # doc_id might be int or str in vector store, but int in DB
                        try:
                            tid = int(doc_id)
                            db_doc = db.query(Doc).filter(Doc.id == tid).first()
                        except ValueError:
                            pass
                    
                    entry = {}
                    if db_doc:
                        entry = {"id": db_doc.id, "title": db_doc.title, "content": db_doc.content}
                    else:
                        entry = {"id": doc_id, "title": meta.get("title"), "content": r.get("document")}
                    
                    entry["score"] = 1.0 - float(r.get("distance", 0.0)) if r.get("distance") is not None else 1.0
                    out.append(entry)
                return out[:top_k]
            finally:
                db.close()
    except Exception as e:
        logger.warning("Vector search failed, falling back to SQL: %s", e)

    # 2. Fallback: SQL ILIKE
    db = SessionLocal()
    try:
        # Simple search in title OR content
        # Note: Postgres ILIKE is case-insensitive
        q_str = f"%{query}%"
        matches = db.query(Doc).filter(
            or_(Doc.title.ilike(q_str), Doc.content.ilike(q_str))
        ).limit(top_k).all()
        
        # Simple scoring simulation
        return [{"id": d.id, "title": d.title, "content": d.content, "score": 0.5} for d in matches]
    finally:
        db.close()


# JWT Token management
def create_access_token(username: str, role: str) -> str:
    """Generate JWT access token containing username and single role."""
    expiration = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    payload = {
        "username": username,
        "role": role,
        "exp": expiration,
        "iat": datetime.utcnow()
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    logger.debug(f"Generated JWT token for user {username}")
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None
