"""Pair a private chat through Windows' existing network, without a network bridge.

Start pairing in the panel first and press Start in the linked bot conversation.
This helper only reads Telegram updates and passes them to the existing nonce validator.
It never sends a message, changes a webhook or logs bot credentials or message contents.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

from drivegram.config import get_settings
from drivegram.db import database
from drivegram.models import utcnow
from drivegram.pairing import accept_pairing
from drivegram.queue import control_lock
from drivegram.telegram import EXPECTED_BOT


def db_action(action):
    _, sessions = database()
    with sessions.begin() as session:
        control = control_lock(session)
        pending = bool(control.pair_hash and control.pair_expires_at and control.pair_expires_at > utcnow())
        if action == 'state':
            return {'pending': pending, 'offset': control.telegram_update_offset}
        updates = json.loads(sys.stdin.read(2 * 1024 * 1024))
        if not pending or not isinstance(updates, list) or len(updates) > 100:
            return {'paired': False}
        paired = False
        for update in updates:
            if not isinstance(update, dict):
                continue
            if isinstance(update.get('update_id'), int):
                control.telegram_update_offset = max(control.telegram_update_offset, update['update_id'] + 1)
            paired = accept_pairing(session, update) or paired
        return {'paired': paired}


def from_windows(distribution):
    root = Path(__file__).resolve().parent.parent
    resolved = subprocess.run(['wsl.exe', '-d', distribution, '-u', 'root', '--', 'wslpath', '-a', root.as_posix()],
                              check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    command = ['wsl.exe', '-d', distribution, '-u', 'root', '--cd', resolved, '--', 'docker', 'compose',
               'exec', '-T', 'worker', 'python', '-m', 'scripts.pair_private']

    def invoke(action, data=None):
        result = subprocess.run(command + [action], input=json.dumps(data) if data is not None else None,
                                check=True, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)

    state = invoke('state')
    if not state['pending']:
        return 'Start a new private-chat pairing in the panel first.'
    settings = get_settings()
    if settings.telegram_api_id and settings.telegram_api_hash.get_secret_value():
        return 'Local API credentials are configured; use the normal panel pairing instead of the cloud helper.'
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        return 'Bot token is missing.'
    with httpx.Client(timeout=15) as client:
        base = 'https://api.telegram.org/bot' + token
        identity = client.post(base + '/getMe').json()
        if not identity.get('ok') or identity.get('result', {}).get('username', '').lower() != EXPECTED_BOT.lower():
            return 'Expected bot identity could not be verified.'
        result = client.post(base + '/getUpdates', json={'offset': state['offset'], 'timeout': 0,
                                                        'allowed_updates': ['message']}).json()
    if not result.get('ok') or not isinstance(result.get('result'), list):
        return 'Could not read pairing updates; check network, cloud migration and webhook configuration.'
    accepted = invoke('accept', result['result'])
    return 'Private destination registered.' if accepted['paired'] else 'No matching Start received yet; press Start and retry.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['from-windows', 'state', 'accept'])
    parser.add_argument('--distribution', default='Ubuntu-22.04')
    args = parser.parse_args()
    try:
        if args.action == 'from-windows':
            print(from_windows(args.distribution))
        else:
            print(json.dumps(db_action(args.action)))
    except Exception:
        raise SystemExit('Pairing helper failed; check local services and network. Private details were not logged.') from None


if __name__ == '__main__':
    main()
