"""On activation/login, gracefully retire an idle pre-Brick app instance."""
import subprocess
import time
import workmode as w

backend = w.Abstand()
try:
    status = backend.call('status')
except w.Error:
    status = None
if status is not None and not status.get('brickControl'):
    if status['sessions']:
        raise w.Error('Finish the active Abstand session, then run workmode setup and log in again')
    # Normal application quit honors Abstand's own quit policy; never force-kill it.
    subprocess.run(['/usr/bin/osascript', '-e',
                    'tell application id "com.buildergroup.abstand" to quit'], check=True, timeout=15)
    for _ in range(20):
        try:
            current = backend.call('status')
            if current.get('brickControl'):
                break
        except w.Error:
            break
        time.sleep(0.5)
    else:
        raise w.Error('Old Abstand is still running; quit it normally when idle')
backend.setup()
