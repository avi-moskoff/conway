#!/bin/sh

if [ -r /etc/conway.env ]; then
    set -a
    . /etc/conway.env
    set +a
fi

# Cores 2 and 3 are isolated (isolcpus in cmdline.txt) for the LED driver's
# refresh thread. Keep everything else - game logic, numpy, the pollers, and
# the decode subprocess (which inherits this mask) - on the housekeeping
# cores 0,1 so nothing competes with the refresh thread.
exec /usr/bin/taskset -c 0,1 /home/avi/conway/.venv/bin/python /home/avi/conway/main.py
