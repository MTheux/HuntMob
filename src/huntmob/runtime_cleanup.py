"""Best-effort, centralized ownership cleanup for HuntMob runtime resources."""

from __future__ import annotations


def _step(results, name, operation):
    try:
        operation()
        results.append({"resource": name, "status": "closed"})
    except Exception:
        results.append({"resource": name, "status": "cleanup_failed"})


def cleanup_primary_session(lab_id: str, *, shutdown: bool = False) -> dict:
    """Close resources owned by one primary lab without exposing exception text."""
    from .codec_relay import CODEC_RELAY
    from .dynamic_runtime import DYNAMIC
    from .managed_proxy import stop_for_lab
    from .screen_relay import SCREEN_RELAY

    results = []
    _step(results, "analysis", DYNAMIC.stop)
    _step(results, "h264", CODEC_RELAY.shutdown if shutdown else CODEC_RELAY.restart)
    _step(results, "mjpeg", SCREEN_RELAY.shutdown if shutdown else SCREEN_RELAY.restart)
    _step(results, "proxy", lambda: stop_for_lab(lab_id))
    return {"ok": all(item["status"] == "closed" for item in results), "resources": results}


def cleanup_all() -> dict:
    """Close every server-owned runtime handle in a deterministic order."""
    from . import ios_proxy, ios_worker, reverse_engines, workspace_devices
    from .codec_relay import CODEC_RELAY
    from .dynamic_runtime import DYNAMIC
    from .screen_relay import SCREEN_RELAY

    results = []
    for name, operation in (
        ("android-analysis", DYNAMIC.stop),
        ("ios-proxy", ios_proxy.stop),
        ("workspace-devices", workspace_devices.shutdown),
        ("reverse-engines", reverse_engines.shutdown),
        ("ios-video", ios_worker.IOS_RELAY.shutdown),
        ("ios-input", ios_worker.close_input_bridge),
        ("android-h264", CODEC_RELAY.shutdown),
        ("android-mjpeg", SCREEN_RELAY.shutdown),
    ):
        _step(results, name, operation)
    return {"ok": all(item["status"] == "closed" for item in results), "resources": results}
