import sys
import threading
import json
import platform
import requests
import logging
import traceback
from queue import Queue, Full

class PytronkittelemetryPlugin:
    def __init__(self, app, telemetry_url=None, crash_url=None, mode="activity", **kwargs):
        self.app = app
        self.logger = logging.getLogger(f"Plugin.pytronkitTelemetry")
        self.queue = Queue(maxsize=100)  # Buffer to prevent memory leaks

        # Modes: 
        # "activity": Heartbeats + Crashes (Default)
        # "errors_only": Only catch unhandled exceptions
        # "minimal": Heartbeats every 5 mins + Crashes
        # Normalize mode
        if isinstance(mode, str):
            mode = mode.lower().strip()
            if mode in ["error_only", "errors_only"]:
                mode = "errors_only"
        self.mode = mode

        # ...
        
        # Priority: 1. Constructor, 2. App Config, 3. Plugin Manifest Config, 4. Default
        # Note: self.app.plugins might not be fully populated yet if called from load()
        # but SupervisedApp (the 'app' here) has access to the app's config.
        
        # We try to find our own plugin object to get its manifest config
        plugin_manifest_config = {}
        if hasattr(app, "_app"): # We are in a SupervisedApp
            for p in getattr(app._app, "plugins", []):
                if p.name == "pytronkitTelemetry":
                    plugin_manifest_config = p.config
                    break

        # Check for both 'url' and 'telemetry_url' aliases
        self.telemetry_url = telemetry_url or \
            kwargs.get("url") or \
            app.config.get("telemetry_url") or \
            plugin_manifest_config.get("telemetry_url") or \
            "https://api.myapp.com/telemetry"
            
        self.crash_url = crash_url or \
            app.config.get("crash_url") or \
            plugin_manifest_config.get("crash_url") or \
            "https://api.myapp.com/crash"

        # Fallback for session_id if not present in app state
        self.session_id = getattr(self.app.state, "session_id", "unknown-session")
        self._stop_event = threading.Event()
        self._original_hook = None

    def setup(self):
        """Standard Pytron plugin setup hook."""
        self._timer = None
        
        # 1. The Flight Recorder (Background Thread)
        self._worker = threading.Thread(target=self._upload_worker, daemon=True)
        self._worker.start()

        # 2. Hook Global Crashes (The "Black Box")
        self._original_hook = sys.excepthook
        sys.excepthook = self._crash_handler

        # 3. Snapshot State periodically if enabled
        if self.mode != "errors_only":
            self._start_snapshot_timer()
        else:
            self.logger.info("Snapshot timer skipped (errors_only mode)")

        self.logger.info(f"Telemetry Flight Recorder started in '{self.mode}' mode.")

    def _start_snapshot_timer(self):
        if not self._stop_event.is_set() and self.mode != "errors_only":
            self._snapshot_state()
            
            # Determine interval based on mode
            # For this test environment, we keep 'activity' fast (5s)
            intervals = {
                "activity": 5.0,     # High frequency for activity tracking (testing)
                "minimal": 300.0,    # 5 minutes for lightweight monitoring
                "default": 60.0      # Standard heartbeat
            }
            interval = intervals.get(self.mode, intervals["default"])
            
            self._timer = threading.Timer(interval, self._start_snapshot_timer)
            self._timer.daemon = True
            self._timer.start()

    def _snapshot_state(self):
        """Captures a lightweight snapshot of user state."""
        if self._stop_event.is_set():
            return

        try:
            # Check if app and state are still valid
            if not self.app or not hasattr(self.app, "state"):
                return
            
            # Create a shallow copy first to avoid iteration errors during snapshotting
            # if the main thread is modifying the state simultaneously.
            state_snapshot = self.app.state.to_dict().copy() 
            
            # SANITIZATION: Remove sensitive keys before queuing
            safe_state = {k: v for k, v in state_snapshot.items() if "password" not in k.lower() and "token" not in k.lower()}
            
            # Get System Info from App
            try:
                system_info = self.app.get_system_info()
            except:
                system_info = {"os": platform.system()}

            # Get RAM usage via psutil as suggested in blueprint
            try:
                import psutil
                ram_usage = psutil.virtual_memory().percent
            except ImportError:
                ram_usage = "unknown"

            payload = {
                "type": "heartbeat",
                "session": self.session_id,
                "state": safe_state,
                "system": system_info,
                "ram_usage": ram_usage,
                "timestamp": __import__("time").time()
            }
            try:
                self.queue.put_nowait(payload)
            except Full:
                self.logger.warning("Telemetry queue full, dropping heartbeat.")
        except Exception as e:
            self.logger.error(f"Error during snapshot: {e}")

    def _crash_handler(self, exc_type, exc_value, exc_traceback):
        """Catch unhandled exceptions, log them, then let the app crash."""
        crash_report = {
            "type": "crash",
            "session": self.session_id,
            "error": str(exc_value),
            "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
            "os": platform.platform(),
            "last_state": self.app.state.to_dict().copy()
        }
        
        # Force a synchronous send because the process is dying
        try:
            self.logger.error(f"CRASH REPORT: {json.dumps(crash_report)}")
            if "myapp.com" not in self.crash_url: # Only send if user changed the default
                requests.post(self.crash_url, json=crash_report, timeout=2)
        except Exception as e:
            self.logger.error(f"Failed to send crash report: {e}")
            
        # Call the original hook so the user still sees the error
        if self._original_hook:
            self._original_hook(exc_type, exc_value, exc_traceback)

    def _upload_worker(self):
        """Consumer thread that sends data to your server."""
        while not self._stop_event.is_set():
            try:
                # Wait for data or timeout
                payload = self.queue.get(timeout=5)
                # In a real app, replace with your actual endpoint
                try:
                    self.logger.debug(f"Telemetry Payload: {json.dumps(payload, indent=2)}")
                    if "myapp.com" not in self.telemetry_url: # Only send if user changed the default
                        requests.post(self.telemetry_url, json=payload, timeout=5)
                except Exception as e:
                    self.logger.debug(f"Silent telemetry send failure: {e}")
                finally:
                    self.queue.task_done()
            except:
                # Timeout, just loop again
                continue

    def teardown(self):
        """Clean up resources on plugin unload."""
        self._stop_event.set()
        if self._timer:
            try:
                self._timer.cancel()
            except:
                pass
        if self._original_hook:
            sys.excepthook = self._original_hook
        self.logger.info("Telemetry Plugin torn down.")
