import io
import struct
import threading
import time

import pytest
import zmq
from PIL import Image
from mcap.reader import make_reader

from mcap_bagger.pipeline import Pipeline
from mcap_bagger.registration import Channel, RegistrationConfig
from mcap_bagger.shm import validate_descriptor


@pytest.mark.parametrize('change', [
    {'version': 1},
    {'header': {'fid': True, 'time_stamp': {'sec': 0, 'nanosec': 1}}},
    {'header': {'fid': 1, 'time_stamp': {'sec': 0, 'nanosec': 1_000_000_000}}},
    {'drone_id': ''},
    {'host_capture_ns': 0},
])
def test_invalid_version_three_descriptor_is_rejected(change):
    metadata = dict(version=3, session='a' * 32, slot=0,
                    shm_name='/bullet_msgs_' + 'a' * 32 + '_s0', width=2,
                    height=2, encoding='rgb8', step=6, bytes=12,
                    sequence=1, capture_ns=1,
                    header={'fid': 1, 'time_stamp': {'sec': 0, 'nanosec': 1}},
                    drone_id='drone_1', host_capture_ns=123456)
    metadata.update(change)
    with pytest.raises(ValueError):
        validate_descriptor(metadata)


@pytest.mark.parametrize('compress', ['raw', 'jpeg'])
def test_both_queues_are_written(tmp_path, compress):
    config = RegistrationConfig('test', tmp_path, (
        Channel('imu', 'tcp://127.0.0.1:5555', False),
        Channel('image', 'tcp://127.0.0.1:5556', True, compress)))
    pipeline = Pipeline(config)
    pipeline.enqueue(0, ('imu', 123, b'\x00binary'))
    pipeline.enqueue(0, ('imu', 124, b''))
    payload = bytes([255, 0, 0]) * 4
    if compress == 'jpeg':
        buffer = io.BytesIO()
        Image.frombytes('RGB', (2, 2), payload).save(buffer, 'JPEG', quality=90)
        payload = buffer.getvalue()
    pipeline.enqueue(1, ('image', 125, payload))
    pipeline.stop.set()
    pipeline.write()
    assert pipeline.error is None
    with next(tmp_path.glob('*.mcap')).open('rb') as stream:
        reader = make_reader(stream)
        messages = list(reader.iter_messages())
        assert len(messages) == 3
        assert [m.data for _, c, m in messages if c.topic == 'imu'] == [b'\x00binary', b'']
        assert next(m.data for _, c, m in messages if c.topic == 'image') == payload
        assert len(reader.get_summary().channels) == 2


def test_tcp_message_receiver(tmp_path):
    with zmq.Context() as context, context.socket(zmq.XPUB) as publisher:
        port = publisher.bind_to_random_port('tcp://127.0.0.1')
        pipeline = Pipeline(RegistrationConfig('test', tmp_path, (
            Channel('imu', f'tcp://127.0.0.1:{port}', False),)))
        thread = threading.Thread(target=pipeline.receive, args=(0,))
        thread.start()
        try:
            assert publisher.poll(3000)
            publisher.recv()
            publisher.send_multipart([b'imu', b'opaque'])
            with pipeline.condition:
                assert pipeline.condition.wait_for(lambda: pipeline.queues[0], timeout=3)
                assert pipeline.queues[0][0][2] == b'opaque'
        finally:
            pipeline.stop.set()
            thread.join(3)
        assert not thread.is_alive()
        assert pipeline.error is None


@pytest.mark.parametrize('topic', ('telemetry/attitude', 'control/msp_rc'))
def test_three_frame_publisher_timestamp_round_trip(tmp_path, topic):
    payload = b'\x81\xa5value\xc4\x02\x00\xff'
    published = 1_793_000_000_123_456_789
    with zmq.Context() as context, context.socket(zmq.XPUB) as publisher:
        port = publisher.bind_to_random_port('tcp://127.0.0.1')
        pipeline = Pipeline(RegistrationConfig('test', tmp_path, (
            Channel(topic, f'tcp://127.0.0.1:{port}', False),)))
        accepted = []
        received = threading.Event()
        original_enqueue = pipeline.enqueue

        def capture(index, message):
            accepted.append(message)
            original_enqueue(index, message)
            received.set()

        pipeline.enqueue = capture
        pipeline.start()
        try:
            assert publisher.poll(3000)
            assert publisher.recv() == b'\x01' + topic.encode()
            publisher.send_multipart([topic.encode(), struct.pack('<Q', published), payload])
            assert received.wait(3)
            assert accepted[0][2:] == (payload, published)
        finally:
            pipeline.stop.set()
            pipeline.thread.join(5)
    assert pipeline.error is None
    with pipeline.writer.path.open('rb') as stream:
        records = list(make_reader(stream).iter_messages())
    assert len(records) == 1
    _, channel, message = records[0]
    assert channel.topic == topic and message.data == payload
    assert message.publish_time == published
    assert message.log_time != published


@pytest.mark.parametrize('frames', (
    [b'imu'], [b'imu', b'bad', b'data'], [b'imu', b'data', b'extra', b'frame'],
))
def test_invalid_ordinary_framing_fails_recording(tmp_path, frames):
    with zmq.Context() as context, context.socket(zmq.XPUB) as publisher:
        port = publisher.bind_to_random_port('tcp://127.0.0.1')
        pipeline = Pipeline(RegistrationConfig('test', tmp_path, (
            Channel('imu', f'tcp://127.0.0.1:{port}', False),)))
        thread = threading.Thread(target=pipeline.receive, args=(0,))
        thread.start()
        try:
            assert publisher.poll(3000)
            publisher.recv()
            publisher.send_multipart(frames)
            with pipeline.condition:
                assert pipeline.condition.wait_for(lambda: pipeline.error is not None, timeout=3)
            assert isinstance(pipeline.error, ValueError)
        finally:
            pipeline.stop.set()
            thread.join(3)


def test_telemetry_topics_share_endpoint_and_preserve_msgpack(tmp_path):
    topics = ('telemetry/attitude', 'telemetry/vfr_hud', 'telemetry/gps', 'control/msp_rc')
    payloads = {topic: b'\x81\xa5value' + bytes([index])
                for index, topic in enumerate(topics, start=1)}
    with zmq.Context() as context, context.socket(zmq.XPUB) as publisher:
        publisher.setsockopt(zmq.XPUB_VERBOSE, 1)
        port = publisher.bind_to_random_port('tcp://127.0.0.1')
        endpoint = f'tcp://127.0.0.1:{port}'
        config = RegistrationConfig('telemetry', tmp_path,
                                    tuple(Channel(topic, endpoint, False) for topic in topics))
        pipeline = Pipeline(config)
        received = threading.Event()
        original_enqueue = pipeline.enqueue
        accepted = []

        def capture(index, message):
            original_enqueue(index, message)
            accepted.append(message[0])
            if len(accepted) == len(topics):
                received.set()

        pipeline.enqueue = capture
        pipeline.start()
        try:
            assert pipeline.ready.wait(3)
            pending = {topic.encode() for topic in topics}
            while pending:
                assert publisher.poll(3000)
                event = publisher.recv()
                if event[:1] == b'\x01':
                    pending.discard(event[1:])
            for topic, payload in payloads.items():
                publisher.send_multipart([topic.encode(), payload])
            assert received.wait(3)
        finally:
            pipeline.stop.set()
            pipeline.thread.join(5)
        assert not pipeline.thread.is_alive()
        assert pipeline.error is None
    with pipeline.writer.path.open('rb') as stream:
        recorded = {channel.topic: message.data
                    for _, channel, message in make_reader(stream).iter_messages()}
    assert recorded == payloads


def test_queue_overflow(tmp_path, monkeypatch):
    monkeypatch.setattr('mcap_bagger.pipeline.QUEUE_BYTES', 2)
    pipeline = Pipeline(RegistrationConfig('test', tmp_path, ()))
    with pytest.raises(ValueError, match='overflow'):
        pipeline.enqueue(0, ('imu', 1, b'123'))


@pytest.mark.parametrize('compress', ['raw', 'jpeg'])
@pytest.mark.parametrize('version', [1, 3])
def test_shm_image_handler(tmp_path, compress, version):
    import json
    import os
    import struct
    from pathlib import Path
    from uuid import uuid4
    from mcap_bagger.shm import HEADER, MAGIC

    session = uuid4().hex
    name = f'/bullet_msgs_{session}_s0'
    path = Path('/dev/shm' + name)
    pixels = bytes([255, 0, 0]) * 4
    metadata = dict(version=version, session=session, slot=0, shm_name=name,
                    width=2, height=2, encoding='rgb8', step=6, bytes=12,
                    sequence=1, capture_ns=1)
    if version == 3:
        metadata.update(header={'fid': 7, 'time_stamp': {'sec': 0, 'nanosec': 1}},
                        drone_id='drone_1', host_capture_ns=123456)
    descriptor = json.dumps(metadata).encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, HEADER.pack(MAGIC, 1, 0, 2, 2, 1, 6, 12, 1, 1, 1,
                                session.encode().ljust(64, b'\0')) + pixels)
        os.close(fd)
        with zmq.Context() as context, context.socket(zmq.XPUB) as publisher:
            port = publisher.bind_to_random_port('tcp://127.0.0.1')
            pipeline = Pipeline(RegistrationConfig('test', tmp_path, (
                Channel('image', f'tcp://127.0.0.1:{port}', True, compress),)))
            thread = threading.Thread(target=pipeline.receive, args=(1,))
            thread.start()
            try:
                assert publisher.poll(3000)
                publisher.recv()
                publisher.send(b'image\0' + struct.pack('<I', len(descriptor)) + descriptor)
                with pipeline.condition:
                    assert pipeline.condition.wait_for(lambda: pipeline.queues[1] or pipeline.error, timeout=3)
                    assert pipeline.error is None
                    payload = pipeline.queues[1][0][2]
                if compress == 'raw':
                    assert payload == pixels
                else:
                    image = Image.open(io.BytesIO(payload))
                    assert image.format == 'JPEG' and image.size == (2, 2)
                    red, green, blue = image.getpixel((0, 0))
                    assert red > 240 and green < 15 and blue < 15
            finally:
                pipeline.stop.set()
                thread.join(3)
    finally:
        path.unlink(missing_ok=True)
