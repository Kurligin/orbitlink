"""Модели хранилища: проект, вариант, кэш прогона."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine, ForeignKey, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import JSON

_MEMORY_SQLITE_URLS = ("sqlite://", "sqlite:///:memory:")


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    title: Mapped[str]
    base_scenario: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)

    variants: Mapped[list[Variant]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Variant.created_at"
    )


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str]
    scenario: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)

    project: Mapped[Project] = relationship(back_populates="variants")
    runs: Mapped[list[Run]] = relationship(back_populates="variant", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    variant_id: Mapped[str] = mapped_column(ForeignKey("variants.id"))
    fingerprint: Mapped[str] = mapped_column(index=True)
    strategy: Mapped[str]
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)

    variant: Mapped[Variant] = relationship(back_populates="runs")


def create_engine_and_tables(url: str) -> Engine:
    """Создаёт движок БД и таблицы схемы.

    Для sqlite «в памяти» (`sqlite://` без указания файла) движок получает
    статический пул с единственным общим соединением: у sqlite отдельная
    база на каждое физическое соединение, а FastAPI выполняет синхронные
    обработчики запросов в пуле потоков — без общего соединения на все
    потоки каждый запрос видел бы свою пустую базу вместо общей.
    """
    if url in _MEMORY_SQLITE_URLS:
        engine = create_engine(
            url,
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, future=True)
