"""Read-only readiness checks. Never print secrets, URLs or raw exception bodies."""
import argparse
import sys

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.pool import NullPool

from drivegram.config import get_settings
from drivegram.models import Control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-check', action='store_true', help='Verify bot identity via the official cloud API')
    args = parser.parse_args()
    settings = get_settings()
    required = {
        'GOOGLE_CLIENT_ID': settings.google_client_id,
        'GOOGLE_CLIENT_SECRET': settings.google_client_secret.get_secret_value(),
        'GOOGLE_DRIVE_FOLDER_ID': settings.google_drive_folder_id,
        'TELEGRAM_BOT_TOKEN': settings.telegram_bot_token.get_secret_value(),
        'TOKEN_ENCRYPTION_KEY': settings.token_encryption_key.get_secret_value(),
        'SESSION_SECRET': settings.session_secret.get_secret_value(),
    }
    if settings.telegram_api_mode == 'local':
        required.update({'TELEGRAM_API_ID': settings.telegram_api_id,
                         'TELEGRAM_API_HASH': settings.telegram_api_hash.get_secret_value()})
    missing = [name for name, value in required.items() if not value]
    database_ok = False
    cloud_ok = not args.cloud_check
    paired = False
    engine = None
    try:
        url = settings.database_url.get_secret_value()
        options = {'connect_timeout': 5} if url.startswith('postgresql') else {}
        engine = create_engine(url, hide_parameters=True, poolclass=NullPool, connect_args=options)
        with engine.connect() as connection:
            database_ok = connection.execute(select(Control.id).where(Control.id == 1)).scalar() == 1
            paired = bool(connection.execute(select(Control.private_chat_id).where(Control.id == 1)).scalar())
        print('Database/schema:', 'ready' if database_ok else 'migration_required')
    except Exception:
        print('Database/schema: unavailable (check host, service and migrations)')
    finally:
        if engine is not None:
            engine.dispose()
    if not settings.telegram_target_id and not paired:
        missing.append('PRIVATE_CHAT_PAIRING')
    print('Missing settings:', ', '.join(missing) if missing else 'none')
    if args.cloud_check:
        try:
            token = settings.telegram_bot_token.get_secret_value()
            if not token:
                raise ValueError()
            with httpx.Client(timeout=20, proxy=settings.telegram_http_proxy.get_secret_value() or None) as client:
                response = client.post('https://api.telegram.org/bot' + token + '/getMe')
                result = response.json()
            matched = result.get('ok') and result.get('result', {}).get('username', '').lower() == 'drivegramotiner_bot'
            cloud_ok = bool(matched)
            print('Cloud bot identity:', 'verified' if matched else 'not_verified')
        except Exception:
            print('Cloud bot identity: request_failed (network or token; details suppressed)')
    return 1 if missing or not database_ok or not cloud_ok else 0


if __name__ == '__main__':
    sys.exit(main())
