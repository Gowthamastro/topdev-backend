"""add proctoring tables and integrity columns

Revision ID: c8f2a1b3d456
Revises: 49f543910638
Create Date: 2026-04-07 14:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c8f2a1b3d456'
down_revision: Union[str, None] = 'b63630bbe98b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create proctor_events table
    op.create_table(
        'proctor_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attempt_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('client_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('event_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['attempt_id'], ['test_attempts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_proctor_events_id'), 'proctor_events', ['id'], unique=False)
    op.create_index(op.f('ix_proctor_events_attempt_id'), 'proctor_events', ['attempt_id'], unique=False)

    # Add integrity columns to test_attempts
    op.add_column('test_attempts', sa.Column('integrity_score', sa.Float(), nullable=True))
    op.add_column('test_attempts', sa.Column('integrity_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('test_attempts', sa.Column('proctor_summary', sa.Text(), nullable=True))
    op.add_column('test_attempts', sa.Column('proctoring_consented', sa.Boolean(), nullable=True, server_default=sa.text('true')))


def downgrade() -> None:
    op.drop_column('test_attempts', 'proctoring_consented')
    op.drop_column('test_attempts', 'proctor_summary')
    op.drop_column('test_attempts', 'integrity_flags')
    op.drop_column('test_attempts', 'integrity_score')
    op.drop_index(op.f('ix_proctor_events_attempt_id'), table_name='proctor_events')
    op.drop_index(op.f('ix_proctor_events_id'), table_name='proctor_events')
    op.drop_table('proctor_events')
