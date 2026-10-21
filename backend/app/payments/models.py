"""Payments tables (module 21). Policies and grants are in migration 0016. Every amount is a bigint of minor units with
its currency next to it; every reference between these tables carries the workspace id too, so a row can never point
into another workspace; provider rows hold the provider's ids only (an account, a customer, a payment method, a
payment, a refund), never card data or a secret."""
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
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_LIST, within, workspace

PROVIDERS = ("stripe", "fake")
ACCOUNT_STATUSES = ("pending", "active", "restricted", "disconnected")
PRODUCT_KINDS = ("service", "physical", "digital")
PRICE_TYPES = ("one_time", "recurring")
SCHEMES = ("fixed", "tiered")
TIERS_MODES = ("graduated", "volume")
INTERVALS = ("day", "week", "month", "year")
DURATIONS = ("once", "repeating", "forever")
INVOICE_STATUSES = ("draft", "open", "paid", "void", "uncollectible")
BILLING_REASONS = ("manual", "payment_link", "subscription_create", "subscription_cycle", "subscription_update")
SUBSCRIPTION_STATUSES = ("incomplete", "incomplete_expired", "trialing", "active", "past_due", "unpaid", "canceled")
COLLECTIONS = ("charge_automatically", "send_invoice")
AFTER_RETRIES = ("cancel", "unpaid")
PAYMENT_STATUSES = ("pending", "processing", "succeeded", "failed", "canceled")
PAYMENT_PROVIDERS = (*PROVIDERS, "manual")
METHODS = ("card", "cash", "check", "bank_transfer", "other")
REFUND_STATUSES = ("pending", "succeeded", "failed")


def one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


def money(**kw) -> Mapped[int]:
    return mapped_column(BigInteger, default=0, server_default="0", **kw)


def contact_fk(column: str = "contact_id") -> ForeignKeyConstraint:
    """A contact is trashed, not deleted, by the app; if one is purged the money rows keep their history."""
    return ForeignKeyConstraint([column, "workspace_id"], ["records.id", "records.workspace_id"],
                                ondelete=f"SET NULL ({column})")


def maybe(column: str, table: str) -> ForeignKeyConstraint:
    """An optional reference within the workspace: cleared, not cascaded, when the target goes."""
    return ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                ondelete=f"SET NULL ({column})")


class PaymentAccount(Base):
    """The workspace's account at a provider (its Stripe Connect account id). One per workspace."""
    __tablename__ = "payment_accounts"
    __table_args__ = (UniqueConstraint("workspace_id"), UniqueConstraint("provider", "account_id"),
                      one_of("provider", PROVIDERS, "ck_payment_accounts_provider"),
                      one_of("status", ACCOUNT_STATUSES, "ck_payment_accounts_status"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    provider: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    details_submitted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    livemode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    display_name: Mapped[str | None] = mapped_column(String(200))
    connected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class PaymentSettings(Base):
    """Per workspace: the default currency, invoice numbering and terms, and the dunning rules of subscriptions."""
    __tablename__ = "payment_settings"
    __table_args__ = (one_of("after_retries", AFTER_RETRIES, "ck_payment_settings_after"),
                      CheckConstraint("next_invoice_number >= 1", name="ck_payment_settings_number"),
                      CheckConstraint("invoice_due_days BETWEEN 0 AND 365", name="ck_payment_settings_due"),
                      CheckConstraint("cardinality(retry_days) <= 8", name="ck_payment_settings_retries"))

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    default_currency: Mapped[str] = mapped_column(String(3), default="usd", server_default="usd")
    invoice_prefix: Mapped[str] = mapped_column(String(20), default="INV-", server_default="INV-")
    next_invoice_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    invoice_due_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    retry_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [1, 3, 5],
                                                  server_default=text("'{1,3,5}'"))
    after_retries: Mapped[str] = mapped_column(String(6), default="cancel", server_default="cancel")
    business_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    business_details: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    invoice_footer: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    updated_at: Mapped[datetime] = created()


class TaxRate(Base):
    __tablename__ = "tax_rates"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),
                      CheckConstraint("percentage_bp BETWEEN 0 AND 10000", name="ck_tax_rates_percentage"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    percentage_bp: Mapped[int] = mapped_column(Integer)  # 825 is 8.25 %
    inclusive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    region: Mapped[str] = mapped_column(String(100), default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), one_of("kind", PRODUCT_KINDS, "ck_products_kind"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(10), default="service", server_default="service")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class Price(Base):
    """What a product costs, in one currency. The amounts never change once saved (invoices and subscriptions point at
    it); a new price replaces an old one, which is archived (`active` false)."""
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), within("product_id", "products"), maybe("tax_rate_id", "tax_rates"),
        one_of("type", PRICE_TYPES, "ck_prices_type"), one_of("scheme", SCHEMES, "ck_prices_scheme"),
        CheckConstraint("scheme <> 'fixed' OR (unit_amount IS NOT NULL AND unit_amount >= 0)", name="ck_prices_fixed"),
        CheckConstraint("scheme <> 'tiered' OR tiers_mode IN ('graduated', 'volume')", name="ck_prices_tiered"),
        CheckConstraint("(type = 'recurring') = (interval IS NOT NULL)", name="ck_prices_interval"),
        CheckConstraint("interval IS NULL OR interval IN ('day', 'week', 'month', 'year')", name="ck_prices_intervals"),
        CheckConstraint("interval_count BETWEEN 1 AND 365 AND trial_days BETWEEN 0 AND 730", name="ck_prices_counts"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    product_id: Mapped[uuid.UUID]
    nickname: Mapped[str] = mapped_column(String(100), default="", server_default="")
    currency: Mapped[str] = mapped_column(String(3))
    type: Mapped[str] = mapped_column(String(9))
    scheme: Mapped[str] = mapped_column(String(6), default="fixed", server_default="fixed")
    unit_amount: Mapped[int | None] = mapped_column(BigInteger)
    tiers: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    tiers_mode: Mapped[str | None] = mapped_column(String(9))
    interval: Mapped[str | None] = mapped_column(String(5))
    interval_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    trial_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tax_rate_id: Mapped[uuid.UUID | None]
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created()


Index("ix_prices_product", Price.product_id)


class Coupon(Base):
    """A percentage or a fixed amount off, by code, on invoices, payment links and subscriptions alike."""
    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), UniqueConstraint("workspace_id", "code_norm"),
        one_of("duration", DURATIONS, "ck_coupons_duration"),
        CheckConstraint("(percent_off_bp IS NULL) <> (amount_off IS NULL)", name="ck_coupons_kind"),
        CheckConstraint("percent_off_bp IS NULL OR percent_off_bp BETWEEN 1 AND 10000", name="ck_coupons_percent"),
        CheckConstraint("amount_off IS NULL OR (amount_off > 0 AND currency IS NOT NULL)", name="ck_coupons_amount"),
        CheckConstraint("(duration = 'repeating') = (duration_months IS NOT NULL)", name="ck_coupons_months"),
        CheckConstraint("max_redemptions IS NULL OR times_redeemed <= max_redemptions", name="ck_coupons_limit"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(40))
    code_norm: Mapped[str] = mapped_column(String(40))  # upper case: codes match whatever the case typed
    percent_off_bp: Mapped[int | None] = mapped_column(Integer)
    amount_off: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    duration: Mapped[str] = mapped_column(String(9), default="once", server_default="once")
    duration_months: Mapped[int | None] = mapped_column(Integer)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    times_redeemed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    once_per_contact: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    price_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default=text("'{}'"))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"
    __table_args__ = (within("coupon_id", "coupons"), contact_fk(), within("invoice_id", "invoices"),
                      within("subscription_id", "subscriptions"),
                      UniqueConstraint("coupon_id", "invoice_id"), UniqueConstraint("coupon_id", "subscription_id"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    coupon_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID | None]
    invoice_id: Mapped[uuid.UUID | None]
    subscription_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()


class PaymentCustomer(Base):
    """A contact as a customer of the workspace's provider account, with the card kept for off-session charges."""
    __tablename__ = "payment_customers"
    __table_args__ = (contact_fk(), UniqueConstraint("contact_id", "account_id"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    contact_id: Mapped[uuid.UUID | None]
    provider: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[str] = mapped_column(String(255))
    customer_id: Mapped[str] = mapped_column(String(255))
    payment_method_id: Mapped[str | None] = mapped_column(String(255))
    card_brand: Mapped[str | None] = mapped_column(String(20))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class Subscription(Base):
    """A contact paying a recurring price. `cycle` goes up whenever a period starts or the state changes, and every job
    about the subscription carries the cycle it was scheduled for, so a job that is late or runs twice does nothing."""
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), contact_fk(), within("price_id", "prices"),
        maybe("coupon_id", "coupons"),
        one_of("status", SUBSCRIPTION_STATUSES, "ck_subscriptions_status"),
        one_of("collection", COLLECTIONS, "ck_subscriptions_collection"),
        CheckConstraint("quantity BETWEEN 1 AND 100000", name="ck_subscriptions_quantity"),
        CheckConstraint("credit_balance >= 0", name="ck_subscriptions_credit"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    contact_id: Mapped[uuid.UUID | None]
    price_id: Mapped[uuid.UUID]
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(18))
    collection: Mapped[str] = mapped_column(String(20), default="charge_automatically",
                                            server_default="charge_automatically")
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    anchor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # periods are counted from here
    periods: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # periods started since the anchor
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cycle: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    coupon_id: Mapped[uuid.UUID | None]
    coupon_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # None with a coupon: forever
    credit_balance: Mapped[int] = money()  # owed to the customer (a downgrade's credit), taken off the next invoice
    latest_invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_subscriptions_contact", Subscription.contact_id)


class Invoice(Base):
    """A bill to a contact. A draft has no number; sending it (or paying a checkout) gives it the next number of the
    workspace, so issued numbers have no gaps. Totals are kept as worked out by app/payments/money.py when the lines
    were last saved; they never change after the invoice is issued."""
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), UniqueConstraint("workspace_id", "number"), contact_fk(),
        within("subscription_id", "subscriptions"), maybe("payment_link_id", "payment_links"),
        maybe("coupon_id", "coupons"),
        one_of("status", INVOICE_STATUSES, "ck_invoices_status"),
        one_of("billing_reason", BILLING_REASONS, "ck_invoices_reason"),
        CheckConstraint("total >= 0 AND amount_paid >= 0 AND amount_paid <= total", name="ck_invoices_amounts"),
        CheckConstraint("status = 'draft' OR status = 'void' OR billing_reason = 'payment_link' OR number IS NOT NULL",
                        name="ck_invoices_number"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    number: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(13), default="draft", server_default="draft")
    billing_reason: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")
    contact_id: Mapped[uuid.UUID | None]
    currency: Mapped[str] = mapped_column(String(3))
    subscription_id: Mapped[uuid.UUID | None]
    payment_link_id: Mapped[uuid.UUID | None]
    coupon_id: Mapped[uuid.UUID | None]
    subtotal: Mapped[int] = money()
    discount: Mapped[int] = money()
    tax: Mapped[int] = money()
    credit_applied: Mapped[int] = money()
    total: Mapped[int] = money()
    amount_paid: Mapped[int] = money()
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # an unpaid checkout lapses then
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    memo: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    footer: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # charges tried (dunning)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_invoices_contact", Invoice.contact_id)
Index("ix_invoices_subscription", Invoice.subscription_id)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (within("invoice_id", "invoices"), maybe("price_id", "prices"), maybe("tax_rate_id", "tax_rates"),
                      CheckConstraint("quantity BETWEEN 1 AND 100000", name="ck_invoice_lines_quantity"),
                      CheckConstraint("tax_bp BETWEEN 0 AND 10000", name="ck_invoice_lines_tax"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    invoice_id: Mapped[uuid.UUID]
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    price_id: Mapped[uuid.UUID | None]
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    unit_amount: Mapped[int] = mapped_column(BigInteger)  # negative for a credit
    amount: Mapped[int] = mapped_column(BigInteger)
    discount: Mapped[int] = money()
    tax_rate_id: Mapped[uuid.UUID | None]
    tax_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    tax_bp: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    tax: Mapped[int] = money()
    total: Mapped[int] = mapped_column(BigInteger)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proration: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


Index("ix_invoice_lines_invoice", InvoiceLine.invoice_id, InvoiceLine.position)


class PaymentLink(Base):
    """A shareable checkout of fixed items (`items`: [{price_id, quantity, adjustable, min, max}]); the public key
    in its URL is public by design, since the link is shared."""
    __tablename__ = "payment_links"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), UniqueConstraint("public_key"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(200))
    public_key: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    items: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    allow_coupons: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    collect_phone: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    success_message: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    redirect_url: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class Payment(Base):
    """One attempt to take money (a transaction): online through a provider, or recorded by hand (cash, cheque).
    `attempt_key` is unique per workspace and derived from what the attempt is for, so a retried job finds its own row
    instead of charging again; `fulfilled_at` is set by the one UPDATE that applies a success to its invoice."""
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), UniqueConstraint("workspace_id", "attempt_key"), contact_fk(),
        within("invoice_id", "invoices"), maybe("subscription_id", "subscriptions"),
        one_of("provider", PAYMENT_PROVIDERS, "ck_payments_provider"),
        one_of("status", PAYMENT_STATUSES, "ck_payments_status"), one_of("method", METHODS, "ck_payments_method"),
        CheckConstraint("amount > 0 AND amount_refunded >= 0 AND amount_refunded <= amount",
                        name="ck_payments_amounts"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    contact_id: Mapped[uuid.UUID | None]
    invoice_id: Mapped[uuid.UUID | None]
    subscription_id: Mapped[uuid.UUID | None]
    provider: Mapped[str] = mapped_column(String(10))
    account_id: Mapped[str | None] = mapped_column(String(255))
    provider_payment_id: Mapped[str | None] = mapped_column(String(255))
    checkout_session_id: Mapped[str | None] = mapped_column(String(255))
    checkout_url: Mapped[str | None] = mapped_column(String(4000))
    attempt_key: Mapped[str] = mapped_column(String(120))
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    amount_refunded: Mapped[int] = money()
    method: Mapped[str] = mapped_column(String(13), default="card", server_default="card")
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_payments_invoice", Payment.invoice_id)
Index("ix_payments_contact", Payment.contact_id)
Index("uq_payments_provider_payment", Payment.provider, Payment.provider_payment_id, unique=True,
      postgresql_where=text("provider_payment_id IS NOT NULL"))


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), within("payment_id", "payments"),
                      one_of("status", REFUND_STATUSES, "ck_refunds_status"),
                      CheckConstraint("amount > 0", name="ck_refunds_amount"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    payment_id: Mapped[uuid.UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[str] = mapped_column(String(9), default="pending", server_default="pending")
    provider_refund_id: Mapped[str | None] = mapped_column(String(255))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_refunds_payment", Refund.payment_id)
Index("uq_refunds_provider", Refund.provider_refund_id, unique=True,
      postgresql_where=text("provider_refund_id IS NOT NULL"))


class PaymentEvent(Base):
    """Provider webhook events already applied, by the provider's event id: a replay finds its row and changes
    nothing. Only the id and type are kept, not the payload."""
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    provider: Mapped[str] = mapped_column(String(10))
    event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = created()


class CheckoutAttempt(Base):
    """Public checkouts started, per link or invoice and visitor (a keyed hash of their address), for the rate limit."""
    __tablename__ = "checkout_attempts"

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    target: Mapped[str] = mapped_column(String(64))
    ip_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()


Index("ix_checkout_attempts_who", CheckoutAttempt.target, CheckoutAttempt.ip_hash, CheckoutAttempt.created_at)
