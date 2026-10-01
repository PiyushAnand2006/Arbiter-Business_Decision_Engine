from __future__ import annotations

from fastapi import HTTPException, Request

from ..services.approvals import TransitionError
from ..services.arbiter import ArbiterService, NotFound


def get_svc(request: Request) -> ArbiterService:
    return request.app.state.svc


def http_errors(fn):
    """Map service exceptions to HTTP status codes."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFound as e:
            raise HTTPException(404, str(e))
        except TransitionError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
    return wrapper
