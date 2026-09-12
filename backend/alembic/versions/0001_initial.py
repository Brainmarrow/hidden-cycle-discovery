"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00

NOTE: This is a placeholder. Generate the real migration with:
    alembic revision --autogenerate -m "initial schema"
after the models are loaded. In development, tables are auto-created
on startup (see app/main.py lifespan).
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables are created via Base.metadata.create_all in dev mode.
    # For production, run: alembic revision --autogenerate -m "initial"
    # to generate the full DDL from app/models/models.py
    pass


def downgrade() -> None:
    pass
