# Power Herald Bot

A Python-based Telegram bot for notifying subscribers about power outages, generator events, and scheduled maintenance windows. Supports multiple chats, admin-controlled activation, and flexible power source management.

User-facing messages are configured in `locale.yaml`. Message templates use
Python format placeholders such as `{chat_id}` and `{source_name}`; keep the
placeholder names intact when customizing a message.

## Features

- **Multi-source monitoring**: Support for passive probing (bot pings device), active probing (device pings bot), and manual generator control
- **Grouped notifications**: Group passive sources into one named, described group; when every enabled source changes to the same state, one message includes per-source outage durations, otherwise only changed sources are notified
- **Smart notifications**: Includes state changes, outage durations, and generator maintenance schedules
- **Per-chat subscriptions**: Different buildings/groups can subscribe to specific power sources
- **Admin controls**: Manual activation approval, maintenance mode management, generator event configuration
- **Scheduled outages**: Daily posting of outage schedules (integration-ready for Yasno DTEK)
- **Database persistence**: ORM-based MySQL storage of state changes, outages, and subscriptions
- **OpenRC integration**: Systemd-free daemon management for Gentoo Linux
- **Webhook-based**: No long polling; efficient webhook integration with Telegram

## Architecture

```
├── src/
│   ├── models.py           # ORM models (PowerSource, Chat, Subscription, etc.)
│   ├── config.py           # Configuration loader (YAML)
│   ├── bot.py              # Telegram webhook bot & main entry point
│   ├── admin.py            # Admin commands (activation, maintenance, generator)
│   ├── probe.py            # Passive probing daemon (bot pings devices)
│   ├── processor.py        # State processor and notification daemon
│   ├── active_probe.py     # Active probe HTTP endpoint (devices ping bot)
│   ├── generator.py        # Generator state control used by the bot
│   ├── notify.py           # Notification logic (state changes + maintenance windows)
│   ├── outage_periods.py   # Outage period tracking & duration calculation
│   ├── maintenance.py      # Maintenance mode management
│   └── schedule.py         # Scheduled outage integration
├── init.d/                 # OpenRC init script for the combined daemon
├── config.yaml             # Configuration file (secrets & settings)
├── locale.yaml             # Localization for user messages
└── README.md               # This file
```

## Installation

### Prerequisites

- Python 3.12+
- MySQL 5.7+ (or compatible)
- Gentoo Linux with OpenRC (for daemon management)
- Telegram bot token (from @BotFather)
- Domain with SSL certificate (for webhooks)

### Setup

1. **Clone and prepare**:
```bash
git clone <repo> power-herald
cd power-herald
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Configure**:
```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your bot token, MySQL credentials, webhook URL, etc.
```

3. **Database**:
```bash
mysql -u root -p < schema.sql
```

### Database CLI

`ph-cli` provides database administration without opening a Python shell. Use
`--db-url` for a one-off database or omit it to use `config.yaml`:

```bash
./ph-cli db restore
./ph-cli groups add --name "Main buildings" --description "Primary sites"
./ph-cli sources add --name grid-a --type passive --address 192.0.2.10 --ping-method ping
./ph-cli group-sources add --group-id 1 --source-id 1
./ph-cli group-sources list
./ph-cli sources list --json
./ph-cli sources update 1 --enabled 0
./ph-cli sources remove 1
./ph-cli subscriptions list
./ph-cli power-states --source-id 1 --state offline
./ph-cli state-changes --from 2026-01-01T00:00:00Z --to 2026-01-31T23:59:59Z
./ph-cli outage-periods --source-id 1 --json
```

The CRUD resources are `groups`, `sources`, `group-sources`, `subscriptions`,
`chats`, and `maintenances`. Use `group-sources` to assign sources to groups;
source subtype options are accepted on `sources add` and `sources update` and
are optional. State snapshots, state
changes, and outage periods are list-only and support
`--source-id`, `--state`, `--from`, `--to`, and `--json` filters.

4. **OpenRC installation** (see OPENRC_SETUP.md):
```bash
sudo cp init.d/power-herald /etc/init.d/
sudo chmod +x /etc/init.d/power-herald
sudo rc-update add power-herald default
# Start services...
```

## Configuration

Edit `config.yaml` to customize:

```yaml
telegram:
  token: "YOUR_BOT_TOKEN"
  webhook_url: "https://your.domain/webhook"
  webhook_port: 8080

database:
  host: "localhost"
  user: "power_herald"
  password: "YOUR_PASSWORD"
  database: "power_herald"

admin:
  chat_ids: ["123456789", "987654321"]

probing:
  passive:
    interval_seconds: 30
    timeout_seconds: 5
  active:
    port: 8081

outages:
  source: "url" # "url" or "file"
  json_url: "https://raw.githubusercontent.com/Baskerville42/outage-data-ua/main/data/outages.json"
  json_file: "/path/to/outages.json"
  delay_seconds: 1800
  gpvs:
    - name: "Kyiv GPV 37.1"
      id: "GPV37.1"

timezone: "Europe/Kyiv" # IANA timezone used for application timestamps and schedules
```

See `config.yaml` for all available options.

## Usage

### Telegram Bot Commands (Admin Only)

- `/activate` - Request chat activation (notifies admin)
- `/approve <chat_id>` - Approve chat activation (admin only)
- `/maintenance <source_id|global> <on|off> [comment]` - Toggle maintenance mode
- `Start Generator` / `Stop Generator` - Control the generator from an activated chat

### Power Source Types

#### 1. Passive (Bot pings device)
- Bot periodically checks the device using the source's `ping_method`: `HTTP`, `PING3`, or `TCP`
- Use `HTTP` with a URL, `PING3` with a hostname/IP, or `TCP` with a `host:port` address
- State: ONLINE/OFFLINE
- Use case: Grid power lines, always-on devices

#### 2. Active (Device pings bot)
- Device sends HTTP POST to `/active_ping` endpoint
- Payload: `{"name": "source_name", "state": "online|offline"}`
- Use case: Devices with limited battery, smart controllers

#### 3. Generator (Manual control with maintenance)
- Manual start/stop via the localized buttons shown after chat activation
- Auto-generates maintenance windows:
  - Start: shows maintenance window (default +4 hours)
  - Stop: shows next working window (default +1 hour)
- Use case: Backup generators with scheduled maintenance

### HTTP Endpoints

**Active Probe** (port 8081):
```bash
POST /active_ping
{
  "name": "source_name",
  "state": "online|offline"
}
```

**Bot Webhook** (port 8080):
- Telegram webhook for bot commands and messages
- Automatically configured on startup

### Daemon Management (OpenRC)

```bash
sudo rc-service power-herald start
sudo rc-service power-herald stop

# Restart all
sudo rc-service power-herald restart

# Check status
sudo rc-service power-herald status

# View logs
sudo tail -f /var/log/power-herald/bot.log
```

For debugging, the individual workers remain available as standalone module
entry points, for example `venv/bin/python -m src.bot` or
`venv/bin/python -m src.processor`.

## Database Schema

### Key Tables

- `power_sources` - Device/generator definitions
- `state_changes` - State transitions (online/offline)
- `periods` - Online/offline source state periods with start/stop timestamps
- `chats` - Telegram chats subscribed to service
- `subscriptions` - Chat-to-source mappings
- `maintenance_modes` - Global or per-source maintenance toggles

## Workflow Examples

### Example 1: City Power Line Outage
1. Bot detects line is offline
2. Notification: "Line A: OFFLINE\nPrevious period: 2:15:30"
3. (Optional) Daily schedule posted at 07:00

### Example 2: Generator Activation
1. An activated chat presses `Start Generator`
2. Notification: "Generator: ONLINE\nMaintenance window: 14:00 - 15:00"
3. An activated chat presses `Stop Generator`
4. Notification: "Generator: OFFLINE\nNext working window: 19:00 onwards"

### Example 3: Multi-Building Setup
- Building A subscribed to: Line A, Line B, Generator 1
- Building B subscribed to: Line C, Generator 2
- Each receives relevant notifications independently
- Each activated chat receives generator notifications through its own subscription

## Troubleshooting

### Bot not responding
- Check webhook URL is accessible
- Verify bot token in config.yaml
- Check Telegram bot @BotFather settings

### No state changes recorded
- Verify passive probe interval (default 30s)
- Check device addresses in config
- Review logs for ping timeouts

### Notifications not sending
- Verify chat is activated (admin `/approve`)
- Check subscription is enabled in database
- Review bot token permissions

### Generator maintenance windows not showing
- Verify generator source type is "GENERATOR"
- Check work_duration_minutes and maintenance_duration_minutes in database

## Future Enhancements

- Direct Yasno DTEK API integration (when available)
- Web dashboard for status monitoring
- Telegram inline keyboards for quick actions
- Multiple generator groups/schedules
- Historical stats and analytics
- SMS/email fallback notifications

## License

TBD

## Support

For issues or questions, contact the administrator.
