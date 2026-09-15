from __future__ import annotations
import argparse,webbrowser
from .server import InspectorServer

def main():
    p=argparse.ArgumentParser(description='Run the loopback-only ZaagGenZ harmonic-comb inspector.')
    p.add_argument('--port',type=int,default=8766);p.add_argument('--sample-rate',type=int,default=48000);p.add_argument('--no-browser',action='store_true');p.add_argument('--verbose',action='store_true')
    p.add_argument('--demo-fixture',action='store_true',help='explicitly preload deterministic synthetic demo/test material instead of waiting for a bound render artifact')
    args=p.parse_args()
    server=InspectorServer(args.port,args.sample_rate,args.verbose,demo_fixture=args.demo_fixture);url=f'http://127.0.0.1:{server.server_port}/inspector'
    if not args.no_browser:webbrowser.open(url)
    print(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
