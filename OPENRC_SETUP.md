# Installation instructions for OpenRC daemon integration

Power Herald is packaged as a Gentoo ebuild (`app-misc/power-herald`) in the
companion `power-herald` overlay. The ebuild takes care of the OpenRC
integration described below; this document explains what it does and how to
manage the resulting service.

## Prerequisites

- Gentoo Linux with OpenRC
- The `power-herald` overlay added to your Portage configuration

## What the ebuild installs

- The application and its Python dependencies (via `dev-python/*` packages)
- The `power-herald` system user and group (`acct-user/power-herald`,
  `acct-group/power-herald`)
- `/usr/bin/ph-server` and `/usr/bin/ph-cli`
- `/etc/power-herald/config.yaml` and `/etc/power-herald/locale.yaml`
- `/etc/init.d/power-herald` and `/etc/conf.d/power-herald`
- `/var/log/power-herald/`, owned by `power-herald:power-herald`
- `/var/lib/power-herald/` when installed with the `sqlite` USE flag

Choose exactly one database backend when installing:

```bash
sudo emerge --ask app-misc/power-herald     # defaults to MariaDB
sudo emerge --ask 'app-misc/power-herald[sqlite,-mariadb]'
```

The SQLite USE flag changes the installed config to use
`/var/lib/power-herald/power_herald.db`. Its tables are created automatically;
the repository's `assets/schema.sql` is only for MariaDB/MySQL.

## Setup Steps

1. Install the package:
```bash
sudo emerge --ask app-misc/power-herald
```

2. Edit the configuration (installed with restrictive permissions since it
   holds secrets):
```bash
sudo -e /etc/power-herald/config.yaml
```

3. Review `/etc/conf.d/power-herald` if you need to change the user, group,
   log files, or pidfile used by the init script. `PH_READY_TIMEOUT` controls
   how long `rc-service power-herald start` waits for the daemon to finish
   its startup sequence (setting the Telegram webhook, configuring bot
   commands, etc.) before reporting the service as started.

4. Enable and start the service:
```bash
sudo rc-update add power-herald default
sudo rc-service power-herald start
```

## Management

```bash
# Check status
sudo rc-service power-herald status

# Stop/restart
sudo rc-service power-herald stop
sudo rc-service power-herald restart

# View logs
sudo tail -f /var/log/power-herald/server.log
```

