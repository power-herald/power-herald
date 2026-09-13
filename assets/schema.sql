-- Power Herald database schema for MySQL 5.7+ / MariaDB.
-- The enum labels match SQLAlchemy's default Enum(PythonEnum) persistence:
-- enum member names are stored, not enum member values.

CREATE DATABASE IF NOT EXISTS power_herald
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE power_herald;

CREATE TABLE IF NOT EXISTS power_sources (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    type ENUM('ACTIVE', 'PASSIVE', 'MANUAL') NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_generator BOOLEAN NOT NULL DEFAULT FALSE,
    description TEXT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS active_sources (
    source_id INT NOT NULL,
    secret VARCHAR(256) NULL,
    PRIMARY KEY (source_id),
    CONSTRAINT fk_active_sources_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS passive_sources (
    source_id INT NOT NULL,
    address VARCHAR(256) NOT NULL,
    ping_method ENUM('HTTP', 'PING', 'TCP') NOT NULL DEFAULT 'PING',
    PRIMARY KEY (source_id),
    CONSTRAINT fk_passive_sources_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS generator_sources (
    source_id INT NOT NULL,
    work_duration_minutes INT NOT NULL DEFAULT 240,
    maintenance_duration_minutes INT NOT NULL DEFAULT 60,
    PRIMARY KEY (source_id),
    CONSTRAINT fk_generator_sources_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS power_groups (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS power_group_sources (
    id INT NOT NULL AUTO_INCREMENT,
    group_id INT NOT NULL,
    source_id INT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_power_group_sources (group_id, source_id),
    CONSTRAINT fk_power_group_sources_group
        FOREIGN KEY (group_id) REFERENCES power_groups (id),
    CONSTRAINT fk_power_group_sources_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chats (
    id INT NOT NULL AUTO_INCREMENT,
    chat_id VARCHAR(64) NOT NULL,
    title VARCHAR(256) NULL,
    thread_id INT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_private BOOLEAN NOT NULL DEFAULT FALSE,
    source_id INT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_chats_chat_id (chat_id),
    CONSTRAINT fk_chats_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS state_changes (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state ENUM('ONLINE', 'OFFLINE') NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_state_changes_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS source_states (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    state ENUM('ONLINE', 'OFFLINE') NOT NULL,
    last_updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT fk_source_states_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS periods (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    state ENUM('ONLINE', 'OFFLINE') NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_periods_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subscriptions (
    id INT NOT NULL AUTO_INCREMENT,
    chat_id INT NOT NULL,
    source_id INT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    CONSTRAINT fk_subscriptions_chat
        FOREIGN KEY (chat_id) REFERENCES chats (id),
    CONSTRAINT fk_subscriptions_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS maintenance_modes (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    comment TEXT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_maintenance_modes_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outage_data (
    id INT NOT NULL AUTO_INCREMENT,
    last_updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content_hash VARCHAR(64) NOT NULL,
    json JSON NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outages (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    message_hash VARCHAR(64) NOT NULL,
    message JSON NOT NULL,
    PRIMARY KEY (id),
    KEY ix_outages_name_id (name, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outage_notifications (
    id INT NOT NULL AUTO_INCREMENT,
    posted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type ENUM('TODAY', 'TOMORROW') NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS weekly_statistics_notifications (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    week_start DATE NOT NULL,
    sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_weekly_statistics_notifications (source_id, week_start),
    CONSTRAINT fk_weekly_statistics_notifications_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;