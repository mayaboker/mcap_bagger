from pathlib import Path
import json
import time

from mcap.reader import make_reader
import pytest
import zmq

from mcap_bagger.recorder import Recorder
from mcap_bagger.recording_control import RecordingController


@pytest.fixture
def controller(config_files):
    recorder = Recorder()
    recorder.init(config_files[0])
    context = zmq.Context()
    publisher = context.socket(zmq.XPUB)
    port = publisher.bind_to_random_port('tcp://127.0.0.1')
    with context.socket(zmq.PUB) as probe:
        status_port = probe.bind_to_random_port('tcp://127.0.0.1')
    clock = [100.]
    control = RecordingController(recorder, f'tcp://127.0.0.1:{port}',
        f'tcp://127.0.0.1:{status_port}', clock=lambda:clock[0])
    assert publisher.poll(2000)
    publisher.recv()
    try:yield control, clock, publisher
    finally:
        try:control.close()
        except RuntimeError:pass
        publisher.close(0);context.term()


def packet(clock, sequence, state='running', session='session', controller='app', request='request'):
    return dict(schema_version=1,controller_id=controller,session_id=session,request_id=request,
        sequence=sequence,issued_ms=int(clock[0]*1000),state=state)


def test_idempotency_and_confirmation_after_finalization(controller):
    control, clock, _ = controller
    control._apply(packet(clock,1),clock[0]);first=control.recorder.recording
    partial = first.path
    assert control.state == 'recording' and partial.exists()
    control._apply(packet(clock,2),clock[0]);assert control.recorder.recording is first
    control._apply(packet(clock,3,'stopped'),clock[0])
    assert control.state == 'idle' and first.final_path.exists() and not partial.exists()
    with first.final_path.open('rb') as stream:assert make_reader(stream,validate_crcs=True).get_summary()
    control._apply(packet(clock,2),clock[0]);assert not control.recorder.active
    control._apply(packet(clock,4,'stopped'),clock[0]);assert control.recorder.recording is first
    control._apply(packet(clock,5,session='next'),clock[0]);assert control.recorder.recording is not first


def test_stale_and_timeout_states_cannot_resurrect_session(controller):
    control, clock, _ = controller
    stale=packet(clock,1);clock[0]+=2
    control._apply(stale,clock[0]);assert not control.recorder.active
    control._apply(packet(clock,2),clock[0]);clock[0]+=3.1;control.poll()
    assert not control.recorder.active and control.state == 'idle'
    control._apply(packet(clock,3),clock[0]);assert control.state == 'error'
    assert not control.recorder.active
    control._apply(packet(clock,4,session='next'),clock[0]);assert control.state == 'recording'


def test_bad_wire_data_and_simulation_topic_do_not_start(controller):
    control, clock, publisher = controller
    publisher.send_multipart([b'simulation/state',json.dumps(packet(clock,1)).encode()])
    publisher.send_multipart([b'recording/state',b'{bad'])
    for _ in range(5):control.poll()
    assert not control.recorder.active


def test_open_failure_reports_error_and_propagates(controller,monkeypatch):
    control,clock,publisher=controller
    def fail():raise OSError('disk unavailable')
    monkeypatch.setattr(control.recorder,'start',fail)
    publisher.send_multipart([b'recording/state',json.dumps(packet(clock,1)).encode()])
    deadline=time.monotonic()+2
    with pytest.raises(OSError,match='disk unavailable'):
        while time.monotonic()<deadline:control.poll()
    assert control.state=='error' and control.error=='disk unavailable'


def test_worker_failure_is_never_acknowledged_as_idle(controller):
    control,clock,_=controller
    control._apply(packet(clock,1),clock[0])
    control.recorder.recording.fail('write failed')
    with pytest.raises(RuntimeError,match='write failed'):control.poll()
    assert control.state=='error'
