import threading

# Serializes access to Pillow's C extension across threads. Under this
# project's real-time/single-core scheduling (run.sh: chrt -f 90 taskset -c
# 3 - deliberate, per the LED matrix library's own guidance for smooth PWM
# refresh, not incidental), concurrent PIL calls from different threads were
# observed producing consistently corrupted decode results even though the
# input bytes were confirmed correct and complete (same byte count on
# repeated independent fetches of the same source). The same scheduling
# setup with no other threads competing did not reproduce the corruption -
# only the real multi-threaded app does - so every thread that calls into
# PIL takes this lock: the main render loop's per-frame Image.fromarray()
# in display.py, and games/weather_radar.py's ticker drawing and dust JPEG
# decoding.
pil_lock = threading.Lock()
