"""usage ledger, wallets, top-ups and rate cards; the trigger that keeps a wallet's balance equal to its ledger; the
usage.read capability

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
# frozen: the values this migration knew
MODES = ("prepaid", "postpaid")
KINDS = ("usage", "reversal", "topup", "adjustment")
TOPUP_STATUSES = ("pending", "succeeded", "failed")
TOPUP_TRIGGERS = ("manual", "auto")
# frozen: what each system role of an existing organization gains (a new organization gets it from app/roles_seed.py)
GRANTS = {key: ("usage.read",) for key in ("owner", "admin", "manager", "member")}
CAPABILITIES = ("usage.read",)


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def pk() -> sa.Column:
    return col("id", sa.Uuid(), **UUID_PK)


def user(name: str) -> sa.Column:
    return col(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def money(name: str, **kw) -> sa.Column:
    return col(name, sa.BigInteger(), **kw)


def zero(name: str) -> sa.Column:
    return money(name, server_default="0")


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def check(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=name)


def tables() -> None:
    op.create_table(
        "wallets", col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        col("currency", sa.String(3), server_default="USD"), zero("balance"),
        col("mode", sa.String(10), server_default="prepaid"), money("credit_limit", nullable=True),
        money("low_balance_at", nullable=True), col("auto_recharge", sa.Boolean(), server_default=sa.text("false")),
        money("recharge_below", nullable=True), money("recharge_amount", nullable=True),
        col("payment_method", sa.String(200), nullable=True), money("monthly_cap", nullable=True),
        col("cap_alert_pct", sa.Integer(), server_default="80"), created(), created("updated_at"),
        check("ck_wallets_mode", in_list("mode", MODES)),
        check("ck_wallets_credit_limit", "credit_limit IS NULL OR credit_limit >= 0"),
        check("ck_wallets_low_balance_at", "low_balance_at IS NULL OR low_balance_at >= 0"),
        check("ck_wallets_monthly_cap", "monthly_cap IS NULL OR monthly_cap >= 0"),
        check("ck_wallets_cap_alert_pct", "cap_alert_pct BETWEEN 1 AND 100"),
        check("ck_wallets_auto_recharge", "NOT auto_recharge OR (recharge_below IS NOT NULL AND recharge_amount > 0)"),
        check("ck_wallets_recharge_below", "recharge_below IS NULL OR recharge_below >= 0"))
    op.create_table(
        "usage_ledger", pk(), workspace(), col("kind", sa.String(12)), col("meter", sa.String(40), nullable=True),
        zero("quantity"), zero("unit_cost"), zero("unit_price"), zero("cost"), zero("price"), money("amount"),
        zero("balance_after"), col("currency", sa.String(3)), col("rate_card_id", sa.Uuid(), nullable=True),
        col("source", sa.String(20)), col("subject_type", sa.String(20), nullable=True),
        col("subject_id", sa.Uuid(), nullable=True), col("reverses_id", sa.Uuid(), nullable=True),
        col("description", sa.String(300), server_default=""), col("idempotency_key", sa.String(160), nullable=True),
        col("actor_type", sa.String(20), server_default="system"), col("actor_id", sa.Uuid(), nullable=True), created(),
        check("ck_usage_ledger_kind", in_list("kind", KINDS)),
        check("ck_usage_ledger_positive",
              "quantity >= 0 AND cost >= 0 AND price >= 0 AND unit_cost >= 0 AND unit_price >= 0"),
        check("ck_usage_ledger_meter", "(kind IN ('usage', 'reversal')) = (meter IS NOT NULL)"),
        check("ck_usage_ledger_usage_amount", "kind <> 'usage' OR amount = -price"),
        check("ck_usage_ledger_reversal_amount", "kind <> 'reversal' OR amount = price"),
        check("ck_usage_ledger_topup_amount", "kind <> 'topup' OR amount > 0"))
    op.create_index("uq_usage_ledger_id_workspace", "usage_ledger", ["id", "workspace_id"], unique=True)
    op.create_foreign_key(None, "usage_ledger", "usage_ledger", ["reverses_id", "workspace_id"],
                          ["id", "workspace_id"])
    op.create_index("uq_usage_ledger_key", "usage_ledger", ["workspace_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_index("ix_usage_ledger_list", "usage_ledger",
                    ["workspace_id", sa.text("created_at DESC"), sa.text("id DESC")])
    op.create_index("ix_usage_ledger_meter", "usage_ledger", ["workspace_id", "meter", "created_at"])
    op.create_index("ix_usage_ledger_subject", "usage_ledger", ["workspace_id", "subject_id"],
                    postgresql_where=sa.text("subject_id IS NOT NULL"))
    op.create_table(
        "wallet_topups", pk(), workspace(), money("amount"), col("currency", sa.String(3)),
        col("status", sa.String(10), server_default="pending"), col("trigger", sa.String(10), server_default="manual"),
        col("provider", sa.String(20)), col("provider_ref", sa.String(200), nullable=True),
        col("error", sa.String(300), nullable=True), col("idempotency_key", sa.String(255), nullable=True),
        col("ledger_id", sa.Uuid(), nullable=True), user("created_by"), created(),
        col("completed_at", TS, nullable=True),
        check("ck_wallet_topups_status", in_list("status", TOPUP_STATUSES)),
        check("ck_wallet_topups_trigger", in_list("trigger", TOPUP_TRIGGERS)),
        check("ck_wallet_topups_amount", "amount > 0"))
    op.create_index("uq_wallet_topups_key", "wallet_topups", ["workspace_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_index("ix_wallet_topups_list", "wallet_topups",
                    ["workspace_id", sa.text("created_at DESC"), sa.text("id DESC")])
    op.create_index("uq_wallet_topups_auto_pending", "wallet_topups", ["workspace_id"], unique=True,
                    postgresql_where=sa.text("trigger = 'auto' AND status = 'pending'"))
    op.create_table(
        "rate_cards", pk(), col("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        col("brand_id", sa.Uuid(), nullable=True),
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        col("meter", sa.String(40)), col("currency", sa.String(3), server_default="USD"),
        money("price", nullable=True), col("markup_bp", sa.Integer(), nullable=True), user("created_by"), created(),
        created("updated_at"),
        sa.ForeignKeyConstraint(["brand_id", "org_id"], ["brands.id", "brands.org_id"], ondelete="CASCADE"),
        check("ck_rate_cards_price_or_markup", "(price IS NULL) <> (markup_bp IS NULL)"),
        check("ck_rate_cards_price", "price IS NULL OR price >= 0"),
        check("ck_rate_cards_markup", "markup_bp IS NULL OR markup_bp BETWEEN -10000 AND 1000000"),
        check("ck_rate_cards_one_scope", "brand_id IS NULL OR workspace_id IS NULL"))
    op.create_index("uq_rate_cards_scope", "rate_cards", ["org_id", "brand_id", "workspace_id", "meter", "currency"],
                    unique=True, postgresql_nulls_not_distinct=True)


WORKSPACE = "workspace_id = app_workspace_id()"
# an owner or admin of the request's organization (the system roles that are admins of every workspace of it)
ORG_ADMIN = ("EXISTS (SELECT 1 FROM org_members om JOIN roles r ON r.id = om.role_id WHERE om.org_id = app_org_id() "
             "AND om.user_id = app_user_id() AND r.is_system AND r.key IN ('owner', 'admin'))")
# Money only enters the ledger the way the code makes it: a usage charge (its amount is minus its price, a check
# constraint), the refund of an existing charge for exactly its price, a top-up the provider accepted for exactly its
# amount, or an adjustment by an organization owner or admin.
LEDGER_INSERT = (
    f"{WORKSPACE} AND (kind = 'usage' "
    "OR (kind = 'reversal' AND EXISTS (SELECT 1 FROM usage_ledger u WHERE u.id = usage_ledger.reverses_id "
    "AND u.kind = 'usage' AND u.price = usage_ledger.price AND u.meter = usage_ledger.meter)) "
    "OR (kind = 'topup' AND subject_type = 'topup' AND EXISTS (SELECT 1 FROM wallet_topups t "
    "WHERE t.id = usage_ledger.subject_id AND t.status = 'pending' AND t.amount = usage_ledger.amount)) "
    f"OR (kind = 'adjustment' AND {ORG_ADMIN}))")
# a rate card applies to the request's workspace when it is the organization's, its brand's or its own
APPLIES = ("(workspace_id IS NULL OR workspace_id = app_workspace_id()) AND (brand_id IS NULL OR brand_id = "
           "(SELECT w.brand_id FROM workspaces w WHERE w.id = app_workspace_id()))")
CARD_WRITE = (f"org_id = app_org_id() AND {ORG_ADMIN} AND (workspace_id IS NULL OR workspace_id IN "
              "(SELECT w.id FROM workspaces w WHERE w.org_id = app_org_id()))")

# table: (privileges for gohigh_app, [(policy, body)]). The ledger is append only. A wallet's balance is not
# writable by a request at all (only the ledger trigger moves it) and a new wallet can only be inserted empty.
RLS = {
    "wallets": ("SELECT", [("workspace", f"FOR ALL USING ({WORKSPACE}) WITH CHECK ({WORKSPACE})")]),
    "usage_ledger": ("SELECT", [("workspace_read", f"FOR SELECT USING ({WORKSPACE})"),
                                ("append", f"FOR INSERT WITH CHECK ({LEDGER_INSERT})")]),
    "wallet_topups": ("SELECT, INSERT", [("workspace", f"FOR ALL USING ({WORKSPACE}) WITH CHECK ({WORKSPACE})")]),
    "rate_cards": ("SELECT, INSERT, DELETE", [
        ("read", f"FOR SELECT USING (org_id = app_org_id() AND ({ORG_ADMIN} OR ({APPLIES})))"),
        ("org_insert", f"FOR INSERT WITH CHECK ({CARD_WRITE})"),
        ("org_update", f"FOR UPDATE USING ({CARD_WRITE}) WITH CHECK ({CARD_WRITE})"),
        ("org_delete", f"FOR DELETE USING ({CARD_WRITE})")]),
}
COLUMN_GRANTS = [
    "GRANT INSERT (workspace_id) ON wallets TO gohigh_app",
    "GRANT UPDATE (currency, mode, credit_limit, low_balance_at, auto_recharge, recharge_below, recharge_amount, "
    "payment_method, monthly_cap, cap_alert_pct, updated_at) ON wallets TO gohigh_app",
    "GRANT INSERT (id, workspace_id, kind, meter, quantity, unit_cost, unit_price, cost, price, amount, currency, "
    "rate_card_id, source, subject_type, subject_id, reverses_id, description, idempotency_key, actor_type, actor_id) "
    "ON usage_ledger TO gohigh_app",
    "GRANT UPDATE (status, provider_ref, error, ledger_id, completed_at) ON wallet_topups TO gohigh_app",
    "GRANT UPDATE (price, markup_bp, updated_at) ON rate_cards TO gohigh_app",
]

FUNCTIONS = [
    # A ledger row moves its wallet's balance, under the wallet's row lock, and records the balance it left behind and
    # the wallet's currency. SECURITY DEFINER: the request role has no UPDATE on the balance.
    """CREATE FUNCTION usage_ledger_apply() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public AS $$
    BEGIN
      NEW.created_at := clock_timestamp();  -- the order rows were applied in, even inside one transaction
      UPDATE wallets SET balance = balance + NEW.amount WHERE workspace_id = NEW.workspace_id
        RETURNING balance, currency INTO NEW.balance_after, NEW.currency;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'workspace % has no wallet', NEW.workspace_id;
      END IF;
      RETURN NEW;
    END $$""",
    "CREATE TRIGGER usage_ledger_apply BEFORE INSERT ON usage_ledger FOR EACH ROW "
    "EXECUTE FUNCTION usage_ledger_apply()",
    # Credit is the organization's risk: only its owners and admins change a wallet's mode, credit limit or currency,
    # and the currency only while the wallet has no ledger entries.
    f"""CREATE FUNCTION wallets_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF current_user = 'gohigh_app' AND (NEW.mode, NEW.credit_limit, NEW.currency)
          IS DISTINCT FROM (OLD.mode, OLD.credit_limit, OLD.currency) AND NOT {ORG_ADMIN} THEN
        RAISE EXCEPTION 'only organization owners and admins change the mode, credit limit or currency of a wallet'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      IF NEW.currency <> OLD.currency AND EXISTS (SELECT 1 FROM usage_ledger WHERE workspace_id = NEW.workspace_id) THEN
        RAISE EXCEPTION 'a wallet with ledger entries keeps its currency' USING ERRCODE = 'check_violation';
      END IF;
      RETURN NEW;
    END $$""",
    "CREATE TRIGGER wallets_guard BEFORE UPDATE ON wallets FOR EACH ROW EXECUTE FUNCTION wallets_guard()",
]


def upgrade() -> None:
    tables()
    for table, (privileges, policies) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        for name, body in policies:
            op.execute(f"CREATE POLICY {name} ON {table} {body}")
    for statement in COLUMN_GRANTS + FUNCTIONS:
        op.execute(statement)
    op.execute("REVOKE ALL ON FUNCTION usage_ledger_apply() FROM PUBLIC")
    # roles have row level security forced on them, which applies to their owner too: the system setting (what sign up
    # uses) lets this migration change them
    op.execute("SELECT set_config('app.system', 'on', true)")
    connection = op.get_bind()
    for key, capabilities in GRANTS.items():
        connection.execute(sa.text("UPDATE roles SET capabilities = capabilities || array(SELECT c FROM "
                                   "unnest(CAST(:caps AS text[])) c WHERE c <> ALL(capabilities)) "
                                   "WHERE is_system AND key = :key"), {"caps": list(capabilities), "key": key})


def downgrade() -> None:
    op.execute("SELECT set_config('app.system', 'on', true)")
    op.get_bind().execute(sa.text("UPDATE roles SET capabilities = array(SELECT c FROM unnest(capabilities) c "
                                  "WHERE c <> ALL(CAST(:caps AS text[])))"), {"caps": list(CAPABILITIES)})
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute("DROP FUNCTION usage_ledger_apply()")
    op.execute("DROP FUNCTION wallets_guard()")
