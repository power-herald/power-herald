# Deployment Guide

## System Requirements

- **OS**: Gentoo Linux (OpenRC)
- **Python**: 3.12+
- **MySQL**: 5.7+ or MariaDB 10.2+
- **Network**: 
  - Outbound HTTPS for Telegram API
  - Inbound HTTPS for webhook (443 → 8080)
  - Inbound HTTP for active probe (8081, recommended behind firewall)
- **SSL Certificate**: Valid SSL cert for webhook domain (Let's Encrypt recommended)

## Installation Steps

### 1. Prepare System

```bash
# Create service user
sudo useradd -m -s /sbin/nologin -d /opt/power_herald power_herald
sudo usermod -a -G power_herald power_herald

# Create directories
sudo mkdir -p /opt/power_herald /var/log/power_herald
sudo chown -R power_herald:power_herald /opt/power_herald /var/log/power_herald

# Install Python and dependencies
sudo emerge -av python:3.12 mysql-connector-python
```

### 2. Deploy Application

```bash
# Clone repository
cd /opt
sudo git clone <repo_url> power_herald
sudo chown -R power_herald:power_herald power_herald
cd power_herald

# Setup venv
sudo -u power_herald python3 -m venv venv
sudo -u power_herald venv/bin/pip install --upgrade pip
sudo -u power_herald venv/bin/pip install -r requirements.txt
```

### 3. Configure Application

```bash
# Copy and edit config
sudo cp config.yaml.example /etc/power_herald/config.yaml
sudo chown power_herald:power_herald /etc/power_herald/config.yaml
sudo chmod 600 /etc/power_herald/config.yaml
sudo nano /etc/power_herald/config.yaml
```

**Critical config fields**:
- `telegram.token` - Get from @BotFather
- `telegram.webhook_url` - Your domain URL (e.g., https://your.domain/webhook)
- `database.*` - MySQL credentials and connection details
- `admin.chat_ids` - Your Telegram user ID(s)

### 4. Initialize Database

```bash
# Create database and user
mysql -u root -p -e "
CREATE DATABASE power_herald CHARACTER SET utf8mb4;
CREATE USER 'power_herald'@'localhost' IDENTIFIED BY 'power_herald';
GRANT ALL PRIVILEGES ON power_herald.* TO 'power_herald'@'localhost';
FLUSH PRIVILEGES;
"

# Create tables from the SQLAlchemy model schema
mysql -u root -p < schema.sql
```

### 5. Setup Reverse Proxy (Nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain;

    ssl_certificate /etc/letsencrypt/live/your.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain/privkey.pem;

    location /webhook {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Restrict internal endpoints
    location /active_ping {
        auth_basic "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8081;
    }

}
```

### 6. Install OpenRC Services

```bash
# Copy init scripts
sudo cp /opt/power_herald/init.d/power_herald_* /etc/init.d/
sudo chmod +x /etc/init.d/power_herald_*

# Add to default runlevel
sudo rc-update add power_herald_bot default
sudo rc-update add power_herald_passive_probe default
sudo rc-update add power_herald_active_probe default
sudo rc-update add power_herald_processor default
sudo rc-update add power_herald_schedule default

# Start services
sudo rc-service power_herald_bot start
sudo rc-service power_herald_passive_probe start
sudo rc-service power_herald_active_probe start
sudo rc-service power_herald_processor start
sudo rc-service power_herald_schedule start
```

### 7. Verify Installation

```bash
# Check service status
sudo rc-service power_herald_bot status
ps aux | grep power_herald

# Test webhook
curl -I https://your.domain/webhook

# Send test message to bot
# Use @your_bot in Telegram and type /activate
```

## Post-Deployment

### 1. Configure Power Sources

Login to MySQL and add power sources:

```sql
INSERT INTO power_sources (name, type, enabled, description) VALUES
  ('Line A', 'PASSIVE', 1, 'Main city power line'),
  ('Generator 1', 'GENERATOR', 1, 'Backup generator');
INSERT INTO passive_sources (source_id, address, ping_method)
  VALUES (1, 'http://192.168.1.10:8000', 'HTTP');
INSERT INTO generator_sources (source_id, work_duration_minutes, maintenance_duration_minutes)
  VALUES (2, 240, 60);
```

Set `ping_method` to `PING` with a hostname/IP, or `TCP` with a `host:port`
address (the `tcp://host:port` form is also accepted).

For a database created with the previous schema, migrate the subtype data
before dropping the old columns:

```sql
INSERT INTO passive_sources (source_id, address, ping_method)
SELECT id, address, ping_method FROM power_sources WHERE type = 'PASSIVE';
INSERT INTO generator_sources (source_id, work_duration_minutes, maintenance_duration_minutes)
SELECT id, work_duration_minutes, maintenance_duration_minutes
FROM power_sources WHERE type = 'GENERATOR';
ALTER TABLE power_sources
  DROP COLUMN address,
  DROP COLUMN ping_method,
  DROP COLUMN work_duration_minutes,
  DROP COLUMN maintenance_duration_minutes;
```

### 2. Create Chat Subscriptions

```sql
-- First, activate a chat via bot /activate command, then:
INSERT INTO chats (chat_id, title, enabled, is_forum) VALUES
  ('123456789', 'Building A', 1, 0);

INSERT INTO subscriptions (chat_id, source_id, enabled) VALUES
  (1, 1, 1);  -- Chat 1 subscribed to source 1 (Line A)
```

### 3. Test Notifications

```bash
# Test passive probe (should trigger on timeout)
mysql> SELECT * FROM state_changes ORDER BY timestamp DESC LIMIT 5;

# Test active probe
curl -X POST http://localhost:8081/active_ping \
  -H "Content-Type: application/json" \
  -d '{"name": "Line B", "state": "offline"}'

```

## Monitoring

### Log Rotation

```bash
# /etc/logrotate.d/power_herald
/var/log/power_herald/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 power_herald power_herald
    sharedscripts
    postrotate
        rc-service power_herald_* restart > /dev/null 2>&1 || true
    endscript
}
```

### Health Checks

```bash
#!/bin/bash
# Monitor script
for service in power_herald_bot power_herald_passive_probe power_herald_active_probe power_herald_processor; do
    if ! rc-service $service status > /dev/null 2>&1; then
        echo "WARNING: $service is not running" | mail -s "Power Herald Alert" admin@example.com
    fi
done
```

### Database Maintenance

```bash
# Weekly backup
mysqldump -u power_herald -p power_herald > /var/backups/power_herald_$(date +%Y%m%d).sql

# Cleanup old state changes (optional, keep 90 days)
mysql power_herald -e "DELETE FROM state_changes WHERE timestamp < DATE_SUB(NOW(), INTERVAL 90 DAY);"
```

## Troubleshooting

### Bot not starting
```bash
sudo rc-service power_herald_bot start
sudo tail -f /var/log/power_herald/bot.log
```

### Database connection error
```bash
# Test connection
mysql -h localhost -u power_herald -p power_herald -e "SELECT 1;"
```

### Webhook not working
```bash
# Check reverse proxy logs
sudo tail -f /var/log/nginx/error.log

# Test webhook endpoint
curl -v https://your.domain/webhook
```

### No notifications
```bash
# Check subscriptions
mysql> SELECT * FROM subscriptions;

# Check chat is enabled
mysql> SELECT * FROM chats WHERE chat_id = 'YOUR_CHAT_ID';

# Check recent state changes
mysql> SELECT * FROM state_changes ORDER BY timestamp DESC LIMIT 10;
```

## Security Considerations

1. **Config file**: Store in `/etc/power_herald/` with 600 permissions
2. **Database password**: Use strong password, restrict access to localhost
3. **Bot token**: Never commit to version control
4. **HTTP endpoints**: Place behind firewall or reverse proxy with authentication
5. **Logs**: Monitor for sensitive data leakage
6. **SSL certificate**: Keep Let's Encrypt auto-renewal configured

## Backup & Recovery

```bash
# Full backup
mysqldump power_herald > /backup/power_herald_full_$(date +%Y%m%d_%H%M%S).sql

# Restore
mysql power_herald < /backup/power_herald_full.sql

# Config backup
cp /etc/power_herald/config.yaml /backup/config_$(date +%Y%m%d).yaml.bak
```
