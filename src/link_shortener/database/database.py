from flask import current_app
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from .base import Base

engine = None
db_session = None

def init_db():
    """Инициализация подключения к БД с конфигом из Flask app"""
    global engine, db_session

    database_url = current_app.config['DATABASE_URL']

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        echo=current_app.config.get('DEBUG', False)
    )
    
    db_session = scoped_session(sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    ))

    Base.query = db_session.query_property()

    # для создания таблиц в бд
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    return db_session

def get_session():
    """Получение сесси для использования в обрботчиках"""
    if db_session is None:
        raise RuntimeError("База данных не инициализирована. сначала вызовите init_db()")
    return db_session()