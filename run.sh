#!/bin/sh
exec /usr/bin/chrt -f 90 /usr/bin/taskset -c 3 /home/avi/conway/.venv/bin/python /home/avi/conway/main.py
