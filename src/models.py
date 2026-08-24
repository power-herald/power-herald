# src/models.py
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Boolean, Text
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class PowerSourceType(enum.Enum):
    ACTIVE = "active"       # Device pings bot
    PASSIVE = "passive"     # Bot pings device
    GENERATOR = "generator" # Generator (manual activation, maintenance scheduling)

class PowerSource(Base):
    __tablename__ = 'power_sources'
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    type = Column(Enum(PowerSourceType), nullable=False)
    address = Column(String(256), nullable=False)  # IP or URL
    enabled = Column(Boolean, default=True)
    description = Column(Text)
    # Generator-specific config
    work_duration_minutes = Column(Integer, default=240)  # 4 hours
    maintenance_duration_minutes = Column(Integer, default=60)  # 1 hour

class StateChangeType(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNSTABLE = "unstable"

class PowerStateChange(Base):
    __tablename__ = 'power_state_changes'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('power_sources.id'), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    state = Column(Enum(StateChangeType), nullable=False)
    source = relationship('PowerSource')

class OutagePeriod(Base):
    __tablename__ = 'outage_periods'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('power_sources.id'), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    state = Column(Enum(StateChangeType), nullable=False)  # OFFLINE/UNSTABLE
    source = relationship('PowerSource')

class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(64), unique=True, nullable=False)
    title = Column(String(256))
    enabled = Column(Boolean, default=True)
    is_forum = Column(Boolean, default=False)
    admin = Column(Boolean, default=False)  # Is this an admin chat?

class Subscription(Base):
    __tablename__ = 'subscriptions'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey('chats.id'), nullable=False)
    source_id = Column(Integer, ForeignKey('power_sources.id'), nullable=False)
    enabled = Column(Boolean, default=True)
    notify_generator = Column(Boolean, default=True)  # Notify on generator events
    chat = relationship('Chat')
    source = relationship('PowerSource')

class MaintenanceMode(Base):
    __tablename__ = 'maintenance_modes'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('power_sources.id'), nullable=True)  # Null = global
    enabled = Column(Boolean, default=True)
    comment = Column(Text)
    source = relationship('PowerSource')

class GeneratorSession(Base):
    __tablename__ = 'generator_sessions'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('power_sources.id'), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    maintenance_window_start = Column(DateTime(timezone=True), nullable=True)
    maintenance_window_end = Column(DateTime(timezone=True), nullable=True)
    source = relationship('PowerSource')
