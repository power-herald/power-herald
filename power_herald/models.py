# src/models.py
from __future__ import annotations

import datetime
import enum

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Boolean, Text, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass

class PowerSourceType(enum.Enum):
    ACTIVE = "active"       # Device pings bot
    PASSIVE = "passive"     # Bot pings device
    MANUAL = "manual"       # State is controlled manually by a user

class PingMethod(enum.Enum):
    HTTP = "http"
    PING = "ping"
    TCP = "tcp"

class PowerSource(Base):
    __tablename__ = 'power_sources'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[PowerSourceType] = mapped_column(Enum(PowerSourceType), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_generator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[ActiveSource | None] = relationship(
        back_populates='source', uselist=False, cascade='all, delete-orphan'
    )
    passive: Mapped[PassiveSource | None] = relationship(
        back_populates='source', uselist=False, cascade='all, delete-orphan'
    )
    generator: Mapped[GeneratorSource | None] = relationship(
        back_populates='source', uselist=False, cascade='all, delete-orphan'
    )
    groups: Mapped[list[PowerGroup]] = relationship(
        secondary='power_group_sources', back_populates='sources'
    )


class ActiveSource(Base):
    __tablename__ = 'active_sources'
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), primary_key=True)
    secret: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[PowerSource] = relationship(back_populates='active')


class PassiveSource(Base):
    __tablename__ = 'passive_sources'
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), primary_key=True)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    ping_method: Mapped[PingMethod] = mapped_column(
        Enum(PingMethod), nullable=False, default=PingMethod.PING
    )
    source: Mapped[PowerSource] = relationship(back_populates='passive')


class GeneratorSource(Base):
    __tablename__ = 'generator_sources'
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), primary_key=True)
    work_duration_minutes: Mapped[int] = mapped_column(Integer, default=240)
    maintenance_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    source: Mapped[PowerSource] = relationship(back_populates='generator')

class PowerGroup(Base):
    __tablename__ = 'power_groups'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list[PowerSource]] = relationship(
        secondary='power_group_sources', back_populates='groups'
    )

class PowerGroupSource(Base):
    __tablename__ = 'power_group_sources'
    __table_args__ = (UniqueConstraint('group_id', 'source_id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('power_groups.id'), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)

class StateChangeType(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"

class StateChange(Base):
    __tablename__ = 'state_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    state: Mapped[StateChangeType] = mapped_column(Enum(StateChangeType), nullable=False)
    source: Mapped[PowerSource] = relationship()

class SourceState(Base):
    __tablename__ = 'source_states'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    state: Mapped[StateChangeType] = mapped_column(Enum(StateChangeType), nullable=False)
    last_updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[PowerSource] = relationship()

class Period(Base):
    __tablename__ = 'periods'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[StateChangeType] = mapped_column(Enum(StateChangeType), nullable=False)  # ONLINE/OFFLINE
    source: Mapped[PowerSource] = relationship()

class Chat(Base):
    __tablename__ = 'chats'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey('power_sources.id'), nullable=True)
    source: Mapped[PowerSource | None] = relationship()

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey('chats.id'), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    chat: Mapped[Chat] = relationship()
    source: Mapped[PowerSource] = relationship()

class MaintenanceMode(Base):
    __tablename__ = 'maintenance_modes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey('power_sources.id'), nullable=True)  # Null = global
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)
    source: Mapped[PowerSource | None] = relationship()

class OutageData(Base):
    __tablename__ = 'outage_data'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    json: Mapped[dict] = mapped_column(JSON, nullable=False)

class Outage(Base):
    __tablename__ = 'outages'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[dict] = mapped_column(JSON, nullable=False)

class OutageNotificationType(enum.Enum):
    TODAY = "today"
    TOMORROW = "tomorrow"

class OutageNotification(Base):
    __tablename__ = 'outage_notifications'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    posted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    type: Mapped[OutageNotificationType] = mapped_column(
        Enum(OutageNotificationType), nullable=False
    )

class WeeklyStatisticsNotification(Base):
    __tablename__ = 'weekly_statistics_notifications'
    __table_args__ = (UniqueConstraint('source_id', 'week_start'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    week_start: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[PowerSource] = relationship()
