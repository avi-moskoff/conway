#!/bin/sh

if [ -r /etc/conway.env ]; then
    set -a
    . /etc/conway.env
    set +a
fi

exec /usr/bin/chrt -f 90 /usr/bin/taskset -c 3 /home/avi/conway/.venv/bin/python /home/avi/conway/main.py
