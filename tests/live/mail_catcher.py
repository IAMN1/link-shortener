"""
Приёмник почты на петле для живых прогонов.

Оба прогона в этом каталоге раньше обходили один и тот же стык. Учётная
запись подтверждалась либо прямым `UPDATE users SET email_verified = 1`,
либо строкой подтверждения, которую прогон сам сочинял и сам же клал в
таблицу. И то и другое проверяет `/api/v1/auth/verify` против токена,
выданного тестом, а не сервисом: если регистрация перестанет выдавать
токен или шаблон письма соберёт ссылку не туда, обе проверки останутся
зелёными. Один такой сценарий уже ломался незамеченным.

Через этот приёмник проходит ровно тот путь, который работает в бою:
регистрация выпускает токен, шаблон собирает ссылку, ``SMTPMailer``
отдаёт письмо по SMTP, — а прогон берёт ссылку из доставленного письма и
идёт по ней. Он же отвечает на вопрос, который прежние обходы не задавали:
уходит ли письмо вообще.

SMTP здесь ровно настолько, насколько его говорит ``smtplib``: приветствие,
EHLO, конверт, DATA, QUIT. Ни TLS, ни аутентификации — их не предлагает и
``mailpit``, на который нацелен профиль development.
"""

import re
import socketserver
import threading
from email import message_from_string
from typing import List, Optional
from urllib.parse import urlsplit


class _Handler(socketserver.StreamRequestHandler):
    """Один сеанс SMTP."""

    def handle(self) -> None:
        """Отговорить один сеанс и сложить доставленное в ящик."""
        self._say("220 catcher ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode("utf-8", "replace").strip()
            head = command.split()[0].upper() if command.split() else ""

            if head in ("EHLO", "HELO"):
                self._say("250 catcher")
            elif head in ("MAIL", "RCPT", "RSET", "NOOP"):
                self._say("250 ok")
            elif head == "DATA":
                self._say("354 end with a lone dot")
                self.server.mailbox.append(self._read_message())
                self._say("250 accepted")
            elif head == "QUIT":
                self._say("221 bye")
                return
            else:
                self._say("502 not implemented")

    def _say(self, text: str) -> None:
        """
        Ответить одной строкой протокола.

        Args:
            text: Строка ответа без завершителя.
        """
        self.wfile.write(text.encode("ascii") + b"\r\n")
        self.wfile.flush()

    def _read_message(self) -> str:
        """
        Прочитать тело письма до одинокой точки.

        Returns:
            Письмо целиком, с заголовками, точки в начале строк
            восстановлены.
        """
        lines: List[str] = []
        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == ".":
                break
            lines.append(line[1:] if line.startswith("..") else line)
        return "\n".join(lines)


class _Server(socketserver.ThreadingTCPServer):
    """TCP-сервер с ящиком, общим для всех сеансов."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address):
        """
        Args:
            address: Пара (хост, порт); порт 0 означает «любой свободный».
        """
        super().__init__(address, _Handler)
        self.mailbox: List[str] = []


class MailCatcher:
    """
    Почтовый сервер, который ничего никуда не отправляет.

    Поднимается на петле, на порту, который выбирает ядро, и живёт в
    отдельном потоке, пока прогон не остановит его.

    Attributes:
        port: Порт, на котором приёмник слушает.
    """

    def __init__(self) -> None:
        """Поднять приёмник и начать принимать сеансы."""
        self._server = _Server(("127.0.0.1", 0))
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Остановить приёмник и освободить порт."""
        self._server.shutdown()
        self._server.server_close()

    def clear(self) -> None:
        """Выбросить всё принятое, чтобы следующая проверка искала своё."""
        self._server.mailbox.clear()

    def messages_to(self, address: str) -> List[str]:
        """
        Выбрать письма, адресованные одному получателю.

        Args:
            address: Адрес в поле ``To``.

        Returns:
            Тела писем в порядке доставки, уже раскодированные.

            Раскодировать обязательно: ``EmailMessage.set_content``
            выбирает quoted-printable, и ссылка подтверждения приезжает в
            нём и разорванной мягким переносом --
            ``token=3DAAAA...AAAA=\\nAAAA``. Почтовый клиент это соберёт
            обратно, а прогон, читающий сырое тело, взял бы обрубок и
            получил бы «This confirmation link is not valid».
        """
        found = []
        for raw in self._server.mailbox:
            message = message_from_string(raw)
            if message.get("To", "") == address:
                payload = message.get_payload(decode=True)
                charset = message.get_content_charset() or "utf-8"
                found.append(payload.decode(charset))
        return found

    def confirmation_link(self, address: str) -> Optional[str]:
        """
        Достать ссылку подтверждения из последнего письма адресату.

        Путь в образце не назван намеренно: ищется любой адрес с
        параметром ``token``. Иначе образец повторял бы то, что и должен
        проверять, и подтверждал бы ссылку, собранную не туда, — ровно
        так первая версия этой правки и прошла подменённый ``VERIFY_PATH``.

        Args:
            address: Адрес, на который слали подтверждение.

        Returns:
            Ссылка целиком, либо ``None``, если письма нет или ссылки в
            нём не нашлось.
        """
        for body in reversed(self.messages_to(address)):
            match = re.search(r"https?://\S*\?\S*token=\S+", body)
            if match:
                return match.group(0).rstrip(".,)")
        return None

    def confirmation_target(self, address: str) -> Optional[str]:
        """
        Та же ссылка, но одним путём с запросом — как её берёт тест-клиент.

        Args:
            address: Адрес, на который слали подтверждение.

        Returns:
            Путь с query-строкой, либо ``None``.
        """
        link = self.confirmation_link(address)
        if link is None:
            return None
        parts = urlsplit(link)
        return parts.path + (f"?{parts.query}" if parts.query else "")
