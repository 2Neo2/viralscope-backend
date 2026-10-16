from sqlalchemy import BigInteger, CheckConstraint, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IntPK, TimestampMixin


class User(TimestampMixin, Base):
    """Клиент сервиса. Входит по коду на почту или через Telegram (этап 3), пароля нет."""

    __tablename__ = "users"
    __table_args__ = (
        # Хотя бы один способ входа. Пользователь без почты и Telegram — ошибка в коде, база её не пропустит
        CheckConstraint("email IS NOT NULL OR telegram_id IS NOT NULL", name="has_login"),
        # Почту храним в нижнем регистре: Ivan@Mail.ru и ivan@mail.ru — один человек, а не два аккаунта
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[IntPK]
    email: Mapped[str | None] = mapped_column(String(320), unique=True)  # 320 — максимум по стандарту
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)  # id в Telegram больше 2^31
    telegram_username: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    # default — для объектов из Python, server_default — для строк, вставленных SQL-ом напрямую
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())

    def __repr__(self) -> str:
        # Без почты: repr попадает в логи и трейсбэки
        return f"User(id={self.id})"
