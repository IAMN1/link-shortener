from flask import current_app
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import OperationalError, SQLAlchemyError, IntegrityError

from link_shortener.core.exceptions import DatabaseConnectionError, DatabaseError, DatabaseIntegrityError
from link_shortener.core.logging_config import get_logger
from .base import Base

engine = None
db_session = None

logger = get_logger(__name__)

def init_db():
    """Инициализация подключения к БД с конфигом из Flask app"""
    global engine, db_session

    database_url = current_app.config['DATABASE_URL']
    echo = current_app.config['DEBUG']

    logger.info(
        'Инициализация Базы Данных', 
        database_url=database_url[:50] if database_url > 50 else database_url,
        echo_mode=echo
    )

    try:

        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            echo=echo
        )
        
        db_session = scoped_session(
            sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=engine
            )
        )

        Base.query = db_session.query_property()

        # для создания таблиц в бд
        from . import models  # noqa: F401
        Base.metadata.create_all(bind=engine)

        logger.info('База данных успешно инициализирована')
        logger.debug(
            'Созданы таблицы',
            database_created_tables=list(Base.metadata.tables.keys())
        )

        return db_session
    
    except OperationalError as e:
        logger.critical(
            'Не удалось подключиться к базе данных',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )
        raise DatabaseConnectionError(
            'Не удалось подключиться к базе данных',
            'DB_CONNECTION_ERROR'
        ) from e
    except SQLAlchemyError as e:

        logger.critical(
            'Ошибка SQLAlchemy при инициализации',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )
        raise DatabaseError(
            'Ошибка инициализации базы данных',
            'DB_INIT_ERROR'
        ) from e

def get_session():
    """Получение сесси для использования в обрботчиках"""
    if db_session is None:
        logger.critical('Попытка получить сессию до инициализации Базы данных!')
        raise RuntimeError("База данных не инициализирована. сначала вызовите init_db()")
    return db_session()


def transaction():
    """
    Контекстный менеджер для транзакций
    """
    session = get_session()

    logger.debug('Начало транзакции')

    try:
        
        yield session
        session.commit()

        logger.debug('Транзакция успешно завершена')

    except IntegrityError as e:
        logger.error(
            'Ошибка целостности данных в транзакции',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )
        
        session.rollback()
        
        logger.debug('Откат транзакции из-за IntegrityError')
        
        raise DatabaseIntegrityError(
            "Нарушение целостности данных",
            "DB_INTEGRITY_ERROR"
        ) from e
    except OperationalError as e:
        logger.critical(
            'Ошибка подключения к БД в транзакции',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )
        
        session.rollback()
        
        logger.debug('Откат транзакции из-за OperationalError')
        
        raise DatabaseConnectionError(
            "Ошибка подключения к базе данных",
            "DB_CONNECTION_ERROR"
        ) from e
        
    except SQLAlchemyError as e:
        logger.error(
            'Ошибка SQLAlchemy в транзакции',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )

        session.rollback()
        
        logger.debug('Откат транзакции из-за SQLAlchemyError')
        
        raise DatabaseError(
            "Ошибка базы данных",
            "DB_ERROR"
        ) from e

    except Exception as e:
        logger.critical(
            'Непредвиденная ошибка в транзакции',
            error=str(e),
            error_type=type(e).__name__, 
            exc_info=True
        )
        
        session.rollback()
        
        logger.debug('Откат транзакции из-за непредвиденной ошибки')
        raise
    finally:
        pass
