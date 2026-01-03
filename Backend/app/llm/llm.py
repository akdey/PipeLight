"""LLM module using LangChain Google LLM (pluggable)."""
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_local_llm():
    """Initialize and return a LangChain Google LLM instance.
    
    Can be switched to other providers by updating the import.
    """
    try:
        # from langchain_google_genai import ChatGoogleGenerativeAI

        # if not settings.GOOGLE_API_KEY:
        #     logger.warning("GOOGLE_API_KEY not set; LLM will fail. Set it in .env")
        # llm = ChatGoogleGenerativeAI(
        #     model="gemini-2.5-flash",
        #     api_key=settings.GOOGLE_API_KEY,
        #     temperature=0.7,
        # )
        # logger.info("Initialized LangChain Google LLM")
        # return llm

        from langchain_groq import ChatGroq

        groq_api_key = settings.GROQ_API_KEY
        if not groq_api_key:
            logger.warning("GROQ_API_KEY not set. Please ensure it is set in your environment.")

        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=groq_api_key,
            temperature=0.7,
        )
        logger.info("Initialized LangChain Groq LLM")
        return llm
    except Exception as e:
        logger.error("Failed to initialize LLM: %s", e)
        raise


_default_llm: Optional[object] = None


def get_llm():
    """Get singleton LLM instance."""
    global _default_llm
    if _default_llm is None:
        _default_llm = get_local_llm()
    return _default_llm
