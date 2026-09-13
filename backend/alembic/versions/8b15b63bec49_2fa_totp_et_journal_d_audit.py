"""2FA TOTP + politique par copropriété + journal d'audit

- users : secret TOTP (chiffré), activation, codes de secours hachés, dernière connexion.
- coproprietes.totp_policy : off | syndic | all. Les lignes existantes restent NULL
  (« off » pour l'application) ; les nouvelles copropriétés reçoivent la politique
  par défaut de l'installation (COPRO_TOTP_DEFAULT_POLICY).
- audit_logs : journal des actions sensibles — pas de clé étrangère (entrées
  forensiques qui doivent survivre aux suppressions de comptes/copropriétés).

Revision ID: 8b15b63bec49
Revises: b1c9a3e2d4f5
Create Date: 2026-09-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b15b63bec49'
down_revision: Union[str, Sequence[str], None] = 'b1c9a3e2d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("user_email", sa.String(), nullable=True),
        sa.Column("user_nom", sa.String(), nullable=True),
        sa.Column("copro_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_copro_id", "audit_logs", ["copro_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.add_column("coproprietes", sa.Column("totp_policy", sa.String(), nullable=True))
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=True))
    op.add_column("users", sa.Column("recovery_hashes", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("last_login_ip", sa.String(), nullable=True))
    op.add_column("users", sa.Column("last_login_ua", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "last_login_ua")
    op.drop_column("users", "last_login_ip")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "recovery_hashes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("coproprietes", "totp_policy")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_copro_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
