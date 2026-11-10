"""Sanitize COMEXIO admin errors without importing Home Assistant UI components."""
from __future__ import annotations
import re

def safe_admin_reason(err: Exception) -> str:
    """Human-readable diagnostics without webhook IDs or credentials."""
    reason = str(err).replace('\r', ' ').replace('\n', ' ').strip()
    # read_config wraps low-level HTTP errors; recover only their status code,
    # never an exception URL or response body that could contain credentials.
    cause = err.__cause__
    status = getattr(cause, 'status', None)
    if isinstance(status, int) and status >= 100 and f'HTTP {status}' not in reason:
        reason += f' (HTTP {status})'
    elif isinstance(cause, TimeoutError):
        reason += ' (Zeitlimit bei COMEXIO-Anfrage)'
    reason = re.sub(r'(?i)(/api/webhook/)[^\s/?&#<>]+',
                    r'\1[geschuetzt]', reason)
    reason = re.sub(r'(?i)https?://[^\s<>]+', '[URL geschuetzt]', reason)
    reason = re.sub(r'(?i)\b(password|token|secret|api_key)\s*[:=]\s*[^\s,;]+',
                    r'\1=[geschuetzt]', reason)
    return (reason or 'COMEXIO lieferte keine Fehlerdetails')[:300]

