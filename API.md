# API Reference

## Endpoints

### Telegram Bot Webhook
**Port**: 8080  
**Path**: `/webhook` (configurable)  

Receives Telegram updates. Automatically configured on bot startup.

---

## Active Probe Endpoint

**Port**: 8081 (configurable)  
**Method**: POST  
**Path**: `/active_ping`

Devices send their power state to this endpoint. Used for active monitoring where the device initiates the check.

### Request
```json
{
  "name": "grid_line_main",
  "state": "online|offline|unstable"
}
```

### Response
```json
{
  "status": "ok"
}
```

### Error Responses
- 404: Source not found or not configured as active
- 400: Invalid state value
- 403: Maintenance mode enabled

---

## Generator Control Endpoint

**Port**: 8082 (configurable)  
**Method**: POST  
**Path**: `/generator`

Manually control generator state and trigger notifications with maintenance windows.

### Request
```json
{
  "source_name": "generator_1",
  "command": "start|stop"
}
```

### Response
```json
{
  "status": "ok"
}
```

### Behavior

#### On `start`:
1. Generator state changes to ONLINE
2. Notification sent to subscribed chats:
   - Shows generator is ON
   - Includes maintenance window: `start_time + work_duration`
3. GeneratorSession record created with maintenance window timestamps

#### On `stop`:
1. Generator state changes to OFFLINE
2. Notification sent to subscribed chats:
   - Shows generator is OFF
   - Includes next working window: `stop_time + maintenance_duration`
3. GeneratorSession record updated with stop time

### Example Usage

```bash
# Start generator
curl -X POST http://localhost:8082/generator \
  -H "Content-Type: application/json" \
  -d '{"source_name": "gen_main", "command": "start"}'

# Stop generator
curl -X POST http://localhost:8082/generator \
  -H "Content-Type: application/json" \
  -d '{"source_name": "gen_main", "command": "stop"}'
```

---

## Telegram Bot Commands

All commands are available only to authorized admin chats (configured in `config.yaml`).

### `/activate`
Requests chat activation. Sends activation request to admin chats for manual approval.

**Response**: "Activation request sent to admin."

---

### `/approve <chat_id>`
Approves and activates a chat that requested activation.

**Admin only**: Yes  
**Args**: 
- `chat_id`: Telegram chat ID to approve

**Example**: `/approve 123456789`

**Response**: "Chat Building A (123456789) activated."

---

### `/maintenance <source_id|global> <on|off> [comment]`
Toggle maintenance mode for a source or globally. When enabled, probes and notifications are suspended.

**Admin only**: Yes  
**Args**:
- `source_id` or `global`: Target source ID or "global" for all
- `on|off`: Enable or disable maintenance
- `comment` (optional): Reason for maintenance

**Examples**:
```
/maintenance 1 on Generator scheduled maintenance
/maintenance global off
```

**Response**: "Maintenance enabled for 1."

---

### `/generator <source_id> <on|off>`
Toggle generator event notifications for the current chat.

**Admin only**: Yes  
**Args**:
- `source_id`: Generator source ID
- `on|off`: Enable or disable notifications

**Example**: `/generator 5 on`

**Response**: "Generator notifications for Generator_1 set to on."

---

## Notification Messages

### Standard State Change
```
Line A: ONLINE
Previous period: 2:15:30
```

### Generator Start (with Maintenance Window)
```
Generator 1: ONLINE
Maintenance window: 14:00 - 15:00
```

### Generator Stop (with Next Working Window)
```
Generator 1: OFFLINE
Next working window: 19:00 onwards
```

### Scheduled Outages (Daily)
```
Outages for 2026-08-24:
  09:00 - 11:00
  14:00 - 16:30

Outages for 2026-08-25:
No outages scheduled.
```

---

## Error Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Bad request (invalid JSON or state) |
| 403 | Forbidden (maintenance mode enabled) |
| 404 | Resource not found |

---

## Rate Limits

- Passive probe: Interval configured in `config.yaml` (default 30s)
- Active probe: No hard limit; device-controlled
- Generator control: No hard limit
- Notifications: Sent per state change only (no flooding)

---

## Authentication

- Bot webhook: Secured by Telegram's callback validation
- Admin commands: Chat ID whitelist in `config.yaml`
- HTTP endpoints: Open (recommended behind firewall or reverse proxy with auth)

**Recommendation**: Deploy behind nginx/Apache with basic auth or IP whitelisting for HTTP endpoints.
