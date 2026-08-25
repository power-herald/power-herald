# Installation instructions for OpenRC daemon integration

## Prerequisites
- Gentoo Linux with OpenRC
- Python 3.12+ venv in /opt/power_herald
- User `power_herald` and group `power_herald` created

## Setup Steps

1. Create user and group:
```bash
useradd -m -d /opt/power_herald power_herald
groupadd power_herald
usermod -a -G power_herald power_herald
```

2. Copy init scripts to /etc/init.d/:
```bash
sudo cp init.d/power_herald_bot /etc/init.d/
sudo cp init.d/power_herald_passive_probe /etc/init.d/
sudo cp init.d/power_herald_active_probe /etc/init.d/
sudo cp init.d/power_herald_processor /etc/init.d/
sudo cp init.d/power_herald_schedule /etc/init.d/
sudo chmod +x /etc/init.d/power_herald_*
```

3. Install project to /opt/power_herald:
```bash
sudo mkdir -p /opt/power_herald
sudo cp -r . /opt/power_herald/
sudo chown -R power_herald:power_herald /opt/power_herald
```

4. Configure config.yaml:
```bash
sudo cp /opt/power_herald/config.yaml /etc/power_herald/config.yaml
sudo chown power_herald:power_herald /etc/power_herald/config.yaml
sudo chmod 600 /etc/power_herald/config.yaml
```

5. Enable and start services:
```bash
sudo rc-service power_herald_bot start
sudo rc-service power_herald_passive_probe start
sudo rc-service power_herald_active_probe start
sudo rc-service power_herald_processor start
sudo rc-service power_herald_schedule start

# Add to default runlevel (optional)
sudo rc-update add power_herald_bot default
sudo rc-update add power_herald_passive_probe default
sudo rc-update add power_herald_active_probe default
sudo rc-update add power_herald_processor default
sudo rc-update add power_herald_schedule default
```

## Management

```bash
# Check status
sudo rc-service power_herald_bot status

# Stop/restart
sudo rc-service power_herald_bot stop
sudo rc-service power_herald_bot restart

# View logs
sudo tail -f /var/log/power_herald/bot.log
```
