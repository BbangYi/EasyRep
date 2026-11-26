"""Run the receive-only air viewer alongside the existing gateway."""
import argparse
import asyncio
import logging
import signal
import threading

from habitat_gateway.config import api_token, load_settings
from habitat.digital_twin.air.history import HistoryBootstrap, REQUEST_TIMEOUT_S
from habitat.digital_twin.air.mqtt import AirSubscriber
from habitat.digital_twin.air.service import AirState, start_server
from habitat.common.http import bearer_token
from habitat.saas.air import AirUploader, load_upload_config


def history_bootstrap(settings, states, limit):
    if not limit:
        return None
    try:
        return HistoryBootstrap(settings, states, api_token(settings), limit=limit)
    except ValueError:
        logging.warning('Air history disabled: local API settings or credential unavailable; MQTT remains active')
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Existing gateway TOML (read only)')
    parser.add_argument('--air-config', required=True, action='append', help='Air geometry JSON; repeat for more cages')
    parser.add_argument('--upload-config', help='Optional SaaS upload JSON; disabled when omitted')
    parser.add_argument('--history-limit', type=int, default=300,
                        help='Recent Gateway records to restore per cage (0 disables; maximum 1000)')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 0 <= args.history_limit <= 1000:
        parser.error('--history-limit must be 0..1000')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = load_settings(args.config)
    if settings.transport != 'mqtt':
        parser.error('Live air view requires MQTT transport')
    states, subscribers = {}, []
    for path in args.air_config:
        state = AirState(path)
        cage = next((c for c in settings.cages if c.id == state.cfg['cage_id']), None)
        if cage is None or cage.id in states:
            parser.error('Air cage_id must be unique and exist in gateway configuration')
        states[cage.id] = state
        subscribers.append(AirSubscriber(settings, cage, state))
    history = history_bootstrap(settings, states, args.history_limit)
    upload = load_upload_config(args.upload_config)
    token = bearer_token(upload.token_env, usage='air upload') if upload.enabled else None
    uploader = AirUploader(upload, settings, states, token)
    server = start_server(states, bind=args.bind, port=args.port)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    cloud = threading.Thread(target=lambda: asyncio.run(uploader.run(stop)), name='air-upload', daemon=True)
    restore = (threading.Thread(target=history.run, args=(stop,), name='air-history', daemon=True)
               if history is not None else None)
    try:
        for subscriber in subscribers:
            subscriber.start()
        if restore is not None:
            restore.start()
        cloud.start()
        logging.info('Air viewer ready cages=%s bind=%s port=%s cloud_enabled=%s history_enabled=%s',
                     ','.join(states), args.bind, server.server_address[1], upload.enabled, history is not None)
        stop.wait()
    finally:
        stop.set()
        for subscriber in subscribers:
            subscriber.close()
        if restore is not None and restore.is_alive():
            restore.join(timeout=REQUEST_TIMEOUT_S + 2)
        if cloud.is_alive():
            cloud.join(timeout=upload.timeout_s + 2)
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
