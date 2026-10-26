"""Add standard ad-format catalog and link it to creatives and delivery history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0002_ad_format_catalog"
down_revision = "0001_initial_ads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_formats"):
        op.create_table(
            "ad_formats",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.Column("device", sa.String(length=20), server_default="both", nullable=False),
            sa.Column("category", sa.String(length=30), server_default="banner", nullable=False),
            sa.Column("placement_notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        )
        op.create_index("ix_ad_formats_code", "ad_formats", ["code"], unique=True)

    inspector = inspect(bind)
    if not inspector.has_table("creative_ad_formats"):
        op.create_table(
            "creative_ad_formats",
            sa.Column("creative_id", sa.Integer(), nullable=False),
            sa.Column("ad_format_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["creative_id"], ["creatives.id"],
                name="fk_creative_ad_formats_creative_id",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["ad_format_id"], ["ad_formats.id"],
                name="fk_creative_ad_formats_ad_format_id",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("creative_id", "ad_format_id"),
        )

    inspector = inspect(bind)
    if inspector.has_table("ad_deliveries"):
        columns = {column["name"] for column in inspector.get_columns("ad_deliveries")}
        if "ad_format_id" not in columns:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("ad_deliveries") as batch:
                    batch.add_column(sa.Column("ad_format_id", sa.Integer(), nullable=True))
                    batch.create_foreign_key(
                        "fk_ad_deliveries_ad_format_id",
                        "ad_formats",
                        ["ad_format_id"],
                        ["id"],
                        ondelete="RESTRICT",
                    )
            else:
                op.add_column(
                    "ad_deliveries",
                    sa.Column("ad_format_id", sa.Integer(), nullable=True),
                )
                op.create_foreign_key(
                    "fk_ad_deliveries_ad_format_id",
                    "ad_deliveries",
                    "ad_formats",
                    ["ad_format_id"],
                    ["id"],
                    ondelete="RESTRICT",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("ad_deliveries"):
        columns = {column["name"] for column in inspector.get_columns("ad_deliveries")}
        if "ad_format_id" in columns:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("ad_deliveries") as batch:
                    batch.drop_constraint("fk_ad_deliveries_ad_format_id", type_="foreignkey")
                    batch.drop_column("ad_format_id")
            else:
                op.drop_constraint(
                    "fk_ad_deliveries_ad_format_id",
                    "ad_deliveries",
                    type_="foreignkey",
                )
                op.drop_column("ad_deliveries", "ad_format_id")

    inspector = inspect(bind)
    if inspector.has_table("creative_ad_formats"):
        op.drop_table("creative_ad_formats")

    inspector = inspect(bind)
    if inspector.has_table("ad_formats"):
        indexes = {item["name"] for item in inspector.get_indexes("ad_formats")}
        if "ix_ad_formats_code" in indexes:
            op.drop_index("ix_ad_formats_code", table_name="ad_formats")
        op.drop_table("ad_formats")
