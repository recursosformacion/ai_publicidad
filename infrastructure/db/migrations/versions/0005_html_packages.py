"""Attach immutable static HTML packages to creatives."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0005_html_packages"
down_revision = "0004_commercial_delivery_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("creative_packages"):
        return
    op.create_table(
        "creative_packages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "creative_id",
            sa.Integer(),
            sa.ForeignKey("creatives.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("compressed_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("entrypoint", sa.String(length=120), nullable=False, server_default="index.html"),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("creative_id", name="uq_creative_packages_creative_id"),
    )
    op.create_index("ix_creative_packages_creative_id", "creative_packages", ["creative_id"])
    op.create_index("ix_creative_packages_sha256", "creative_packages", ["sha256"])


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("creative_packages"):
        return
    op.drop_index("ix_creative_packages_sha256", table_name="creative_packages")
    op.drop_index("ix_creative_packages_creative_id", table_name="creative_packages")
    op.drop_table("creative_packages")
