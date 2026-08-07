#!/bin/bash
set -e

# Создаём каталог для логов (если его нет) и меняем владельца на appuser
mkdir -p /app/logs
chown appuser:appuser /app/logs

# Переключаемся на appuser и выполняем переданную команду
exec gosu appuser "$@"