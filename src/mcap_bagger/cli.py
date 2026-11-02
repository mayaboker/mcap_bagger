"""Manual command loop or simulation-controlled recorder service."""

import argparse
import shlex
import signal
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

from .control import ControlledRecorder
from .recorder import Recorder
from .recording_control import RecordingController
from bullet_msgs.recording_control import DEFAULT_STATE_ENDPOINT, DEFAULT_STATUS_ENDPOINT


def _prepare_output_directory(path):
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix='.mcap-write-check-', dir=path) as probe:
            probe.write(b'\0')
            probe.flush()
    except OSError as error:
        raise ValueError(f'Cannot write MCAP output directory {path}: {error}') from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="load YAML and wait for simulation runs")
    parser.add_argument("--ready-file", type=Path, help="write readiness marker after control subscriptions are installed")
    parser.add_argument('--output-dir', help='MCAP directory override; requires --config, relative to the working directory')
    parser.add_argument('--control-mode', choices=('simulation', 'recording'), default='simulation',
                        help='simulation lifecycle (default) or recorder-only state control')
    parser.add_argument('--recording-state-endpoint', default=DEFAULT_STATE_ENDPOINT)
    parser.add_argument('--recording-status-endpoint', default=DEFAULT_STATUS_ENDPOINT)
    args = parser.parse_args()
    if args.output_dir is not None and not args.config:
        parser.error('--output-dir requires --config')
    if args.control_mode == 'recording' and not args.config:
        parser.error('--control-mode recording requires --config')
    service = None
    cleanup_failed = False
    recorder = Recorder(
        on_error=lambda message: print(message, file=sys.stderr, flush=True)
    )

    def terminate(signum, frame):
        raise KeyboardInterrupt

    previous_interrupt = signal.getsignal(signal.SIGINT)
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        if args.config:
            print(recorder.init(args.config, output_dir=args.output_dir), flush=True)
            _prepare_output_directory(recorder.config.output_dir)
            if args.control_mode == 'recording':
                service = RecordingController(recorder, args.recording_state_endpoint,
                    args.recording_status_endpoint, report=lambda message: print(message, flush=True))
                print('Waiting for MAVLink recording state; recorder idle', flush=True)
            else:
                service = ControlledRecorder(recorder, report=lambda message: print(message, flush=True))
                print("Waiting for physics running state; Stop/Reset closes recording", flush=True)
            if args.ready_file:
                args.ready_file.write_text("ready\n")
            while True:
                service.poll()
        print("Commands: init <yaml>, start, close, quit")
        while True:
            try:
                parts = shlex.split(input("mcap-bagger> "))
                if not parts:
                    continue
                if parts[0] == "init" and len(parts) == 2:
                    print(recorder.init(parts[1]))
                elif parts == ["start"]:
                    print(recorder.start())
                elif parts == ["close"]:
                    print(recorder.close())
                elif parts == ["quit"]:
                    break
                else:
                    print("Usage: init <yaml> | start | close | quit")
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr, flush=True)
    except (EOFError, KeyboardInterrupt):
        print()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Ignore repeated shutdown signals while accepted data is drained.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if service is not None:
                service.close()
            else:
                print(recorder.close())
        except Exception as error:
            cleanup_failed = True
            print(f'Recorder shutdown failed: {error}', file=sys.stderr, flush=True)
        if args.ready_file:
            try:
                args.ready_file.unlink(missing_ok=True)
            except OSError as error:
                print(f'Could not remove readiness marker: {error}', file=sys.stderr, flush=True)
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_interrupt)
    return 1 if cleanup_failed or (recorder.recording and recorder.recording.error) else 0


if __name__ == "__main__":
    raise SystemExit(main())
