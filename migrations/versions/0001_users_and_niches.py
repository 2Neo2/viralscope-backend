"""users and niches

Первая миграция: пользователи и ниши.
- users          — клиенты; вход по почте или Telegram, поэтому одно из двух обязательно
- niches         — ниши для квиза и сбора видео
- niche_queries  — хештеги и аккаунты, по которым собираются видео ниши
- user_niches    — какие ниши выбрал клиент

Revision ID: 0001
Revises:
Create Date: 2026-10-17 11:30:48.855745+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "niches",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_niches")),
        sa.UniqueConstraint("slug", name=op.f("uq_niches_slug")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.CheckConstraint("email IS NOT NULL OR telegram_id IS NOT NULL", name=op.f("ck_users_has_login")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )
    op.create_table(
        "niche_queries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("niche_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("hashtag", "account", name="querykind", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("value", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('hashtag', 'account')", name=op.f("ck_niche_queries_kind")),
        sa.ForeignKeyConstraint(
            ["niche_id"], ["niches.id"], name=op.f("fk_niche_queries_niche_id_niches"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_niche_queries")),
        sa.UniqueConstraint("niche_id", "kind", "value", name=op.f("uq_niche_queries_niche_id_kind_value")),
    )
    op.create_table(
        "user_niches",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("niche_id", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.String(length=200), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["niche_id"], ["niches.id"], name=op.f("fk_user_niches_niche_id_niches"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_niches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "niche_id", name=op.f("pk_user_niches")),
    )
    op.create_index(op.f("ix_user_niches_niche_id"), "user_niches", ["niche_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_niches_niche_id"), table_name="user_niches")
    op.drop_table("user_niches")
    op.drop_table("niche_queries")
    op.drop_table("users")
    op.drop_table("niches")
