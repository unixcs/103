-- verify-lab MySQL 表结构
-- 与 app/db.py 里的 SQLite 版本一一对应，差异只在类型和自增写法。

CREATE TABLE IF NOT EXISTS users (
    user_id      BIGINT PRIMARY KEY,
    username     VARCHAR(255),
    full_name    VARCHAR(255),
    balance      INT NOT NULL DEFAULT 1,
    is_blocked   TINYINT NOT NULL DEFAULT 0,
    invited_by   BIGINT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_checkin DATETIME NULL,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS invitations (
    id         BIGINT AUTO_INCREMENT PRIMARY KEY,
    inviter_id BIGINT NOT NULL,
    invitee_id BIGINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_invitee (invitee_id),
    INDEX idx_inviter (inviter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS verifications (
    id        BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id   BIGINT NOT NULL,
    kind      VARCHAR(50) NOT NULL,
    status    VARCHAR(50) NOT NULL,
    detail    TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS card_keys (
    key_code     VARCHAR(100) PRIMARY KEY,
    balance      INT NOT NULL,
    max_uses     INT NOT NULL DEFAULT 1,
    current_uses INT NOT NULL DEFAULT 0,
    created_by   BIGINT,
    expire_at    DATETIME NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS card_key_usage (
    key_code VARCHAR(100) NOT NULL,
    user_id  BIGINT NOT NULL,
    used_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (key_code, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
