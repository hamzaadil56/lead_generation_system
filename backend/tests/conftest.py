import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base

TEST_URL = "postgresql+psycopg://postgres:dev@localhost:5432/leadgen_test"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    conn = engine.connect()
    txn = conn.begin()
    s = sessionmaker(bind=conn)()
    yield s
    s.close()
    txn.rollback()      # every test rolls back; no cross-test leakage
    conn.close()
