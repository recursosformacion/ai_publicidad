"""Separate creative content type, size and delivery authorization."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "0007_content_delivery_model"
down_revision = "0006_creative_custom_size"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("creatives")}
    if "delivery_mode" not in columns:
        op.add_column(
            "creatives",
            sa.Column("delivery_mode", sa.String(length=20), nullable=False, server_default="both"),
        )
    # Legacy creatives used "responsive" as a content type. Infer their real
    # content and move the capability to delivery_mode.
    op.execute(
        text(
            """
            UPDATE creatives
            SET format = CASE
                WHEN image_url IS NOT NULL AND body IS NOT NULL AND TRIM(body) <> '' THEN 'image_text'
                WHEN image_url IS NOT NULL THEN 'image'
                ELSE 'text'
            END,
            delivery_mode = 'adaptive'
            WHERE format = 'responsive'
            """
        )
    )
    op.execute(text("UPDATE creatives SET delivery_mode = 'both' WHERE delivery_mode IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("creatives")}
    op.execute(text("UPDATE creatives SET format = 'responsive' WHERE delivery_mode = 'adaptive' AND format IN ('text','image','image_text')"))
    if "delivery_mode" in columns:
        op.drop_column("creatives", "delivery_mode")
