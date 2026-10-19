import json
import ipaddress
from pathlib import Path


def config(path):
    value = json.loads(Path(path).read_text())
    if set(value) != {'host', 'port', 'threads', 'max_seconds', 'final_timeout_seconds'}:
        raise ValueError('Unknown or missing configuration fields')
    if not ipaddress.ip_address(value['host']).is_loopback:
        raise ValueError('Only loopback listening is supported')
    for name, low, high in [('port', 1, 65535), ('threads', 1, 32),
                            ('max_seconds', 1, 120), ('final_timeout_seconds', 1, 120)]:
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError(f'Invalid {name}')
    return value

