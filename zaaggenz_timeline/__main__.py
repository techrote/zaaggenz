"""Run the local timeline and recovered instrument without a cloud service."""
import argparse
import webbrowser
from .server import TimelineServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port must be 0..65535')
    with TimelineServer(args.port, verbose=args.verbose) as server:
        url = f'http://127.0.0.1:{server.server_port}/timeline'
        print(f'zaaggenz timeline: {url}', flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
