import os
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from drivegram.config import Settings
from drivegram.models import Base, Control, Job


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url="sqlite://", temp_dir=tmp_path / "transfers",
                    telegram_bot_token="123456:dummy", telegram_api_id="123", telegram_api_hash="dummy",
                    telegram_channel_id="-10012345", google_client_id="test", google_client_secret="test",
                    google_drive_folder_id="folder123", token_encryption_key=Fernet.generate_key().decode(),
                    session_secret="test-session-secret-with-at-least-32-characters", admin_password="test-password-long-enough",
                    cookie_secure=False, disk_reserve_mb=0, retry_base_seconds=1)


@pytest.fixture
def sessions(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        # Do NOT drop objects from an existing database. All tests get a unique schema.
        schema = "test_" + uuid.uuid4().hex
        engine = create_engine(url, hide_parameters=True)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine.dispose()
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True)
    else:
        schema = None
        engine = create_engine(f"sqlite:///{Path(tmp_path) / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Control(id=1))
    yield factory
    engine.dispose()
    if schema:
        engine = create_engine(url, hide_parameters=True)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.fixture
def queued(sessions, settings):
    from drivegram.queue import current_scope
    with sessions.begin() as session:
        job = Job(id=str(uuid.uuid4()), drive_file_id="file123", version_key="v:1",
                  source_scope=current_scope(session, settings), original_name="ویدیو.mp4",
                  mime_type="video/mp4", size_bytes=4, status="queued")
        session.add(job)
    return job.id
