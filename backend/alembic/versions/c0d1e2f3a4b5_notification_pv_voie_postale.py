"""voie postale par copropriétaire ; notification du PV aux opposants et défaillants

Loi n° 65-557, art. 42 al. 2 (notification du PV sous un mois, contestation sous deux mois)
et art. 42-1 (voie électronique par défaut, voie postale sur demande du copropriétaire).
Les comptes existants restent en voie électronique : aucune demande n'est inventée.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notification_postale", sa.Boolean(), nullable=False,
                                      server_default=sa.text("false")))
        batch_op.add_column(sa.Column("notification_postale_depuis", sa.Date(), nullable=True))
    op.create_table(
        "notifications_pv",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ag_id", sa.Integer(), sa.ForeignKey("ags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("nom", sa.String(), nullable=False),
        sa.Column("qualite", sa.String(), nullable=False),
        sa.Column("resolutions", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("date_envoi", sa.Date(), nullable=True),
        sa.Column("date_presentation", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notifications_pv_ag_id", "notifications_pv", ["ag_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_pv_ag_id", table_name="notifications_pv")
    op.drop_table("notifications_pv")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("notification_postale_depuis")
        batch_op.drop_column("notification_postale")
