"""Versioned, provider-neutral device session contract for the web workspace."""

from __future__ import annotations

from datetime import datetime, timezone


SCHEMA = "huntmob.device-session/v1"


def _stream(relay_snapshot, online):
    state = relay_snapshot.get("state", "idle")
    if state == "running":
        status = "streaming"
    elif state == "error":
        status = "error"
    elif online:
        status = "idle"
    else:
        status = "unavailable"
    return {
        "status": status,
        "transport": relay_snapshot.get("transport"),
        "generation": relay_snapshot.get("generation"),
        "frames": relay_snapshot.get("frames", 0),
        "width": relay_snapshot.get("width"),
        "height": relay_snapshot.get("height"),
        "error": bool(relay_snapshot.get("error")),
        "telemetry": relay_snapshot.get("telemetry", {}),
    }


def capabilities(platform, *, primary=False, root_mode=None):
    """Advertise implemented operations, never capabilities inferred from liveness."""
    android = platform == "android"
    return {
        "lifecycle": ["start", "stop"] if not primary else ["stop"],
        "display": {"stream": True, "screenshot": True, "input": True},
        "input_actions": (["touch", "text", "key", "home", "back"] if android
                          else ["touch", "text", "key", "home", "recents", "lock"]),
        "apps": {"install": True, "open_store": android and root_mode == "stock"},
        "security": {
            "rea_static": True,
            "rea_dynamic_evidence": android,
            "frida": android,
            "frida_experimental": not android,
            "deep_dast": android,
            "physical_device": False,
            "root_profile": android and root_mode == "root",
        },
    }


def describe(record, status, relay_snapshot, *, primary=False):
    platform = record.get("platform", "android")
    online = (status.get("state") == "device" and
              status.get("properties", {}).get("sys.boot_completed") == "1" and
              status.get("ownership_verified") is True)
    generation = relay_snapshot.get("generation")
    return {
        "schema": SCHEMA,
        "identity": {
            "device_id": record["id"],
            "workspace_id": record.get("workspace_id", record["id"]),
            "platform": platform,
            "serial": record.get("serial"),
            "physical": False,
        },
        "lifecycle": {
            "status": "online" if online else "error" if status.get("state") == "error" else "offline",
            "ownership_verified": status.get("ownership_verified") is True,
        },
        "channels": {
            "stream": _stream(relay_snapshot, online),
            "input": {
                "status": "ready" if online and relay_snapshot.get("input_ready") else "idle" if online else "unavailable",
                "generation": generation,
            },
            "settings": {"status": "ready", "generation": generation},
        },
        "capabilities": capabilities(platform, primary=primary, root_mode=record.get("root_mode")),
    }


def inventory(workspace_id, primary, devices, errors):
    return {
        "schema": "huntmob.device-inventory/v1",
        "workspace_id": workspace_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary": primary,
        "devices": devices,
        "discovery_errors": errors,
    }
