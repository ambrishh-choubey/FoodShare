"""HTTP layer only. Login is optional (visitors get general help); what a
person can learn about is decided by their role on the server."""
from flask import Blueprint, g, request

from responses import fail, ok
from services import ServiceError

from . import service

bp = Blueprint("chatbot", __name__, url_prefix="/api/v1/chatbot")


@bp.errorhandler(ServiceError)
def handle_service_error(err):
    response, status = fail(err.code, err.message, err.status)
    if err.retry_after:
        response.headers["Retry-After"] = str(err.retry_after)
    return response, status


def _client_key():
    return f"user:{g.user.id}" if g.user else f"ip:{request.remote_addr}"


@bp.get("/start")
def start():
    """Welcome text and suggested questions for the current role."""
    return ok(service.start(g.user))


@bp.post("/message")
def message():
    """CSRF is enforced for every POST by security.init_security."""
    body = request.get_json(silent=True)
    return ok(service.handle_message(g.user, body, _client_key()))
