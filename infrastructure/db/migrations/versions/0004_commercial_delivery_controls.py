"""Add commercial orders, budgets, delivery caps and visitor hashes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_commercial_delivery_controls"
down_revision = "0003_brands_and_cooldown"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, column: sa.Column, foreign_table: str | None = None) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)
            if foreign_table:
                batch.create_foreign_key(f"fk_{table}_{column.name}", foreign_table, [column.name], ["id"], ondelete="SET NULL")
    else:
        op.add_column(table, column)
        if foreign_table:
            op.create_foreign_key(f"fk_{table}_{column.name}", table, foreign_table, [column.name], ["id"], ondelete="SET NULL")


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("advertisers"):
        op.create_table(
            "advertisers",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("legal_name", sa.String(240)),
            sa.Column("contact_name", sa.String(160)),
            sa.Column("contact_email", sa.String(254)),
            sa.Column("phone", sa.String(60)),
            sa.Column("website_url", sa.String(2048)),
            sa.Column("notes", sa.Text()),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_advertisers_name"),
        )
    if not inspect(bind).has_table("ad_orders"):
        op.create_table(
            "ad_orders",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("advertiser_id", sa.Integer(), sa.ForeignKey("advertisers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("reference", sa.String(100)),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("starts_at", sa.DateTime(timezone=True)),
            sa.Column("ends_at", sa.DateTime(timezone=True)),
            sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
            sa.Column("billing_model", sa.String(10), nullable=False, server_default="fixed"),
            sa.Column("fixed_fee_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_budget_cents", sa.Integer()),
            sa.Column("daily_budget_cents", sa.Integer()),
            sa.Column("cpm_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cpc_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("impression_limit_total", sa.Integer()),
            sa.Column("impression_limit_daily", sa.Integer()),
            sa.Column("click_limit_total", sa.Integer()),
            sa.Column("click_limit_daily", sa.Integer()),
            sa.Column("pacing_mode", sa.String(10), nullable=False, server_default="none"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("reference", name="uq_ad_orders_reference"),
        )
        op.create_index("ix_ad_orders_advertiser_id", "ad_orders", ["advertiser_id"])

    if "order_id" not in _columns("campaigns"):
        _add_column("campaigns", sa.Column("order_id", sa.Integer(), nullable=True), "ad_orders")
    for name, column in [
        ("max_impressions_total", sa.Column("max_impressions_total", sa.Integer())),
        ("max_impressions_daily", sa.Column("max_impressions_daily", sa.Integer())),
        ("max_clicks_total", sa.Column("max_clicks_total", sa.Integer())),
        ("max_clicks_daily", sa.Column("max_clicks_daily", sa.Integer())),
        ("max_impressions_per_visitor", sa.Column("max_impressions_per_visitor", sa.Integer(), nullable=False, server_default="0")),
        ("visitor_interval_seconds", sa.Column("visitor_interval_seconds", sa.Integer(), nullable=False, server_default="0")),
    ]:
        if name not in _columns("campaigns"):
            _add_column("campaigns", column)
    if "visitor_key_hash" not in _columns("ad_deliveries"):
        _add_column("ad_deliveries", sa.Column("visitor_key_hash", sa.String(64)))
    indexes = {i["name"] for i in inspect(bind).get_indexes("ad_deliveries")}
    if "ix_ad_deliveries_visitor_key_hash" not in indexes:
        op.create_index("ix_ad_deliveries_visitor_key_hash", "ad_deliveries", ["visitor_key_hash"])
    if "charge_microcents" not in _columns("ad_events"):
        _add_column("ad_events", sa.Column("charge_microcents", sa.BigInteger(), nullable=False, server_default="0"))


def downgrade() -> None:
    bind = op.get_bind()
    if "visitor_key_hash" in _columns("ad_deliveries"):
        indexes = {i["name"] for i in inspect(bind).get_indexes("ad_deliveries")}
        if "ix_ad_deliveries_visitor_key_hash" in indexes:
            op.drop_index("ix_ad_deliveries_visitor_key_hash", table_name="ad_deliveries")
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("ad_deliveries") as batch:
                batch.drop_column("visitor_key_hash")
        else:
            op.drop_column("ad_deliveries", "visitor_key_hash")
    if "charge_microcents" in _columns("ad_events"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("ad_events") as batch:
                batch.drop_column("charge_microcents")
        else:
            op.drop_column("ad_events", "charge_microcents")
    names = _columns("campaigns")
    drop_names = ["max_impressions_total", "max_impressions_daily", "max_clicks_total", "max_clicks_daily", "max_impressions_per_visitor", "visitor_interval_seconds", "order_id"]
    if any(name in names for name in drop_names):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("campaigns") as batch:
                if "order_id" in names:
                    try:
                        batch.drop_constraint("fk_campaigns_order_id", type_="foreignkey")
                    except Exception:
                        pass
                for name in drop_names:
                    if name in names:
                        batch.drop_column(name)
        else:
            if "order_id" in names:
                try:
                    op.drop_constraint("fk_campaigns_order_id", "campaigns", type_="foreignkey")
                except Exception:
                    pass
            for name in drop_names:
                if name in names:
                    op.drop_column(name)
    if inspect(bind).has_table("ad_orders"):
        op.drop_table("ad_orders")
    if inspect(bind).has_table("advertisers"):
        indexes = {i["name"] for i in inspect(bind).get_indexes("advertisers")}
        if "ix_advertisers_name" in indexes:
            op.drop_index("ix_advertisers_name", table_name="advertisers")
        op.drop_table("advertisers")
