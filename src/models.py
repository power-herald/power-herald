# src/models.py
from __future__ import annotations

import datetime
import enum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Boolean, Text, UniqueConstraint, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass

class PowerSourceType(enum.Enum):
    ACTIVE = "active"       # Device pings bot
    PASSIVE = "passive"     # Bot pings device
    GENERATOR = "generator" # Generator (manual activation, maintenance scheduling)

class PingMethod(enum.Enum):
    HTTP = "http"
    PING = "ping"
    TCP = "tcp"

class PowerSource(Base):
    __tablename__ = 'power_sources'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[PowerSourceType] = mapped_column(Enum(PowerSourceType), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)  # IP or URL
    ping_method: Mapped[PingMethod] = mapped_column(Enum(PingMethod), nullable=False, default=PingMethod.PING)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Generator-specific config
    work_duration_minutes: Mapped[int] = mapped_column(Integer, default=240)  # 4 hours
    maintenance_duration_minutes: Mapped[int] = mapped_column(Integer, default=60)  # 1 hour
    groups: Mapped[list[PowerSourceGroup]] = relationship(
        secondary='power_source_group_sources', back_populates='sources'
    )

class PowerSourceGroup(Base):
    __tablename__ = 'power_source_groups'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[list[PowerSource]] = relationship(
        secondary='power_source_group_sources', back_populates='groups'
    )

class PowerSourceGroupSource(Base):
    __tablename__ = 'power_source_group_sources'
    __table_args__ = (UniqueConstraint('group_id', 'source_id'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('power_source_groups.id'), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)

class StateChangeType(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"

class PowerStateChange(Base):
    __tablename__ = 'power_state_changes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    state: Mapped[StateChangeType] = mapped_column(Enum(StateChangeType), nullable=False)
    source: Mapped[PowerSource] = relationship()

class PowerState(Base):
    __tablename__ = 'power_states'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    state: Mapped[StateChangeType] = mapped_column(Enum(StateChangeType), nullable=False)
    last_updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[PowerSource] = relationship()

class OutagePeriod(Base):
    __tablename__ = 'outage_periods'
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
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_forum: Mapped[bool] = mapped_column(Boolean, default=False)
    admin: Mapped[bool] = mapped_column(Boolean, default=False)  # Is this an admin chat?

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(ForeignKey('chats.id'), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_generator: Mapped[bool] = mapped_column(Boolean, default=True)  # Notify on generator events
    chat: Mapped[Chat] = relationship()
    source: Mapped[PowerSource] = relationship()

class MaintenanceMode(Base):
    __tablename__ = 'maintenance_modes'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey('power_sources.id'), nullable=True)  # Null = global
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text)
    source: Mapped[PowerSource | None] = relationship()

class GeneratorSession(Base):
    __tablename__ = 'generator_sessions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('power_sources.id'), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_window_start: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    maintenance_window_end: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[PowerSource] = relationship()

class OutageData(Base):
    __tablename__ = 'outage_data'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    json: Mapped[dict] = mapped_column(JSON, nullable=False)

class Outage(Base):
    __tablename__ = 'outage'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[dict] = mapped_column(JSON, nullable=False)
