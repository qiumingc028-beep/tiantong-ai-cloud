from backend.models import TaskCenterTask, User
from backend.task_center_ownership import (
    SESSION_USER_KEY,
    bind_session_task_ownership,
    bind_task_ownership,
)


def owner_db(test_db):
    db = test_db()
    bind_session_task_ownership(db, user=db.query(User).filter(User.username == "owner").one())
    return db


def bind_pending_tasks(db):
    owner = db.info[SESSION_USER_KEY]
    for task in tuple(db.new):
        if isinstance(task, TaskCenterTask):
            bind_task_ownership(db, task, user=owner)
