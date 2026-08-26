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
  "state": "online|offline"
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

## Generator Control

Generator state is controlled from the localized `Start Generator` and `Stop Generator`
buttons shown to activated chats. The old HTTP endpoint and `/generator` command are
no longer available. Each transition notifies subscribed, enabled chats and records
the generator maintenance window.


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
- `chat_id`: Chat ID to approve

**Example**: `/approve 1`

**Response**: "Chat Building A (1) activated."

---

### `/subscribe <chat_id> <source_id>`
Adds an enabled power source subscription to an activated or pending chat.

**Admin only**: Yes
**Args**:
- `chat_id`: Chat ID to subscribe
- `source_id`: Power source ID

**Example**: `/subscribe 1 1`

---

### `/sources`
Lists all configured power sources, including their IDs, types, and status.

**Admin only**: Yes

---

### `/chats`
Lists all registered chats and their activation status.

**Admin only**: Yes

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
