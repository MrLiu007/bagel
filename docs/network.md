# Network

## Modes

| Mode | Behavior |
|------|----------|
| `AUTO` | Direct first; retry via proxy when configured |
| `DIRECT` | Never use proxy |
| `PROXY` | External requests use proxy |

Internal hosts (`postgres`, `rsshub`, `freshrss`) stay on `NO_PROXY`.

## Degraded mode

If GitHub / overseas RSS is unreachable:

1. Record `PARTIAL` / warnings in job runs and doctor
2. Keep domestic RSS collection running
3. Do not crash the web app

## Local proxy in Docker

```env
HTTPS_PROXY=http://host.docker.internal:7890
HTTP_PROXY=http://host.docker.internal:7890
```

Compose already maps `host.docker.internal:host-gateway` for Linux.
