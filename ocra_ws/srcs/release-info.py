"""Read the version and official asset digest from GitHub release metadata."""
import json
import re
import sys


def release_info(release, arch):
    tag = release.get("tag_name", "")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag) or release.get("prerelease") or release.get("draft"):
        raise ValueError("官方最新发布版本格式异常")
    name = f"orca-server-linux-{arch}.tar.gz"
    assets = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(assets) != 1:
        raise ValueError(f"官方发布缺少唯一的 {name}")
    digest = assets[0].get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("官方安装包缺少有效 SHA256，停止安装")
    return tag[1:], digest.removeprefix("sha256:")


if __name__ == "__main__":
    try:
        print(*release_info(json.load(sys.stdin), sys.argv[1]))
    except (ValueError, KeyError, TypeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
