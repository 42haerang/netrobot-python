"""Publish reviewed APK/model artifacts to this project's public GitHub Releases.

Uses the user's existing Git credential manager in memory. Tokens are never
printed, saved in files, or included in shell arguments. Creates a draft,
uploads all assets, then publishes; an interrupted draft can be resumed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import requests

REPO = '42haerang/netrobot-python'
API = f'https://api.github.com/repos/{REPO}'


def publish(tag, commit, body_file, assets):
    credential = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', text=True,
        capture_output=True, check=True,
        env={**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0'})
    fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    token = fields.get('password')
    if not token:
        raise RuntimeError('No existing GitHub credential; no credentials printed')
    session = requests.Session()
    session.headers.update({'Authorization': f'Bearer {token}',
                            'Accept': 'application/vnd.github+json',
                            'X-GitHub-Api-Version': '2022-11-28'})
    existing = session.get(API+'/releases', params={'per_page': 100}, timeout=30)
    existing.raise_for_status()
    release = next((r for r in existing.json() if r['tag_name'] == tag), None)
    if release and not release['draft']:
        raise RuntimeError('Preserve the already published release; use a new version')
    body = Path(body_file).read_text(encoding='utf-8')
    if release is None:
        created = session.post(API+'/releases', json={'tag_name': tag, 'target_commitish': commit,
            'name': 'NetRobot Drone '+tag.removeprefix('android-'),
            'body': body, 'draft': True, 'prerelease': True}, timeout=30)
        created.raise_for_status()
        release = created.json()
    existing_assets = {a['name']: a for a in release['assets']}
    for filename in assets:
        path = Path(filename)
        with path.open('rb') as content:
            digest = hashlib.file_digest(content, 'sha256').hexdigest()
        if path.name in existing_assets:
            asset = existing_assets[path.name]
            if asset['size'] != path.stat().st_size or asset.get('digest') != 'sha256:'+digest:
                raise RuntimeError('Existing draft asset differs; preserve and inspect: '+path.name)
            print('ASSET_ALREADY_PRESENT', path.name, flush=True)
            continue
        with path.open('rb') as content:
            uploaded = session.post(release['upload_url'].split('{')[0],
                params={'name': path.name}, data=content,
                headers={'Content-Type': 'application/octet-stream'}, timeout=(30, 600))
        uploaded.raise_for_status()
        asset = uploaded.json()
        if asset['size'] != path.stat().st_size or asset.get('digest') != 'sha256:'+digest:
            raise RuntimeError('Uploaded size or SHA256 differs: '+path.name)
        print('ASSET_VERIFIED', path.name, asset['size'], flush=True)
    response = session.patch(API+f"/releases/{release['id']}",
        json={'draft': False, 'body': body, 'make_latest': 'false'}, timeout=30)
    response.raise_for_status()
    print('PUBLIC_RELEASE', response.json()['html_url'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--body', required=True, type=Path)
    parser.add_argument('assets', nargs='+', type=Path)
    args = parser.parse_args()
    publish(args.tag, args.commit, args.body, args.assets)
