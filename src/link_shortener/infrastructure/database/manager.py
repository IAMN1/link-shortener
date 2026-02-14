from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from link_shortener.infrastructure.database.base import Base


class DatabaseManager:
    """Класс для управления подключением к Базе Данных"""

    def __init__(self, database_url: str, echo: bool = False):

        self.database_url = database_url
        self.echo = echo
        self.engine = None
        self._session_factory = None

    def connect(self) -> "DatabaseManager":
        """Подключение к базе данных"""
        self.engine = create_engine(
            self.database_url, pool_pre_ping=True, echo=self.echo
        )

        self._session_factory = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        return self

    def close(self):
        """Закрытие соединения"""
        if self.engine:
            self.engine.dispose()

    def create_tables(self):
        """Создание таблиц (для разработки/тестов)"""
        if not self.engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        Base.metadata.create_all(bind=self.engine)

    # ========== Варианты обращения к Базе Данных ==========

    ## Вариант 1 - через контекстный менеджер
    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """
        Контекстный менеджер для сессии
        Автоматически закрывает сессию и откатывавет в случае возникновения ошибки
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    ## Вариант 2 - через метод получения сесии
    def get_session(self) -> Session:
        """
        Получение сессии без контекстного менеджера
        ВНИМАНИЕ: Вызывающий код должен сам закрывать сесиию!
        """

        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call connect() first.")

        return self._session_factory()
