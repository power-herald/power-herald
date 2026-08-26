# Installation instructions for OpenRC daemon integration

## Prerequisites
- Gentoo Linux with OpenRC
- Python 3.12+ venv in /opt/power-herald
- User `powerherald` and group `powerherald` created

## Setup Steps

1. Create user and group:
```bash
useradd -m -d /opt/power-herald powerherald
groupadd powerherald
usermod -a -G powerherald powerherald
```

2. Copy init scripts to /etc/init.d/:
```bash
sudo cp init.d/power-herald /etc/init.d/
sudo chmod +x /etc/init.d/power-herald
```

3. Install project to /opt/power-herald:
```bash
sudo mkdir -p /opt/power-herald
sudo cp -r . /opt/power-herald/
sudo chown -R powerherald:powerherald /opt/power-herald
```

4. Configure config.yaml:
```bash
sudo cp /opt/power-herald/config.yaml /etc/power-herald/config.yaml
sudo chown powerherald:powerherald /etc/power-herald/config.yaml
sudo chmod 600 /etc/power-herald/config.yaml
```

5. Enable and start services:
```bash
sudo rc-service power-herald start

# Add to default runlevel (optional)
sudo rc-update add power-herald default
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
