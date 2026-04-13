"""Add Phase 1 profile completion fields to candidates

Revision ID: d4e1f2a3b567
Revises: c8f2a1b3d456
Create Date: 2026-04-13

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4e1f2a3b567"
down_revision = "c8f2a1b3d456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("is_profile_complete", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "candidates",
        sa.Column("phone_verified", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("candidates", "phone_verified")
    op.drop_column("candidates", "is_profile_complete")
