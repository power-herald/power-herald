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
sudo cp init.d/power_herald /etc/init.d/
sudo chmod +x /etc/init.d/power_herald
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
sudo rc-service power_herald start

# Add to default runlevel (optional)
sudo rc-update add power_herald default
```

## Management

```bash
# Check status
sudo rc-service power_herald status

# Stop/restart
sudo rc-service power_herald stop
sudo rc-service power_herald restart

# View logs
sudo tail -f /var/log/power_herald/server.log
```
