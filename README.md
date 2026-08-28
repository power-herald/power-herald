# Power Herald Bot

A Python-based Telegram bot for notifying subscribers about power outages, generator events with maintenance windows, outages schedule, etc. Supports multiple chats, admin-controlled activation, and flexible power source management.

User-facing messages are configured in `locale.yaml`. Message templates use
Python format placeholders such as `{chat_id}` and `{source_name}`; keep the
placeholder names intact when customizing a message.

## Features

- **Multi-source monitoring**: Support for passive probing (bot pings device), active probing (device pings bot), and manual notifications.
- **Grouped notifications**: Group power sources into one named, described group; when every enabled source changes to the same state, one message includes per-source outage durations, otherwise only changed sources are notified
- **Smart notifications**: Includes state changes, outage durations, and generator maintenance schedules
- **Per-chat subscriptions**: Different buildings/groups can subscribe to specific power sources
- **Admin controls**: Manual activation approval, maintenance mode management, generator event configuration
- **Scheduled outages**: Daily posting of outage schedules (third-party source, aggregated from Yasno/DTEK)
- **Database persistence**: ORM-based MariaDB/MySQL or SQLite storage of state changes, outages, and subscriptions
- **OpenRC integration**: Systemd-free daemon management for Gentoo Linux
- **Webhook-based**: No long polling; efficient webhook integration with Telegram

## Architecture

```
├── power_herald/
│   ├── models.py           # ORM models (PowerSource, Chat, Subscription, etc.)
│   ├── config.py           # Configuration loader (YAML)
│   ├── bot.py              # Telegram webhook bot & it's main entry point
│   ├── admin.py            # Admin commands (activation, maintenance, generator)
│   ├── probe.py            # Passive probing daemon (bot pings devices)
│   ├── processor.py        # State processor and notification daemon
│   ├── active_probe.py     # Active probe HTTP endpoint (devices ping bot)
│   ├── generator.py        # Generator state control used by the bot
│   ├── notify.py           # Notification logic (state changes + maintenance windows)
│   ├── outage_data.py      # Third-party source of outage schedule retrieving and parsing
│   ├── outage_periods.py   # Outage period tracking & duration calculation
│   ├── maintenance.py      # Maintenance mode management
│   ├── schedule.py         # Outage schedule notifications (from-today-for-today, from-today-for-tomorrow)
│   ├── cli.py              # Console management client application for database entities
│   ├── server.py           # All-in-one daemon to run separated modules
│   ├── lifecycle.py        # Daemon utils
│   ├── messages.py         # User messages interpolation and preparation
│   └── state_store.py      # Power source state changes recording routines
├── pyproject.toml          # Python packaging metadata (console scripts, dependencies)
├── config.yaml             # Configuration file (secrets & settings, installed to /etc/power-herald/)
├── locale.yaml             # Localization for user messages (installed to /etc/power-herald/)
└── README.md               # This file
```

The OpenRC init script, conf.d defaults, and Gentoo ebuild live in the
separate `power-herald` overlay (see the `portage/` repository next to this
project) rather than in this source tree.

---

## Installation

### Gentoo (recommended)

Power Herald ships as a Gentoo ebuild in the companion `power-herald` overlay.
The ebuild pulls in all Python dependencies from the main tree, creates the
`power-herald` system user/group, and installs the OpenRC service:

```bash
emerge --sync power-herald-overlay   # or eselect repository add power-herald-overlay <url>
emerge --ask app-misc/power-herald
```

This installs:
- the `ph-cli` and `ph-server` executables into `/usr/bin`
- `config.yaml` and `locale.yaml` into `/etc/power-herald/` (edit these in place)
- the OpenRC init script and `/etc/conf.d/power-herald` defaults

See `OPENRC_SETUP.md` for enabling and managing the service.

### Manual / development setup

- Python 3.12+
- SQLite (built into Python), or MariaDB 10.2 / MySQL 5.7+
- Telegram bot token (from @BotFather)
- Domain with SSL certificate (for webhooks)

```bash
git clone <repo> power-herald
cd power-herald
python3 -m venv venv
source venv/bin/activate
# Only SQLite support:
pip install -e .
# Extra driver for MariaDB/MySQL support:
# pip install -e ".[mariadb]"
cp config.yaml.example config.yaml
# Edit config.yaml with your bot token, database settings, webhook URL, etc.
# For SQLite, set database.driver to sqlite and database.database to a file path.
# The tables are created automatically by the CLI:
./ph-cli db restore
# assets/schema.sql is only for MariaDB/MySQL deployments.
```

### Docker

Build the image with Python 3.14 slim:

```bash
docker build --tag power-herald:latest .
```

Provide `config.yaml` at runtime so secrets are not included in the image. The
container creates its SQLite tables on startup. To configure database entities,
mount shell scripts into `/docker-init.d`; they run in filename order and can
make sequential `ph-cli` calls. For example, create `docker-init.d/10-sources.sh`:

```sh
if [ ! -e /app/power_herald.db ]; then
  ph-cli db restore
  ph-cli groups add --name "Main buildings" --description "Primary sites"
  ph-cli sources add --name grid-a --type passive --address 192.0.2.10 --ping-method ping
  ph-cli group-sources add --group-id 1 --source-id 1
fi
```

This guard uses the default SQLite path. Update `/app/power_herald.db` when
`database.database` in `config.yaml` uses a different path.

Mount that directory when starting the container:

```bash
docker run --detach --name power-herald \
  --restart unless-stopped \
  --publish 8080:8080 --publish 8081:8081 \
  --volume "$(pwd)/config.yaml:/app/config.yaml:ro" \
  --volume "$(pwd)/docker-init.d:/docker-init.d:ro" \
  power-herald:latest
```

The administrator chat ID is not known before the first startup. Start the
container, send the bot a message from the intended administrator chat, and
retrieve that chat's ID from the container logs. Add the ID to
`admin.chat_ids` in the mounted `config.yaml`, then restart the container.

Initialization scripts execute each time the container starts, so make them
idempotent or remove the initialization mount after the first successful
startup. SQLite state is intentionally ephemeral; mount a writable data volume
and configure `database.database` with its path only when state must persist.
Set `POWER_HERALD_CONFIG` when mounting the configuration at a different path.

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

**OpenRC installation** (see OPENRC_SETUP.md): the ebuild installs the init
script automatically; just enable and start it:
```bash
sudo rc-update add power-herald default
sudo rc-service power-herald start
```

---

## Configuration

Edit `config.yaml` to change the needed minimum that must be defined:

```yaml
telegram:
  token: "YOUR_BOT_TOKEN"
  webhook_url: "https://your.domain/webhook"
  webhook_secret: "YOUR_WEBHOOK_SECRET"

database:
  driver: "sqlite"  # or "mysql+pymysql"
  database: "./power_herald.db"
  # For mysql+pymysql:
  host: "localhost"
  user: "power_herald"
  password: "YOUR_PASSWORD"
  database: "power_herald"

admin:
  chat_ids: ["123456789", "987654321"]

outages:
  gpvs:
    - name: "Kyiv GPV 37.1"
      id: "GPV37.1"

```

See `config.yaml` for all available options.

---

## Usage

### Telegram Bot Commands (Admin Only)

- `/activate` - Request chat activation (notifies admin)
- `/approve <chat_id>` - Approve chat activation (admin only)
- `/maintenance <source_id|global> <on|off> [comment]` - Toggle maintenance mode
- `Start Generator` / `Stop Generator` - Control the generator from an activated chat

### Power Source Types

#### 1. Passive (Bot pings device)
- Bot periodically checks the device using the source's `ping_method`: `HTTP`, `PING`, or `TCP`
- Use `HTTP` with a URL, `PING` with a hostname/IP, or `TCP` with a `host:port` address
- State: ONLINE/OFFLINE
- Use case: Devices, those are reachable from the Internet 

#### 2. Active (Device pings bot)
- Device sends HTTP POST to `/ping` endpoint
- Payload: `{"name": "source_name", "state": "online|offline"}`
- Use case: Smart devices, controllers, etc.

#### 3. Manual control (By user via chat)
- Manual start/stop via the localized buttons shown after chat activation
- Auto-generates maintenance windows:
  - Start: shows maintenance window (default is +4 hours from now)
  - Stop: shows next working window (default is +1 hour from now)
- Use case: Backup generators with scheduled maintenance

### HTTP Endpoints

**Active Probe** (port 8081):
```bash
POST /ping
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
sudo rc-service power-herald restart

# Check status
sudo rc-service power-herald status

# View logs
sudo tail -f /var/log/power-herald/server.log
```

For debugging, the individual workers remain available as standalone module
entry points, for example `venv/bin/python -m power_herald.bot` or
`venv/bin/python -m power_herald.processor`.

---

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
- Each activated chat receives own generator notifications through its own subscription

---

## Troubleshooting

### Bot not responding
- Check webhook URL is accessible
- Verify bot token in config.yaml
- Check Telegram bot @BotFather settings

## Regular ping is not working
- Check (PING3 Troubleshooting)[ping3-ts], especially on Debian-based systems

### No state changes recorded
- Verify passive probe interval (default 30s)
- Check device addresses in config
- Review logs for ping timeouts

### Notifications not sending
- Verify chat is activated (admin `/approve`)
- Check subscription is enabled in database
- Review bot token permissions

### Generator maintenance windows not showing
- Verify generator source type is "MANUAL", it is marked as generator, and it is linked to the chat
- Check work_duration_minutes and maintenance_duration_minutes in database

---

## Future Enhancements

- [ ] Web dashboard for status monitoring
- [ ] Telegram inline keyboards for quick actions
- [ ] Historical stats and analytics notifications
- [ ] Other messangers integration
- [ ] Email fallback notifications
- [ ] Docker image
- [ ] Systemd integration
- [ ] Debian-based package distribution (`*.deb`) 

## License

MIT License at [LICENSE]

## Support

For questions, contact the administrator.

For issues use issue tracker.

---
[ping3-ts]: https://github.com/kyan001/ping3/blob/master/TROUBLESHOOTING.md
