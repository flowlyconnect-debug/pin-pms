from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.audit import record as audit_record
from app.comments.models import Comment
from app.extensions import db
from app.guests.models import Guest
from app.notifications import services as notification_service
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User, UserRole

TARGET_TYPES = ("guest", "reservation", "property")
MENTION_RE = re.compile(r"@([A-Za-z0-9._-]{2,64})")
RESOURCE_PATH = {"guest": "guests", "reservation": "reservations", "property": "properties"}


@dataclass
class CommentServiceError(Exception):
    code: str
    message: str
    status: int


class CommentService:
    @staticmethod
    def _resolve_target(organization_id: int, target_type: str, target_id: int) -> None:
        if target_type == "guest":
            row = Guest.query.filter_by(id=target_id, organization_id=organization_id).first()
        elif target_type == "property":
            row = Property.query.filter_by(id=target_id, organization_id=organization_id).first()
        elif target_type == "reservation":
            row = (
                Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
                .join(Property, Unit.property_id == Property.id)
                .filter(Reservation.id == target_id, Property.organization_id == organization_id)
                .first()
            )
        else:
            raise CommentServiceError("validation_error", "Invalid target_type.", 400)
        if row is None:
            raise CommentServiceError("not_found", "Target resource not found in organization.", 404)

    @staticmethod
    def _handle_mentions(*, organization_id: int, actor_user_id: int, body: str, target_type: str, target_id: int) -> None:
        usernames = {m.group(1).strip().lower() for m in MENTION_RE.finditer(body or "") if m.group(1).strip()}
        if not usernames:
            return
        actor = User.query.filter_by(id=actor_user_id, organization_id=organization_id).first()
        for username in usernames:
            user = User.query.filter(
                User.organization_id == organization_id,
                (User.email.ilike(f"{username}@%")) | (User.email.ilike(username)),
            ).first()
            if user is None or user.id == actor_user_id:
                continue
            title = "Sinut mainittiin kommentissa"
            actor_email = actor.email if actor is not None else "Kollega"
            notification_service.create(
                organization_id=organization_id,
                type="comment.mentioned",
                title=title,
                body=f"{actor_email} mainitsi sinut kohteessa {target_type} #{target_id}.",
                link=f"/admin/{RESOURCE_PATH[target_type]}/{target_id}",
                user_id=user.id,
            )

    @staticmethod
    def create(
        organization_id: int,
        target_type: str,
        target_id: int,
        author_user_id: int,
        body: str,
        is_internal: bool = True,
    ) -> Comment:
        CommentService._resolve_target(organization_id, target_type, target_id)
        cleaned = (body or "").strip()
        if not cleaned:
            raise CommentServiceError("validation_error", "Comment body is required.", 400)
        comment = Comment(
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            author_user_id=author_user_id,
            body=cleaned,
            is_internal=bool(is_internal),
        )
        db.session.add(comment)
        db.session.flush()
        audit_record(
            "comment.created",
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            metadata={"comment_id": comment.id},
            commit=False,
        )
        CommentService._handle_mentions(
            organization_id=organization_id,
            actor_user_id=author_user_id,
            body=cleaned,
            target_type=target_type,
            target_id=target_id,
        )
        return comment

    @staticmethod
    def edit(comment_id: int, actor_user_id: int, body: str) -> Comment:
        comment = Comment.query.get(comment_id)
        if comment is None:
            raise CommentServiceError("not_found", "Comment not found.", 404)
        if comment.author_user_id != actor_user_id:
            raise CommentServiceError("forbidden", "Only the author can edit comment.", 403)
        if datetime.utcnow() - comment.created_at > timedelta(minutes=15):
            raise CommentServiceError("forbidden", "Edit window has expired.", 403)
        cleaned = (body or "").strip()
        if not cleaned:
            raise CommentServiceError("validation_error", "Comment body is required.", 400)
        comment.body = cleaned
        comment.edited_at = datetime.utcnow()
        db.session.flush()
        audit_record(
            "comment.edited",
            organization_id=comment.organization_id,
            target_type=comment.target_type,
            target_id=comment.target_id,
            metadata={"comment_id": comment.id},
            commit=False,
        )
        return comment

    @staticmethod
    def delete(comment_id: int, actor_user_id: int) -> None:
        comment = Comment.query.get(comment_id)
        if comment is None:
            raise CommentServiceError("not_found", "Comment not found.", 404)
        actor = User.query.get(actor_user_id)
        if actor is None or actor.organization_id != comment.organization_id:
            raise CommentServiceError("forbidden", "Forbidden.", 403)
        is_admin = actor.role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}
        if not is_admin and comment.author_user_id != actor_user_id:
            raise CommentServiceError("forbidden", "Forbidden.", 403)
        audit_record(
            "comment.deleted",
            organization_id=comment.organization_id,
            target_type=comment.target_type,
            target_id=comment.target_id,
            metadata={"comment_id": comment.id},
            commit=False,
        )
        db.session.delete(comment)
        db.session.flush()

    @staticmethod
    def list_for_target(
        organization_id: int, target_type: str, target_id: int, include_internal: bool = True
    ) -> list[Comment]:
        CommentService._resolve_target(organization_id, target_type, target_id)
        query = Comment.query.filter_by(
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
        )
        if not include_internal:
            query = query.filter(Comment.is_internal.is_(False))
        return query.order_by(Comment.created_at.desc(), Comment.id.desc()).all()
