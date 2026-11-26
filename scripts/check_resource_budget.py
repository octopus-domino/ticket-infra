"""Check the resolved Compose memory limits without connecting to a daemon."""
import json
import re
import sys


def bytes_value(value):
    match = re.fullmatch(r'(\d+)\s*(b|[kmgt](?:i?b)?)?', str(value).lower())
    if not match:
        raise ValueError(f'Unsupported byte limit: {value}')
    unit = (match[2] or 'b')[0]
    return int(match[1]) * 1024 ** 'bkmgt'.index(unit)


def limits(config):
    for name, service in config['services'].items():
        soft = service.get('environment', {}).get('GOMEMLIMIT')
        if soft is None:
            continue
        try:
            hard_bytes = bytes_value(service.get('mem_limit'))
            soft_bytes = bytes_value(soft)
        except ValueError as error:
            raise ValueError(f'{name}: {error}') from error
        if not 0 < soft_bytes < hard_bytes:
            raise ValueError(f'{name}: GOMEMLIMIT {soft} leaves no headroom in {hard_bytes} bytes')
        print(f'{name}: soft={soft_bytes} hard={hard_bytes} headroom={hard_bytes - soft_bytes} bytes')


if __name__ == '__main__':
    try:
        limits(json.load(sys.stdin))
    except (KeyError, ValueError) as error:
        sys.exit(str(error))
