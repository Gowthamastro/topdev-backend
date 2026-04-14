"""Add location and hiring_budget to clients

Revision ID: e7f9a2b3c4d5
Revises: d4e1f2a3b567
Create Date: 2026-04-14 19:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7f9a2b3c4d5'
down_revision = 'd4e1f2a3b567'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding columns to clients table
    op.add_column('clients', sa.Column('location', sa.String(length=255), nullable=True))
    op.add_column('clients', sa.Column('hiring_budget', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Removing columns from clients table
    op.drop_column('clients', 'hiring_budget')
    op.drop_column('clients', 'location')
