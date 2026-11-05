"""External event timestamps; the agent receives no messages from this logger."""
import datetime as dt
import json
import time


def capture_stream(stream, raw_path, events_path):
    with raw_path.open('wb') as raw, events_path.open('wb') as annotated:
        for line in iter(stream.readline,b''):
            raw.write(line);raw.flush()
            try:
                event=json.loads(line)
                if not isinstance(event,dict):raise ValueError('non-object event')
                event['_harness_received']={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                                            'monotonic_ns':time.monotonic_ns()}
                annotated.write((json.dumps(event,ensure_ascii=False)+'\n').encode())
            except (ValueError,UnicodeError):
                annotated.write(line)
            annotated.flush()
