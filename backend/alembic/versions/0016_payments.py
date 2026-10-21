"""payments: provider accounts, settings, tax rates, products and prices, coupons and redemptions, customers,
subscriptions, invoices and lines, payment links, payments, refunds, applied webhook events and checkout attempts; the
payments capabilities

Revision ID: 0016
Revises: 0012
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0012"
branch_labels = None
depends_on = None

# frozen: what each system role of an existing organization gains (a new organization gets them from
# app/roles_seed.py). Custom roles get nothing: an admin adds them to the roles that should have them.
ALL = ("payments.read", "payments.write", "payments.refund", "payments.manage")
GRANTS = {
    "owner": ALL,
    "admin": ALL,
    "manager": ("payments.read", "payments.write", "payments.refund"),
    "member": ("payments.read", "payments.write"),
    "viewer": ("payments.read",),
    "automation": ("payments.read", "payments.write"),
}


def tables() -> None:
    op.create_table(
        "checkout_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checkout_attempts_who", "checkout_attempts", ["target", "ip_hash", "created_at"], unique=False)
    op.create_table(
        "coupons",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("code_norm", sa.String(length=40), nullable=False),
        sa.Column("percent_off_bp", sa.Integer(), nullable=True),
        sa.Column("amount_off", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("duration", sa.String(length=9), server_default="once", nullable=False),
        sa.Column("duration_months", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("times_redeemed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("once_per_contact", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("price_ids", postgresql.ARRAY(sa.Uuid()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(duration = 'repeating') = (duration_months IS NOT NULL)", name="ck_coupons_months"),
        sa.CheckConstraint("duration IN ('once', 'repeating', 'forever')", name="ck_coupons_duration"),
        sa.CheckConstraint("(percent_off_bp IS NULL) <> (amount_off IS NULL)", name="ck_coupons_kind"),
        sa.CheckConstraint("amount_off IS NULL OR (amount_off > 0 AND currency IS NOT NULL)", name="ck_coupons_amount"),
        sa.CheckConstraint("max_redemptions IS NULL OR times_redeemed <= max_redemptions", name="ck_coupons_limit"),
        sa.CheckConstraint("percent_off_bp IS NULL OR percent_off_bp BETWEEN 1 AND 10000", name="ck_coupons_percent"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("workspace_id", "code_norm"),
    )
    op.create_table(
        "payment_accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="pending", nullable=False),
        sa.Column("charges_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("payouts_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("details_submitted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("livemode", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("connected_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("provider IN ('stripe', 'fake')", name="ck_payment_accounts_provider"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'restricted', 'disconnected')", name="ck_payment_accounts_status"
        ),
        sa.ForeignKeyConstraint(["connected_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "account_id"),
        sa.UniqueConstraint("workspace_id"),
    )
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "event_id"),
    )
    op.create_table(
        "payment_links",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("public_key", sa.String(length=40), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "items", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("allow_coupons", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("collect_phone", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("success_message", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("redirect_url", sa.String(length=2000), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("public_key"),
    )
    op.create_table(
        "payment_settings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("default_currency", sa.String(length=3), server_default="usd", nullable=False),
        sa.Column("invoice_prefix", sa.String(length=20), server_default="INV-", nullable=False),
        sa.Column("next_invoice_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("invoice_due_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column("retry_days", postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{1,3,5}'"), nullable=False),
        sa.Column("after_retries", sa.String(length=6), server_default="cancel", nullable=False),
        sa.Column("business_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("business_details", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("invoice_footer", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("after_retries IN ('cancel', 'unpaid')", name="ck_payment_settings_after"),
        sa.CheckConstraint("cardinality(retry_days) <= 8", name="ck_payment_settings_retries"),
        sa.CheckConstraint("invoice_due_days BETWEEN 0 AND 365", name="ck_payment_settings_due"),
        sa.CheckConstraint("next_invoice_number >= 1", name="ck_payment_settings_number"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), server_default="", nullable=False),
        sa.Column("kind", sa.String(length=10), server_default="service", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('service', 'physical', 'digital')", name="ck_products_kind"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("percentage_bp", sa.Integer(), nullable=False),
        sa.Column("inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("region", sa.String(length=100), server_default="", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("percentage_bp BETWEEN 0 AND 10000", name="ck_tax_rates_percentage"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(length=100), server_default="", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("type", sa.String(length=9), nullable=False),
        sa.Column("scheme", sa.String(length=6), server_default="fixed", nullable=False),
        sa.Column("unit_amount", sa.BigInteger(), nullable=True),
        sa.Column(
            "tiers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("tiers_mode", sa.String(length=9), nullable=True),
        sa.Column("interval", sa.String(length=5), nullable=True),
        sa.Column("interval_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("trial_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tax_rate_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(type = 'recurring') = (interval IS NOT NULL)", name="ck_prices_interval"),
        sa.CheckConstraint(
            "interval IS NULL OR interval IN ('day', 'week', 'month', 'year')", name="ck_prices_intervals"
        ),
        sa.CheckConstraint(
            "scheme <> 'fixed' OR (unit_amount IS NOT NULL AND unit_amount >= 0)", name="ck_prices_fixed"
        ),
        sa.CheckConstraint("scheme <> 'tiered' OR tiers_mode IN ('graduated', 'volume')", name="ck_prices_tiered"),
        sa.CheckConstraint("scheme IN ('fixed', 'tiered')", name="ck_prices_scheme"),
        sa.CheckConstraint("type IN ('one_time', 'recurring')", name="ck_prices_type"),
        sa.CheckConstraint(
            "interval_count BETWEEN 1 AND 365 AND trial_days BETWEEN 0 AND 730", name="ck_prices_counts"
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "workspace_id"], ["products.id", "products.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id", "workspace_id"],
            ["tax_rates.id", "tax_rates.workspace_id"],
            ondelete="SET NULL (tax_rate_id)",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_index("ix_prices_product", "prices", ["product_id"], unique=False)
    op.create_table(
        "payment_customers",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.Column("payment_method_id", sa.String(length=255), nullable=True),
        sa.Column("card_brand", sa.String(length=20), nullable=True),
        sa.Column("card_last4", sa.String(length=4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id", "workspace_id"], ["records.id", "records.workspace_id"], ondelete="SET NULL (contact_id)"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_id", "account_id"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=18), nullable=False),
        sa.Column("collection", sa.String(length=20), server_default="charge_automatically", nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anchor", sa.DateTime(timezone=True), nullable=True),
        sa.Column("periods", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cycle", sa.Integer(), server_default="0", nullable=False),
        sa.Column("coupon_id", sa.Uuid(), nullable=True),
        sa.Column("coupon_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credit_balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("latest_invoice_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "collection IN ('charge_automatically', 'send_invoice')", name="ck_subscriptions_collection"
        ),
        sa.CheckConstraint(
            "status IN ('incomplete', 'incomplete_expired', 'trialing', 'active', 'past_due', 'unpaid', 'canceled')",
            name="ck_subscriptions_status",
        ),
        sa.CheckConstraint("credit_balance >= 0", name="ck_subscriptions_credit"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 100000", name="ck_subscriptions_quantity"),
        sa.ForeignKeyConstraint(
            ["contact_id", "workspace_id"], ["records.id", "records.workspace_id"], ondelete="SET NULL (contact_id)"
        ),
        sa.ForeignKeyConstraint(
            ["coupon_id", "workspace_id"], ["coupons.id", "coupons.workspace_id"], ondelete="SET NULL (coupon_id)"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["price_id", "workspace_id"], ["prices.id", "prices.workspace_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_index("ix_subscriptions_contact", "subscriptions", ["contact_id"], unique=False)
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=13), server_default="draft", nullable=False),
        sa.Column("billing_reason", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("payment_link_id", sa.Uuid(), nullable=True),
        sa.Column("coupon_id", sa.Uuid(), nullable=True),
        sa.Column("subtotal", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("discount", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("tax", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credit_applied", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("amount_paid", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("memo", sa.String(length=2000), server_default="", nullable=False),
        sa.Column("footer", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "billing_reason IN ('manual', 'payment_link', 'subscription_create', 'subscription_cycle', "
            "'subscription_update')",
            name="ck_invoices_reason",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR status = 'void' OR billing_reason = 'payment_link' OR number IS NOT NULL",
            name="ck_invoices_number",
        ),
        sa.CheckConstraint("status IN ('draft', 'open', 'paid', 'void', 'uncollectible')", name="ck_invoices_status"),
        sa.CheckConstraint("total >= 0 AND amount_paid >= 0 AND amount_paid <= total", name="ck_invoices_amounts"),
        sa.ForeignKeyConstraint(
            ["contact_id", "workspace_id"], ["records.id", "records.workspace_id"], ondelete="SET NULL (contact_id)"
        ),
        sa.ForeignKeyConstraint(
            ["coupon_id", "workspace_id"], ["coupons.id", "coupons.workspace_id"], ondelete="SET NULL (coupon_id)"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["payment_link_id", "workspace_id"],
            ["payment_links.id", "payment_links.workspace_id"],
            ondelete="SET NULL (payment_link_id)",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "workspace_id"], ["subscriptions.id", "subscriptions.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("workspace_id", "number"),
    )
    op.create_index("ix_invoices_contact", "invoices", ["contact_id"], unique=False)
    op.create_index("ix_invoices_subscription", "invoices", ["subscription_id"], unique=False)
    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("coupon_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id", "workspace_id"], ["records.id", "records.workspace_id"], ondelete="SET NULL (contact_id)"
        ),
        sa.ForeignKeyConstraint(
            ["coupon_id", "workspace_id"], ["coupons.id", "coupons.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id", "workspace_id"], ["invoices.id", "invoices.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "workspace_id"], ["subscriptions.id", "subscriptions.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("coupon_id", "invoice_id"),
        sa.UniqueConstraint("coupon_id", "subscription_id"),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("unit_amount", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("discount", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("tax_rate_id", sa.Uuid(), nullable=True),
        sa.Column("tax_name", sa.String(length=100), server_default="", nullable=False),
        sa.Column("tax_bp", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tax_inclusive", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tax", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proration", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 100000", name="ck_invoice_lines_quantity"),
        sa.CheckConstraint("tax_bp BETWEEN 0 AND 10000", name="ck_invoice_lines_tax"),
        sa.ForeignKeyConstraint(
            ["invoice_id", "workspace_id"], ["invoices.id", "invoices.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["price_id", "workspace_id"], ["prices.id", "prices.workspace_id"], ondelete="SET NULL (price_id)"
        ),
        sa.ForeignKeyConstraint(
            ["tax_rate_id", "workspace_id"],
            ["tax_rates.id", "tax_rates.workspace_id"],
            ondelete="SET NULL (tax_rate_id)",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoice_lines_invoice", "invoice_lines", ["invoice_id", "position"], unique=False)
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=10), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_url", sa.String(length=4000), nullable=True),
        sa.Column("attempt_key", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("amount_refunded", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("method", sa.String(length=13), server_default="card", nullable=False),
        sa.Column("note", sa.String(length=500), server_default="", nullable=False),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("method IN ('card', 'cash', 'check', 'bank_transfer', 'other')", name="ck_payments_method"),
        sa.CheckConstraint("provider IN ('stripe', 'fake', 'manual')", name="ck_payments_provider"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed', 'canceled')", name="ck_payments_status"
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount_refunded >= 0 AND amount_refunded <= amount", name="ck_payments_amounts"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id", "workspace_id"], ["records.id", "records.workspace_id"], ondelete="SET NULL (contact_id)"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["invoice_id", "workspace_id"], ["invoices.id", "invoices.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "workspace_id"],
            ["subscriptions.id", "subscriptions.workspace_id"],
            ondelete="SET NULL (subscription_id)",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("workspace_id", "attempt_key"),
    )
    op.create_index("ix_payments_contact", "payments", ["contact_id"], unique=False)
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"], unique=False)
    op.create_index(
        "uq_payments_provider_payment",
        "payments",
        ["provider", "provider_payment_id"],
        unique=True,
        postgresql_where=sa.text("provider_payment_id IS NOT NULL"),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=True),
        sa.Column("note", sa.String(length=500), server_default="", nullable=False),
        sa.Column("status", sa.String(length=9), server_default="pending", nullable=False),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_refunds_status"),
        sa.CheckConstraint("amount > 0", name="ck_refunds_amount"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["payment_id", "workspace_id"], ["payments.id", "payments.workspace_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_index("ix_refunds_payment", "refunds", ["payment_id"], unique=False)
    op.create_index(
        "uq_refunds_provider",
        "refunds",
        ["provider_refund_id"],
        unique=True,
        postgresql_where=sa.text("provider_refund_id IS NOT NULL"),
    )


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# table: (privileges for gohigh_app, extra policies). Money is never deleted by a request: products, prices, coupons,
# tax rates and links are archived, invoices voided (only a draft is deleted, with its lines), payments and refunds
# only move forward, and the applied webhook events are append only. A provider webhook knows only the provider's
# account id: it finds the workspace in the system scope, then moves into it.
RLS = {
    "payment_accounts": ("SELECT, INSERT, UPDATE", [("system", "FOR SELECT USING (app_system())")]),
    "payment_settings": ("SELECT, INSERT, UPDATE", []),
    "tax_rates": ("SELECT, INSERT, UPDATE", []),
    "products": ("SELECT, INSERT, UPDATE", []),
    "prices": ("SELECT, INSERT, UPDATE (nickname, active)", []),
    "coupons": ("SELECT, INSERT, UPDATE", []),
    "payment_links": ("SELECT, INSERT, UPDATE", [("system", "FOR SELECT USING (app_system())")]),
    "payment_customers": ("SELECT, INSERT, UPDATE", []),
    "subscriptions": ("SELECT, INSERT, UPDATE", []),
    "invoices": ("SELECT, INSERT, UPDATE, DELETE", []),
    "invoice_lines": ("SELECT, INSERT, DELETE", []),
    "coupon_redemptions": ("SELECT, INSERT, DELETE", []),
    "payments": ("SELECT, INSERT, UPDATE", []),
    "refunds": ("SELECT, INSERT, UPDATE", []),
    "payment_events": ("SELECT, INSERT", []),
    "checkout_attempts": ("SELECT, INSERT, DELETE", []),
}


def upgrade() -> None:
    tables()
    for table, (privileges, policies) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
        for name, policy in policies:
            op.execute(f"CREATE POLICY {name} ON {table} {policy}")
    # roles have row level security forced on them: the system setting (what sign up uses) lets this change them
    op.execute("SELECT set_config('app.system', 'on', true)")
    connection = op.get_bind()
    for key, capabilities in GRANTS.items():
        connection.execute(
            sa.text(
                "UPDATE roles SET capabilities = capabilities || array(SELECT c FROM "
                "unnest(CAST(:caps AS text[])) c WHERE c <> ALL(capabilities)) "
                "WHERE is_system AND key = :key"
            ),
            {"caps": list(capabilities), "key": key},
        )


def downgrade() -> None:
    op.execute("SELECT set_config('app.system', 'on', true)")
    op.get_bind().execute(
        sa.text(
            "UPDATE roles SET capabilities = array(SELECT c FROM unnest(capabilities) c "
            "WHERE c <> ALL(CAST(:caps AS text[])))"
        ),
        {"caps": list(ALL)},
    )
    for table in (
        "refunds",
        "payments",
        "invoice_lines",
        "coupon_redemptions",
        "invoices",
        "subscriptions",
        "payment_customers",
        "prices",
        "tax_rates",
        "products",
        "payment_settings",
        "payment_links",
        "payment_events",
        "payment_accounts",
        "coupons",
        "checkout_attempts",
    ):
        op.execute(f"DROP TABLE {table} CASCADE")
