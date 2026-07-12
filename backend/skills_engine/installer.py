from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from .models import Skill
from .service import disable_skill, enable_skill, install_skill


def install_skill_version(db: Session, skill: Skill, payload, user: User):
    return install_skill(db, skill, payload, user)


def enable_skill_installation(db: Session, skill: Skill, installation, user: User):
    return enable_skill(db, skill, installation, user)


def disable_skill_installation(db: Session, skill: Skill, installation, user: User):
    return disable_skill(db, skill, installation, user)
