# core/session_singleton.py
from core.session import SessionCache

# Shared singleton instance
shared_session = SessionCache(ttl=300)
