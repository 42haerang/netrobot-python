"""Generate machine-local settings without publishing shared control credentials."""
import argparse
import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pc'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', help='Example: http://192.168.0.10:8765')
    args = parser.parse_args()
    from server import local_ip
    settings_path = ROOT / 'settings.json'
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding='utf-8'))
        print('Keeping existing settings.json')
    else:
        settings = json.loads((ROOT / 'settings.example.json').read_text(encoding='utf-8'))
        settings['control_token'] = secrets.token_hex(24)
        settings['pairing_code'] = f'{secrets.randbelow(1000000):06d}'
        settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Created settings.json (simulation mode)')
    config_path = ROOT / 'phone/config.json'
    if config_path.exists():
        print('Keeping existing phone/config.json')
    else:
        config = {'server': args.server or f'http://{local_ip()}:{settings.get("port", 8765)}',
                  'token': settings['control_token']}
        config_path.parent.mkdir(exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
        print('Created phone/config.json')
    print('Local settings contain credentials: do not share these files.')


if __name__ == '__main__':
    main()
