#!/bin/sh
set -e

# Подставляет имена журналов в шаблон и крутит logrotate по расписанию.
#
# Имена берутся из тех же трёх переменных, по которым их выбирает
# приложение. Без этого шага конфиг называл файлы буквально, и
# развёртывание, поставившее своё LOG_FILENAME, оставалось без ротации
# молча: missingok глушит отсутствие файла, ротатор возвращает ноль, а
# журнал растёт до конца диска.
#
# Умолчания те же, что у BaseConfig. Второй раз записанные — да, но
# альтернатива хуже: без них незаданная переменная превращает путь в
# `/logs/.log`, и ротация снова молча ничего не делает.
export LOG_FILENAME="${LOG_FILENAME:-application}"
export ERROR_LOG_FILENAME="${ERROR_LOG_FILENAME:-error}"
export AUDIT_LOG_FILENAME="${AUDIT_LOG_FILENAME:-audit}"

# Имя журнала — имя, а не путь. Приложение проверяет эти три настройки при
# старте и отказывается подниматься с плохим именем, но ротатор — отдельный
# контейнер: он поднимется и станет ротировать `/logs/../что-нибудь`, пока
# оператор разбирается, почему не встало приложение. Проверка та же по
# смыслу, что `JOURNAL_NAME` в configs/app/base.py.
for name in "${LOG_FILENAME}" "${ERROR_LOG_FILENAME}" "${AUDIT_LOG_FILENAME}"; do
    case "${name}" in
        *[!A-Za-z0-9._-]* | .* | "")
            echo "refusing to rotate: '${name}' is not a journal name" >&2
            exit 1
            ;;
    esac
done

# Именно эти три и никакие другие: envsubst без списка подставит всякую
# `${...}`, какая попадётся, а в конфиге logrotate таких конструкций быть
# не должно вовсе — если появится, пусть останется как написана.
envsubst '${LOG_FILENAME} ${ERROR_LOG_FILENAME} ${AUDIT_LOG_FILENAME}' \
    < /etc/logrotate.d/link_shortener.template \
    > /etc/logrotate.d/link_shortener

echo "logrotate will follow: ${LOG_FILENAME}.log, ${ERROR_LOG_FILENAME}.log, ${AUDIT_LOG_FILENAME}.log"

# `render` — подставить и выйти, без цикла. Существует ради теста, который
# спрашивает у настоящего logrotate, принимает ли он то, что мы отгружаем:
# спрашивать надо о готовом конфиге, а готовит его этот скрипт. Тест,
# повторяющий подстановку своими силами, проверял бы свою копию.
if [ "$1" = "render" ]; then
    exit 0
fi

# Интервал — целое число секунд, и проверяется по той же причине, что
# имена: `sleep abc` возвращает ошибку и возвращается сразу, так что цикл
# перестаёт быть расписанием и становится busy-loop — logrotate зовётся без
# передышки, а `docker logs` наполняется отказами со скоростью диска.
# Опечатка в переменной, ничего больше.
case "${LOG_ROTATE_INTERVAL}" in
    "" | *[!0-9]* | 0)
        echo "refusing to run: LOG_ROTATE_INTERVAL='${LOG_ROTATE_INTERVAL}'" \
             "is not a positive whole number of seconds" >&2
        exit 1
        ;;
esac

# Расписание циклом, а не cron: см. Dockerfile.logrotate.
#
# Отказ не гасится: logrotate возвращает ненулевой код, когда не смог
# подменить файл — чаще всего из-за прав на каталог, — и об этом надо
# узнать из `docker logs`, а не по молчанию.
while true; do
    logrotate --state /logs/.logrotate.state /etc/logrotate.d/link_shortener \
        || echo 'logrotate failed, see the message above' >&2
    sleep "${LOG_ROTATE_INTERVAL}"
done
