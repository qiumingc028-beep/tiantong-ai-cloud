from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from .models import Skill
from .service import create_version, create_version_row


def publish_new_version(db: Session, skill: Skill, payload, user: User):
    return create_version(db, skill, payload, user)


def activate_existing_version(db: Session, skill: Skill, version, user: User):
    skill.current_version_id = version.id
    skill.status = "已发布"
    skill.enabled = True
    db.commit()
    db.refresh(skill)
    return skill
