"""State-controlled physical recording; never consumes simulation lifecycle."""
import json
import time
from uuid import uuid4

import zmq
from bullet_msgs import validate_endpoint
from bullet_msgs.recording_control import (STATE_TOPIC, STATUS_TOPIC, STATE_INTERVAL_S,
    STATE_TIMEOUT_S, MAX_BATCH, MAX_ERROR_CHARS, MAX_MESSAGE_BYTES, decode, fresh, validate_state, validate_status)


POLL_INTERVAL_S = .01


class RecordingController:
    def __init__(self, recorder, state_endpoint, status_endpoint, *, clock=time.monotonic, report=print):
        validate_endpoint(state_endpoint)
        validate_endpoint(status_endpoint)
        if state_endpoint == status_endpoint:
            raise ValueError('recording state/status endpoints must differ')
        self.recorder, self.clock, self.report = recorder, clock, report
        self.recorder_id = uuid4().hex
        self.controller_id = self.session_id = self.request_id = None
        self.sequence = self.last_sequence = 0
        self.last_seen = None
        self.next_status = 0.
        self.state, self.path, self.error = 'idle', None, None
        self.retired = set()
        self.context = zmq.Context()
        self.input = self.context.socket(zmq.SUB)
        self.output = self.context.socket(zmq.PUB)
        try:
            for socket in (self.input, self.output):
                socket.setsockopt(zmq.LINGER, 0)
                socket.setsockopt(zmq.RCVHWM, MAX_BATCH)
                socket.setsockopt(zmq.SNDHWM, MAX_BATCH)
            self.input.setsockopt(zmq.SUBSCRIBE, STATE_TOPIC)
            self.input.setsockopt(zmq.MAXMSGSIZE, MAX_MESSAGE_BYTES)
            self.input.connect(state_endpoint)
            self.output.bind(status_endpoint)
        except BaseException:
            self.input.close(0)
            self.output.close(0)
            self.context.term()
            raise

    def _publish(self):
        self.sequence += 1
        value = dict(schema_version=1, recorder_id=self.recorder_id,
            controller_id=self.controller_id, session_id=self.session_id, request_id=self.request_id,
            sequence=self.sequence, issued_ms=int(self.clock()*1000), state=self.state,
            path=self.path, error=self.error)
        validate_status(value)
        try:
            self.output.send_multipart([STATUS_TOPIC, json.dumps(value).encode()], zmq.NOBLOCK)
        except zmq.Again:
            pass  # Periodic status repairs a dropped transition.
        self.next_status = self.clock() + STATE_INTERVAL_S

    def _stop(self, reason):
        if self.recorder.active:
            self.state = 'finalizing'
            self._publish()
            self.recorder.recording.outcome = reason
            self.report(self.recorder.close())
            if self.recorder.recording.error:
                raise RuntimeError(self.recorder.recording.error)
            self.path = str(self.recorder.recording.final_path)
        if self.recorder.recording is not None and self.recorder.recording.error:
            raise RuntimeError(self.recorder.recording.error)
        self.state = 'idle'

    def _apply(self, value, now):
        if not fresh(value, now) or value['controller_id'] in self.retired:
            return
        if value['controller_id'] != self.controller_id:
            self._stop('controller_changed')
            if self.controller_id is not None:
                self.retired.add(self.controller_id)
            self.controller_id = value['controller_id']
            self.last_sequence = 0
        if value['sequence'] <= self.last_sequence:
            return
        self.last_sequence = value['sequence']
        self.last_seen = now
        self.request_id = value['request_id']
        if value['state'] == 'running':
            if self.recorder.active and self.session_id != value['session_id']:
                self._stop('session_changed')
            if not self.recorder.active:
                # A timed-out/closed session cannot be resurrected by its heartbeats.
                if self.session_id == value['session_id']:
                    self.state, self.error = 'error', 'recording session already closed; send a new Start'
                    self._publish()
                    return
                self.session_id = value['session_id']
                self.report(self.recorder.start())
                self.path = str(self.recorder.recording.final_path)
            self.state = 'recording'
        else:
            self._stop('recording_stop')
        self.error = None
        self._publish()

    def poll(self):
        if self.recorder.recording is not None and self.recorder.recording.error:
            self.error, self.state = self.recorder.recording.error[:MAX_ERROR_CHARS], 'error'
            self._publish()
            raise RuntimeError(self.error)
        for _ in range(MAX_BATCH):
            try:
                parts = self.input.recv_multipart(zmq.NOBLOCK)
            except zmq.Again:
                break
            if len(parts) != 2 or parts[0] != STATE_TOPIC:
                continue
            try:
                value = decode(parts[1], validate_state)
            except (ValueError, TypeError, UnicodeError, RecursionError) as error:
                self.report(f'Rejected recording state: {error}')
                continue
            try:
                self._apply(value, self.clock())
            except Exception as error:
                self.error, self.state = str(error)[:MAX_ERROR_CHARS] or 'recording failed', 'error'
                self._publish()
                raise
        if self.recorder.active and self.recorder.recording.error:
            self.error, self.state = self.recorder.recording.error[:MAX_ERROR_CHARS], 'error'
            self._publish()
            raise RuntimeError(self.error)
        if self.last_seen is not None and self.clock() - self.last_seen >= STATE_TIMEOUT_S and self.recorder.active:
            self._stop('recording_controller_timeout')
            self._publish()
        if self.clock() >= self.next_status:
            self._publish()
        time.sleep(POLL_INTERVAL_S)

    def close(self):
        try:
            self._stop('application_shutdown')
        finally:
            self.input.close(0)
            self.output.close(0)
            self.context.term()
