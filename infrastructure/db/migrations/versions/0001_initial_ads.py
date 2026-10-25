"""Initial advertising inventory, deliveries and events."""

from alembic import op

from domain.models import Base

revision = "0001_initial_ads"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
