from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from drivegram.config import get_settings


def make_database(url, no_pool=False):
    options = {"poolclass": NullPool} if no_pool else {}
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True, **options)
    return engine, sessionmaker(engine, expire_on_commit=False)


def database():
    return _database()


@lru_cache
def _database():
    settings = get_settings()
    return make_database(settings.database_url.get_secret_value(), settings.database_no_pool)
