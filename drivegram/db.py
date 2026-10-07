from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from drivegram.config import get_settings


def make_database(url):
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def database():
    return _database()


@lru_cache
def _database():
    return make_database(get_settings().database_url.get_secret_value())
