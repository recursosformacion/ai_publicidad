"""Allow a creative to request a custom (non-standard) size."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0006_creative_custom_size"
down_revision = "0005_html_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("creatives")}
    if "custom_width" not in columns:
        op.add_column("creatives", sa.Column("custom_width", sa.Integer(), nullable=True))
    if "custom_height" not in columns:
        op.add_column("creatives", sa.Column("custom_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("creatives")}
    if "custom_height" in columns:
        op.drop_column("creatives", "custom_height")
    if "custom_width" in columns:
        op.drop_column("creatives", "custom_width")
