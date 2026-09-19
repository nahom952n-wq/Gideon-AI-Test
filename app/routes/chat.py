"""AI chat assistant routes."""

import logging
import markdown
import bleach
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from ..models import ChatSession, ChatMessage
from ..extensions import db
from ..services.chat_service import ChatService
from .auth import login_required, current_user
from .auth import login_required, current_user

bp = Blueprint("chat", __name__, url_prefix="/chat")
log = logging.getLogger("scholarmind.app")
chat_service = ChatService()

# Safe HTML tags allowed in markdown output
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'code', 'pre', 'blockquote',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dl', 'dt', 'dd',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'span', 'div'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title'],
    'code': ['class'],
    'pre': ['class'],
    'span': ['class'],
    'div': ['class']
}


def markdown_to_html(text: str) -> str:
    """Convert markdown to safe HTML."""
    if not text:
        return ""
    html = markdown.markdown(text, extensions=["tables", "fenced_code"])
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
    )


@bp.route("/")
@login_required
def index():
    sessions = ChatSession.query.filter_by(user_id=current_user().id).order_by(ChatSession.last_active_at.desc()).limit(10).all()
    requested_id = request.args.get("session_id", type=int)
    active_session = (
        ChatSession.query.filter_by(id=requested_id, user_id=current_user().id).first()
        if requested_id
        else (sessions[0] if sessions else None)
    )
    messages = []
    if active_session:
        messages = active_session.messages.order_by(ChatMessage.created_at).all()
    return render_template(
        "chat/index.html", 
        sessions=sessions, 
        active_session=active_session, 
        messages=messages,
        markdown_to_html=markdown_to_html,
    )


@bp.route("/send", methods=["POST"])
@login_required
def send():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    session_id = data.get("session_id")

    if not user_message:
        return jsonify({"error": "Message is required."}), 400

    if session_id:
        session = ChatSession.query.filter_by(id=session_id, user_id=current_user().id).first()
    else:
        session = None

    if not session:
        session = ChatSession(user_id=current_user().id)
        db.session.add(session)
        db.session.flush()

    user_msg = ChatMessage(session_id=session.id, role="user", content=user_message)
    db.session.add(user_msg)

    response_text, source = chat_service.respond(user_message, session.id)

    assistant_msg = ChatMessage(
        session_id=session.id, role="assistant", content=response_text, source=source
    )
    db.session.add(assistant_msg)

    from datetime import datetime
    session.last_active_at = datetime.utcnow()
    if not session.title and len(user_message) > 0:
        session.title = user_message[:60]

    db.session.commit()

    # Return rendered HTML version of response for display
    response_html = markdown_to_html(response_text)
    
    return jsonify({
        "session_id": session.id,
        "response": response_text,
        "response_html": response_html,
        "source": source,
    })


@bp.route("/<int:session_id>/delete", methods=["POST"])
@login_required
def delete_session(session_id: int):
    """Delete a chat session and all its messages."""
    session = ChatSession.query.filter_by(id=session_id, user_id=current_user().id).first_or_404()
    
    # Delete all messages in the session
    ChatMessage.query.filter_by(session_id=session_id).delete()
    
    # Delete the session
    db.session.delete(session)
    db.session.commit()
    
    flash("Chat session deleted.", "info")
    
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True})
    
    # Otherwise redirect to chat index
    return redirect(url_for("chat.index"))
