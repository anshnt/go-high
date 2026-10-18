"""Tenancy and auth tables: Organization > Brand > Workspace, users and their memberships, sessions.
Row Level Security lives in migration 0002; new workspace tables follow the same pattern (see README)."""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
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


SCOPES = ("all", "team", "own", "own_and_unassigned", "none")
EMPTY_ARRAY = text("'{}'")


class Role(Base):
    """A named set of capabilities for an organization (ADR 0004). Rules per object are in RoleObjectRule."""
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("org_id", "key"), UniqueConstraint("id", "org_id"))

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default=EMPTY_ARRAY)
    created_at: Mapped[datetime] = created()


class RoleObjectRule(Base):
    """What a role sees of one object (`*`: every object without a rule of its own): the records in scope and the
    fields it may not read or change."""
    __tablename__ = "role_object_rules"
    __table_args__ = (
        UniqueConstraint("role_id", "object_key"),
        ForeignKeyConstraint(["role_id", "org_id"], ["roles.id", "roles.org_id"], ondelete="CASCADE"),
        CheckConstraint("scope IN (" + ", ".join(f"'{s}'" for s in SCOPES) + ")", name="ck_role_object_rules_scope"),
    )

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    role_id: Mapped[uuid.UUID]
    object_key: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str] = mapped_column(String(20))
    hidden_fields: Mapped[list[str]] = mapped_column(ARRAY(String(63)), default=list, server_default=EMPTY_ARRAY)
    readonly_fields: Mapped[list[str]] = mapped_column(ARRAY(String(63)), default=list, server_default=EMPTY_ARRAY)


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (ForeignKeyConstraint(["role_id", "org_id"], ["roles.id", "roles.org_id"]),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = created()


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"))
    created_at: Mapped[datetime] = created()


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        ForeignKeyConstraint(["parent_team_id", "workspace_id"], ["teams.id", "teams.workspace_id"]),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    parent_team_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()


Index("ix_teams_name", Team.workspace_id, func.lower(Team.name), unique=True)


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (ForeignKeyConstraint(["team_id", "workspace_id"], ["teams.id", "teams.workspace_id"],
                                           ondelete="CASCADE"),)

    team_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = created()


Index("ix_team_members_user", TeamMember.user_id)


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
