# pytronkitTelemetry: Automated Flight Recorder

**pytronkitTelemetry** is a robust, "flight recorder" style telemetry and crash reporting plugin for Pytron applications. It provides real-time visibility into your application's health, usage patterns, and stability issues without blocking the main execution thread.

## Features

-   **Background Flight Recorder**: Runs a lightweight background thread to queue and upload telemetry data, ensuring the main application UI remains responsive.
-   **Automated Crash Handler**: Hooks into `sys.excepthook` to capture unhandled exceptions, creating a "Black Box" report containing the traceback and last known application state before the process dies.
-   **Intelligent Sanitization**: Automatically strips sensitive information (keys containing "password", "token") from state snapshots before transmission.
-   **Configurable Modes**:
    -   `activity` (Default): High-frequency checks (5s) for detailed usage tracking.
    -   `minimal`: Low-frequency heartbeats (5m) for lightweight monitoring.
    -   `errors_only`: Disables heartbeats; only reports crashes.
-   **Resource Monitoring**: Captures System OS info and RAM usage (via `psutil`).

## Configuration

Configure the plugin in your `manifest.json` or pass arguments during initialization.

### Manifest Configuration (`manifest.json`)

```json
{
    "name": "pytronkitTelemetry",
    "config": {
        "telemetry_url": "https://api.myapp.com/telemetry",
        "crash_url": "https://api.myapp.com/crash"
    }
}
```

### Runtime Options

-   `mode`: Set the operation mode (`activity`, `minimal`, `errors_only`).
-   `url` / `telemetry_url`: Endpoint for heartbeat data.
-   `crash_url`: Endpoint for crash reports.

## Usage

The plugin automatically hooks into the application lifecycle upon `setup()`.

### Manual Initialization (if needed)

```python
plugin = PytronkittelemetryPlugin(
    app, 
    mode="minimal", 
    telemetry_url="https://analytics.example.com",
    crash_url="https://analytics.example.com/crash"
)
plugin.setup()
```

### Data Payloads

#### Heartbeat Payload
```json
{
    "type": "heartbeat",
    "session": "unique-session-id",
    "state": { ...application_state... },
    "system": { "os": "Windows", ... },
    "ram_usage": 45.2,
    "timestamp": 1234567890.0
}
```

#### Crash Payload
```json
{
    "type": "crash",
    "session": "unique-session-id",
    "error": "ZeroDivisionError: division by zero",
    "traceback": "...stack trace...",
    "os": "Windows-10-...",
    "last_state": { ...state_at_crash... }
}
```

## Dependencies

-   `requests`: For HTTP transmission.
-   `psutil`: For system resource monitoring.
