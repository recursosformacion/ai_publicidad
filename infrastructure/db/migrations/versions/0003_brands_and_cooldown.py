"""Register brands, symmetric competitor relationships, and campaign rotation intervals."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_brands_and_cooldown"
down_revision = "0002_ad_format_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("brands"):
        op.create_table(
            "brands",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("website_url", sa.String(length=2048), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        )

    inspector = inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("brands")}
    if "ix_brands_name" not in indexes:
        op.create_index("ix_brands_name", "brands", ["name"], unique=True)

    inspector = inspect(bind)
    if not inspector.has_table("brand_competitors"):
        op.create_table(
            "brand_competitors",
            sa.Column("brand_left_id", sa.Integer(), nullable=False),
            sa.Column("brand_right_id", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "brand_left_id < brand_right_id",
                name="ck_brand_competitors_canonical_pair",
            ),
            sa.ForeignKeyConstraint(
                ["brand_left_id"], ["brands.id"],
                name="fk_brand_competitors_left",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["brand_right_id"], ["brands.id"],
                name="fk_brand_competitors_right",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("brand_left_id", "brand_right_id"),
        )

    inspector = inspect(bind)
    campaign_columns = {item["name"] for item in inspector.get_columns("campaigns")}
    missing_brand = "brand_id" not in campaign_columns
    missing_interval = "minimum_interval_seconds" not in campaign_columns
    if missing_brand or missing_interval:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("campaigns") as batch:
                if missing_brand:
                    batch.add_column(sa.Column("brand_id", sa.Integer(), nullable=True))
                    batch.create_foreign_key(
                        "fk_campaigns_brand_id",
                        "brands",
                        ["brand_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
                if missing_interval:
                    batch.add_column(
                        sa.Column(
                            "minimum_interval_seconds",
                            sa.Integer(),
                            server_default="0",
                            nullable=False,
                        )
                    )
        else:
            if missing_brand:
                op.add_column("campaigns", sa.Column("brand_id", sa.Integer(), nullable=True))
                op.create_foreign_key(
                    "fk_campaigns_brand_id",
                    "campaigns",
                    "brands",
                    ["brand_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if missing_interval:
                op.add_column(
                    "campaigns",
                    sa.Column(
                        "minimum_interval_seconds",
                        sa.Integer(),
                        server_default="0",
                        nullable=False,
                    ),
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("campaigns"):
        columns = {item["name"] for item in inspector.get_columns("campaigns")}
        missing_brand = "brand_id" not in columns
        missing_interval = "minimum_interval_seconds" not in columns
        # On downgrade, drop columns introduced by this revision. On databases
        # bootstrapped from the current Base.metadata migration 0001 may have created
        # them early; dropping them here is still correct for a downgrade to 0002.
        if bind.dialect.name == "sqlite":
            if not missing_brand or not missing_interval:
                with op.batch_alter_table("campaigns") as batch:
                    if not missing_brand:
                        try:
                            batch.drop_constraint("fk_campaigns_brand_id", type_="foreignkey")
                        except Exception:
                            # Some create_all bootstraps assign dialect-generated names;
                            # SQLite table recreation will preserve other constraints.
                            pass
                    if not missing_interval:
                        batch.drop_column("minimum_interval_seconds")
                    if not missing_brand:
                        batch.drop_column("brand_id")
        else:
            if not missing_brand:
                op.drop_constraint("fk_campaigns_brand_id", "campaigns", type_="foreignkey")
                op.drop_column("campaigns", "brand_id")
            if not missing_interval:
                op.drop_column("campaigns", "minimum_interval_seconds")

    inspector = inspect(bind)
    if inspector.has_table("brand_competitors"):
        op.drop_table("brand_competitors")

    inspector = inspect(bind)
    if inspector.has_table("brands"):
        indexes = {item["name"] for item in inspector.get_indexes("brands")}
        if "ix_brands_name" in indexes:
            op.drop_index("ix_brands_name", table_name="brands")
        op.drop_table("brands")
