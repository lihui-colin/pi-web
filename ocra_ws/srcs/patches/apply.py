#!/usr/bin/env python3
"""Apply checked, idempotent patches to an installed server-only release."""
import json
import os
import stat
import tempfile
from pathlib import Path
import re
import sys


def apply(release):
    for spec_path in sorted((Path(__file__).parent / "service").glob("*.json")):
        spec = json.loads(spec_path.read_text())
        target = release / spec["file"]
        source = target.read_text()
        if spec["marker"] in source:
            print(f"补丁已存在：{spec_path.name}")
            continue
        if len(re.findall(spec["pattern"], source)) != 1:
            raise RuntimeError(f"补丁与发布版本不兼容，未修改文件：{spec_path.name} ({target})")
        updated = re.sub(spec["pattern"], spec["replacement"], source)
        fd, staged = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(staged, stat.S_IMODE(target.stat().st_mode))
            os.replace(staged, target)
        finally:
            Path(staged).unlink(missing_ok=True)
        print(f"已应用补丁：{spec_path.name}，下次服务启动生效。")


if __name__ == "__main__":
    apply(Path(sys.argv[1]).resolve())
