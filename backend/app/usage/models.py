"""The usage tables (migration 0013): a wallet per workspace, the append-only ledger behind it, top-ups through a
payment provider, and rate cards set by the organization. Money is integer micros (money.py). Policies, grants and the
trigger that keeps a wallet's balance equal to the sum of its ledger are in the migration."""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import workspace

MODES = ("prepaid", "postpaid")
KINDS = ("usage", "reversal", "topup", "adjustment")
TOPUP_STATUSES = ("pending", "succeeded", "failed")
TOPUP_TRIGGERS = ("manual", "auto")


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class Wallet(Base):
    """One per workspace, made on first use. `balance` is written only by the ledger trigger. `mode`, `credit_limit`
    and `currency` are the organization's (credit is the agency's risk); the alerts, auto-recharge and the monthly cap
    are the workspace's."""
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint(in_list("mode", MODES), name="ck_wallets_mode"),
        CheckConstraint("credit_limit IS NULL OR credit_limit >= 0", name="ck_wallets_credit_limit"),
        CheckConstraint("low_balance_at IS NULL OR low_balance_at >= 0", name="ck_wallets_low_balance_at"),
        CheckConstraint("monthly_cap IS NULL OR monthly_cap >= 0", name="ck_wallets_monthly_cap"),
        CheckConstraint("cap_alert_pct BETWEEN 1 AND 100", name="ck_wallets_cap_alert_pct"),
        CheckConstraint("NOT auto_recharge OR (recharge_below IS NOT NULL AND recharge_amount > 0)",
                        name="ck_wallets_auto_recharge"),
        CheckConstraint("recharge_below IS NULL OR recharge_below >= 0", name="ck_wallets_recharge_below"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    balance: Mapped[int] = mapped_column(BigInteger, server_default="0")
    mode: Mapped[str] = mapped_column(String(10), server_default="prepaid")
    credit_limit: Mapped[int | None] = mapped_column(BigInteger)  # postpaid: how far below zero; null: no limit
    low_balance_at: Mapped[int | None] = mapped_column(BigInteger)  # alert when the balance falls below this
    auto_recharge: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    recharge_below: Mapped[int | None] = mapped_column(BigInteger)
    recharge_amount: Mapped[int | None] = mapped_column(BigInteger)
    payment_method: Mapped[str | None] = mapped_column(String(200))  # the provider's token for a saved method
    monthly_cap: Mapped[int | None] = mapped_column(BigInteger)  # usage per calendar month (UTC); a hard stop
    cap_alert_pct: Mapped[int] = mapped_column(Integer, server_default="80")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class LedgerEntry(Base):
    """Append only: a request may insert and read, never change or delete. `amount` is signed (usage is negative, a
    top-up positive) and `balance_after` is filled in by the trigger, under the wallet's row lock."""
    __tablename__ = "usage_ledger"
    __table_args__ = (
        CheckConstraint(in_list("kind", KINDS), name="ck_usage_ledger_kind"),
        CheckConstraint("quantity >= 0 AND cost >= 0 AND price >= 0 AND unit_cost >= 0 AND unit_price >= 0",
                        name="ck_usage_ledger_positive"),
        CheckConstraint("(kind IN ('usage', 'reversal')) = (meter IS NOT NULL)", name="ck_usage_ledger_meter"),
        CheckConstraint("kind <> 'usage' OR amount = -price", name="ck_usage_ledger_usage_amount"),
        CheckConstraint("kind <> 'reversal' OR amount = price", name="ck_usage_ledger_reversal_amount"),
        CheckConstraint("kind <> 'topup' OR amount > 0", name="ck_usage_ledger_topup_amount"),
        ForeignKeyConstraint(["reverses_id", "workspace_id"], ["usage_ledger.id", "usage_ledger.workspace_id"]),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    kind: Mapped[str] = mapped_column(String(12))
    meter: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    unit_cost: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    unit_price: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cost: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")  # what it cost the platform
    price: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")  # what the workspace is charged
    amount: Mapped[int] = mapped_column(BigInteger)  # the change to the balance
    balance_after: Mapped[int] = mapped_column(BigInteger, server_default="0")  # set by the trigger
    currency: Mapped[str] = mapped_column(String(3))
    rate_card_id: Mapped[uuid.UUID | None]  # the card that priced it; kept when the card is deleted
    source: Mapped[str] = mapped_column(String(20))  # inbox, workflow, api, auto_recharge, admin
    subject_type: Mapped[str | None] = mapped_column(String(20))
    subject_id: Mapped[uuid.UUID | None]
    reverses_id: Mapped[uuid.UUID | None]
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(20), default="system", server_default="system")
    actor_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()


Index("uq_usage_ledger_id_workspace", LedgerEntry.id, LedgerEntry.workspace_id, unique=True)
Index("uq_usage_ledger_key", LedgerEntry.workspace_id, LedgerEntry.idempotency_key, unique=True,
      postgresql_where=text("idempotency_key IS NOT NULL"))
Index("ix_usage_ledger_list", LedgerEntry.workspace_id, LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
Index("ix_usage_ledger_meter", LedgerEntry.workspace_id, LedgerEntry.meter, LedgerEntry.created_at)
Index("ix_usage_ledger_subject", LedgerEntry.workspace_id, LedgerEntry.subject_id,
      postgresql_where=text("subject_id IS NOT NULL"))


class Topup(Base):
    """A charge to the workspace's payment method that credits the wallet once the provider accepts it."""
    __tablename__ = "wallet_topups"
    __table_args__ = (
        CheckConstraint(in_list("status", TOPUP_STATUSES), name="ck_wallet_topups_status"),
        CheckConstraint(in_list("trigger", TOPUP_TRIGGERS), name="ck_wallet_topups_trigger"),
        CheckConstraint("amount > 0", name="ck_wallet_topups_amount"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    trigger: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual")
    provider: Mapped[str] = mapped_column(String(20))
    provider_ref: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(300))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    ledger_id: Mapped[uuid.UUID | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("uq_wallet_topups_key", Topup.workspace_id, Topup.idempotency_key, unique=True,
      postgresql_where=text("idempotency_key IS NOT NULL"))
Index("ix_wallet_topups_list", Topup.workspace_id, Topup.created_at.desc(), Topup.id.desc())
# at most one automatic top-up in flight per workspace, so a burst of sends below the threshold charges the card once
Index("uq_wallet_topups_auto_pending", Topup.workspace_id, unique=True,
      postgresql_where=text("trigger = 'auto' AND status = 'pending'"))


class RateCard(Base):
    """What the organization charges for a meter, for the whole organization, one brand or one workspace (the most
    specific wins): a fixed `price` per unit, or a `markup_bp` over the cost (basis points; -10 000 is free). A card
    applies to wallets of its currency."""
    __tablename__ = "rate_cards"
    __table_args__ = (
        ForeignKeyConstraint(["brand_id", "org_id"], ["brands.id", "brands.org_id"], ondelete="CASCADE"),
        CheckConstraint("(price IS NULL) <> (markup_bp IS NULL)", name="ck_rate_cards_price_or_markup"),
        CheckConstraint("price IS NULL OR price >= 0", name="ck_rate_cards_price"),
        CheckConstraint("markup_bp IS NULL OR markup_bp BETWEEN -10000 AND 1000000", name="ck_rate_cards_markup"),
        CheckConstraint("brand_id IS NULL OR workspace_id IS NULL", name="ck_rate_cards_one_scope"),
    )

    id: Mapped[uuid.UUID] = pk()
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    brand_id: Mapped[uuid.UUID | None]
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    meter: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    price: Mapped[int | None] = mapped_column(BigInteger)
    markup_bp: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("uq_rate_cards_scope", RateCard.org_id, RateCard.brand_id, RateCard.workspace_id, RateCard.meter,
      RateCard.currency, unique=True, postgresql_nulls_not_distinct=True)
