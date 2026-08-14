"""
Нагрузочный профиль сокращателя.

Запуск (стек должен быть поднят, см. docs/DEVELOPER_GUIDE.md):

    uv sync --group load
    uv run locust -f tests/load/locustfile.py --headless \
        -u 60 -r 20 -t 60s -H http://localhost:5000

Три сценария, каждый со своим классом; выбор — флагом `--class-picker`
или `RedirectUser`/`CreateUser`/`MixedUser` в конце командной строки.

Профиль называет адрес сам, и свой на каждый запрос. Ограничитель частоты
считает по адресу (редирект — 200 за минуту, создание — 30), поэтому
нагрузка с одного адреса упирается в счётчик на третьем запросе в секунду:
замерялась бы не служба, а он. Замерено: 20 пользователей со своим адресом
у каждого дали 85% ответов 429.

Свой адрес на запрос — это модель «много разных вызывающих», а не обход
проверки: сам ограничитель остаётся в пути и по-прежнему стоит одного
INCR в Redis на каждый запрос. Именно этот случай и надо мерить — от
насыщения одним вызывающим защищает как раз ограничитель, а пулы и
тайм-ауты нужны там, где вызывающих много.

Адрес доезжает заголовком ``X-Forwarded-For``, а развёртывание для замера
объявляет доверенным тот адрес, с которого приходит locust
(``TRUSTED_PROXIES``). Это тот же путь, которым адрес клиента доходит
из-за балансировщика в бою.

Файл pytest не собирает: имя не подходит под ``python_files``.
"""

import itertools
import random

from locust import HttpUser, between, constant, events, task


SEED_LINKS = 200
"""Сколько ссылок создаётся до замера, чтобы редиректу было куда ходить."""

_addresses = itertools.count(1)
"""Счётчик, из которого каждый пользователь берёт свой адрес."""

SHORT_CODES: list[str] = []
"""Коды, созданные на подготовке. Общие для всех пользователей."""


def _next_address() -> str:
    """
    Выдать следующий адрес из блока 10.0.0.0/8.

    Returns:
        Адрес в точечной записи, свой у каждого вызова.
    """
    n = next(_addresses)
    return f"10.{(n >> 16) & 0xFF}.{(n >> 8) & 0xFF}.{n & 0xFF}"


@events.test_start.add_listener
def seed_links(environment, **_kwargs):
    """
    Создать ссылки, по которым будет ходить редирект.

    Без этого шага редирект измерял бы промах: несуществующий код — это
    404 из кэша, а не путь «найти ссылку, посчитать переход, ответить».

    Args:
        environment: Окружение locust; из него берётся базовый адрес.
    """
    import requests

    base = environment.host.rstrip("/")
    SHORT_CODES.clear()
    with requests.Session() as session:
        for i in range(SEED_LINKS):
            response = session.post(
                f"{base}/api/v1/shorten",
                json={"url": f"https://example.com/load-{i}"},
                headers={"X-Forwarded-For": _next_address()},
                timeout=10,
            )
            if response.status_code in (200, 201):
                SHORT_CODES.append(response.json()["short_code"])

    if not SHORT_CODES:
        raise RuntimeError(
            "не создано ни одной ссылки: проверьте TRUSTED_PROXIES и "
            "GUEST_LINK_LIMIT в env-файле замеряемого стека"
        )


class RedirectUser(HttpUser):
    """Только редиректы — самый горячий путь сервиса."""

    wait_time = constant(0)

    @task
    def follow(self) -> None:
        """Перейти по случайному короткому коду."""
        code = random.choice(SHORT_CODES)
        self.client.get(
            f"/{code}",
            name="GET /<code>",
            headers={"X-Forwarded-For": _next_address()},
            allow_redirects=False,
        )


class CreateUser(HttpUser):
    """Только создание ссылок — самый дорогой путь: запись плюс инвалидация."""

    wait_time = constant(0)

    def on_start(self) -> None:
        """Завести счётчик, из которого берутся неповторяющиеся адреса."""
        self.counter = 0

    @task
    def shorten(self) -> None:
        """Сократить адрес, которого ещё не было."""
        self.counter += 1
        self.client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/{self.counter}-{id(self)}"},
            headers={"X-Forwarded-For": _next_address()},
            name="POST /api/v1/shorten",
        )


class HealthUser(HttpUser):
    """Только /health — путь, который опрашивает healthcheck контейнера."""

    wait_time = constant(0)

    @task
    def health(self) -> None:
        """Спросить состояние зависимостей."""
        self.client.get("/health", name="GET /health")


class MixedUser(HttpUser):
    """
    Смесь в пропорции, в которой сокращатель и работает.

    Девять переходов на одно создание и один опрос состояния на сотню
    запросов: ссылку создают однажды, а открывают многократно.
    """

    wait_time = between(0, 0.05)

    def on_start(self) -> None:
        """Завести счётчик, из которого берутся неповторяющиеся адреса."""
        self.counter = 0

    @task(90)
    def follow(self) -> None:
        """Перейти по случайному короткому коду."""
        code = random.choice(SHORT_CODES)
        self.client.get(
            f"/{code}",
            name="GET /<code>",
            headers={"X-Forwarded-For": _next_address()},
            allow_redirects=False,
        )

    @task(9)
    def shorten(self) -> None:
        """Сократить адрес, которого ещё не было."""
        self.counter += 1
        self.client.post(
            "/api/v1/shorten",
            json={"url": f"https://example.com/{self.counter}-{id(self)}"},
            headers={"X-Forwarded-For": _next_address()},
            name="POST /api/v1/shorten",
        )

    @task(1)
    def health(self) -> None:
        """Спросить состояние зависимостей."""
        self.client.get("/health", name="GET /health")
