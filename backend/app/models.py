"""Tenancy and auth tables: Organization > Brand > Workspace, users and their memberships, sessions.
Row Level Security lives in migration 0002; new workspace tables follow the same pattern (see README)."""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


def created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created()


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("id", "org_id"),)

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created()


class Workspace(Base):
    __tablename__ = "workspaces"
    # the brand must belong to the same org as the workspace
    __table_args__ = (ForeignKeyConstraint(["brand_id", "org_id"], ["brands.id", "brands.org_id"], ondelete="CASCADE"),)

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    brand_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="ck_users_email_lower"),)

    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(300))  # null: magic-link-only user
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set by the first magic link
    created_at: Mapped[datetime] = created()


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_org_members_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = created()


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_members_role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = created()


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex; the token itself is never stored
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MagicLink(Base):
    __tablename__ = "magic_links"

    id: Mapped[uuid.UUID] = pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    """One row per failed sign-in, for throttling."""
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_who", "email", "ip", "created_at"),)

    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(254))
    ip: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()
