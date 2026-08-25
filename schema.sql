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
    type ENUM('ACTIVE', 'PASSIVE', 'GENERATOR') NOT NULL,
    address VARCHAR(256) NOT NULL,
    ping_method ENUM('HTTP', 'PING', 'TCP') NOT NULL DEFAULT 'PING',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT NULL,
    work_duration_minutes INT NOT NULL DEFAULT 240,
    maintenance_duration_minutes INT NOT NULL DEFAULT 60,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chats (
    id INT NOT NULL AUTO_INCREMENT,
    chat_id VARCHAR(64) NOT NULL,
    title VARCHAR(256) NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_forum BOOLEAN NOT NULL DEFAULT FALSE,
    admin BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id),
    UNIQUE KEY uq_chats_chat_id (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS power_state_changes (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state ENUM('ONLINE', 'OFFLINE', 'UNSTABLE') NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_power_state_changes_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS outage_periods (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NULL,
    state ENUM('ONLINE', 'OFFLINE', 'UNSTABLE') NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_outage_periods_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subscriptions (
    id INT NOT NULL AUTO_INCREMENT,
    chat_id INT NOT NULL,
    source_id INT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    notify_generator BOOLEAN NOT NULL DEFAULT TRUE,
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

CREATE TABLE IF NOT EXISTS generator_sessions (
    id INT NOT NULL AUTO_INCREMENT,
    source_id INT NOT NULL,
    started_at DATETIME NOT NULL,
    stopped_at DATETIME NULL,
    maintenance_window_start DATETIME NULL,
    maintenance_window_end DATETIME NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_generator_sessions_source
        FOREIGN KEY (source_id) REFERENCES power_sources (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;