"""Run the authoritative single-origin ZaagGenZ local runtime."""
from __future__ import annotations
import argparse,webbrowser
from .server import ZaaggenzServer

WORKSPACES={'compose':'/timeline','listening':'/listen','inspector':'/inspector','vocal':'/vocal','legacy':'/'}

def run(*,default_workspace='compose',default_open=False):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--sample-rate',type=int,default=48000)
    p.add_argument('--workspace',choices=tuple(WORKSPACES),default=default_workspace)
    p.add_argument('--open',action='store_true',default=default_open)
    p.add_argument('--no-browser',action='store_true')
    p.add_argument('--verbose',action='store_true')
    p.add_argument('--demo-fixture',action='store_true',help='explicitly preload Inspector synthetic demo/test material')
    a=p.parse_args()
    if not 0<=a.port<=65535:p.error('port must be 0..65535')
    if not 8000<=a.sample_rate<=192000:p.error('sample-rate must be 8000..192000')
    with ZaaggenzServer(a.port,a.sample_rate,a.verbose,demo_fixture=a.demo_fixture) as server:
        base=f'http://127.0.0.1:{server.server_port}';url=base+WORKSPACES[a.workspace]
        print('zaaggenz runtime:',base,flush=True);print('workspace:',url,flush=True)
        if a.open and not a.no_browser:webbrowser.open(url)
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass

def main():run()
if __name__=='__main__':main()
