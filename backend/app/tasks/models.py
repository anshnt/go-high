"""The tasks table (migration 0009). A task may link to any record; references carry the workspace id, like the record
engine's, so a task can never point into another workspace."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import within, workspace

PRIORITIES = ("none", "low", "medium", "high")
STATUSES = ("open", "done")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        within("record_id", "records"),
        ForeignKeyConstraint(["parent_task_id", "workspace_id"], ["tasks.id", "tasks.workspace_id"]),
        ForeignKeyConstraint(["depends_on_task_id", "workspace_id"], ["tasks.id", "tasks.workspace_id"]),
        CheckConstraint("priority IN ('none', 'low', 'medium', 'high')", name="ck_tasks_priority"),
        CheckConstraint("status IN ('open', 'done')", name="ck_tasks_status"),
        CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name="ck_tasks_completed"),
        CheckConstraint("recurrence IS NULL OR due_at IS NOT NULL", name="ck_tasks_recurrence_due"),
        CheckConstraint("depends_on_task_id IS DISTINCT FROM id", name="ck_tasks_depends_self"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    # an all-day task is due on a date: due_at is midnight UTC of that date, whoever looks at it
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    priority: Mapped[str] = mapped_column(String(6), default="none", server_default="none")
    status: Mapped[str] = mapped_column(String(4), default="open", server_default="open")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_id: Mapped[uuid.UUID | None]
    recurrence: Mapped[str | None] = mapped_column(String(200))
    parent_task_id: Mapped[uuid.UUID | None]  # the first task of a recurring series
    depends_on_task_id: Mapped[uuid.UUID | None]
    position: Mapped[float] = mapped_column(DOUBLE_PRECISION, default=0, server_default="0")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_tasks_list", Task.workspace_id, Task.position, Task.id)
Index("ix_tasks_assignee", Task.workspace_id, Task.assignee_id, Task.due_at, postgresql_where=text("status = 'open'"))
Index("ix_tasks_record", Task.record_id, postgresql_where=Task.record_id.is_not(None))
Index("ix_tasks_parent", Task.parent_task_id, postgresql_where=Task.parent_task_id.is_not(None))
Index("ix_tasks_depends_on", Task.depends_on_task_id, postgresql_where=Task.depends_on_task_id.is_not(None))
