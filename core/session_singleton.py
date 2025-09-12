# core/session_singleton.py
from core.session import SessionCache
from core.session_manager import SessionManager

# Shared singleton instance
session_manager = SessionManager()
shared_session = SessionCache(session_manager=session_manager)

