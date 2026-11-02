#!/usr/bin/env python3
"""Print Windows Inferno worker readiness; never installs or boots anything."""

import json

from huntmob.ios_inferno_windows import snapshot


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2, ensure_ascii=False))
