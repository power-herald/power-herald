# Outage schedule notifications

This document describes the `TODAY`, `TOMORROW`, and `IMMEDIATE` outage
notifications, how their target dates relate, and how duplicate schedule
messages are avoided.

## Notification types

| Type | When it is sent | `posted_for` | Duplicate checks |
| --- | --- | --- | --- |
| `IMMEDIATE` | When `update_once()` sends an automatic update for the current day | The current day | Latest `IMMEDIATE`, `TOMORROW`, and `TODAY` notification for that target date |
| `TODAY` | At `outages.schedule_send_time.today`, if today's schedule has offline or unspecified periods | The current day | Latest `TODAY` and `IMMEDIATE` notification for that target date |
| `TOMORROW` | At `outages.schedule_send_time.tomorrow` | The next day | Latest `TOMORROW` notification for that target date |

`posted_for` is the date the schedule describes, not necessarily the date the
notification was sent. For example, a TOMORROW notification sent Monday for
Tuesday is stored with `posted_for=Tuesday`. On Tuesday, an immediate update
checks that TOMORROW record because it may already have delivered Tuesday's
schedule.

The schedule worker runs `update_once()` before checking the configured TODAY
and TOMORROW send times. Those times can be disabled in configuration. The
worker may therefore check a send time repeatedly; the notification records
make subsequent checks idempotent when the schedule hash is unchanged.

## Priority and relationships

`IMMEDIATE` updates have higher priority than scheduled TODAY and TOMORROW
notices. The duplicate checks are target-date-specific:

- If yesterday's TOMORROW notice already sent today's schedule, a matching
  immediate update for today is suppressed.
- If an immediate update already sent today's schedule, a matching TODAY
  notice for today is suppressed.
- An immediate update is only for the current day. It does not cover a
  TOMORROW notice for the next day, so TOMORROW checks only prior TOMORROW
  notices for that next-day target.
- Different notification types can be recorded for the same target date when
  their daily hashes differ. Each check compares the latest notification of
  each relevant type, rather than only the newest record overall.

For example:

```text
Monday evening: TOMORROW posted for Tuesday
Tuesday morning: IMMEDIATE for Tuesday checks the TOMORROW hash and avoids a
                 duplicate if Tuesday's schedule is unchanged
Tuesday scheduled time: TODAY for Tuesday checks the IMMEDIATE hash and avoids
                        a duplicate if Tuesday's schedule is unchanged
Tuesday evening: TOMORROW for Wednesday is independent of Tuesday's IMMEDIATE
```

## Hashing and persistence

Notifications are recorded in the `outage_notifications` table:

- `type` is `today`, `tomorrow`, or `immediate`.
- `posted_for` is the target schedule date.
- `posted_at` is when the notification record was created after the send attempt.
- `schedule_hash` identifies the schedule for `posted_for`.

The schedule hash is calculated from that date's data for each group: its
outage periods, whether that day is unspecified, and its emergency status.
It does not include the other days in the weekly schedule. A change to another
weekday therefore does not make the current day's notification appear new.

The worker keeps a separate `Outage.message_hash` for detecting changes to a
group's prepared message, which includes the weekly schedule. Once changed
messages are found, `schedule_hash` determines whether the schedule for the
target day has already been sent.

Duplicate checks compare hashes for the same target date. A matching hash
suppresses a send; a different hash allows the changed daily schedule to be
sent. Immediate updates also require the overall emergency state to be
unchanged before the duplicate check suppresses their schedule messages.

A notification record is added after a non-empty schedule batch is passed to
`send_messages`. Emergency broadcasts are handled separately from these
schedule notification records.

## Sending conditions

- `TODAY` is skipped while global emergency mode is active, when every group is
  marked emergency, or when there are no offline or unspecified periods for
  the target day.
- `TOMORROW` omits groups marked emergency. It can still send when the target
  day has no offline periods.
- `IMMEDIATE` sends changed non-emergency group schedules. Emergency state
  transitions are broadcast separately.
