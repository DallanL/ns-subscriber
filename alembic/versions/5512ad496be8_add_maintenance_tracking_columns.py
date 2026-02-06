"""Add maintenance tracking columns

Revision ID: 5512ad496be8
Revises: 02e36ce00c43
Create Date: 2026-01-30 12:10:33.051557

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5512ad496be8"
down_revision: Union[str, Sequence[str], None] = "02e36ce00c43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add columns to subscriptions table
    op.add_column(
        "subscriptions",
        sa.Column(
            "maintenance_status", sa.String(), server_default="pending", nullable=True
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "last_maintenance_attempt", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "subscriptions", sa.Column("maintenance_message", sa.Text(), nullable=True)
    )
    op.create_index(
        op.f("ix_subscriptions_maintenance_status"),
        "subscriptions",
        ["maintenance_status"],
        unique=False,
    )

    # Add columns to oauth_credentials table
    op.add_column(
        "oauth_credentials",
        sa.Column(
            "maintenance_status", sa.String(), server_default="pending", nullable=True
        ),
    )
    op.add_column(
        "oauth_credentials",
        sa.Column(
            "last_maintenance_attempt", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "oauth_credentials", sa.Column("maintenance_message", sa.Text(), nullable=True)
    )
    op.create_index(
        op.f("ix_oauth_credentials_maintenance_status"),
        "oauth_credentials",
        ["maintenance_status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove columns from oauth_credentials table
    op.drop_index(
        op.f("ix_oauth_credentials_maintenance_status"), table_name="oauth_credentials"
    )
    op.drop_column("oauth_credentials", "maintenance_message")
    op.drop_column("oauth_credentials", "last_maintenance_attempt")
    op.drop_column("oauth_credentials", "maintenance_status")

    # Remove columns from subscriptions table
    op.drop_index(
        op.f("ix_subscriptions_maintenance_status"), table_name="subscriptions"
    )
    op.drop_column("subscriptions", "maintenance_message")
    op.drop_column("subscriptions", "last_maintenance_attempt")
    op.drop_column("subscriptions", "maintenance_status")
