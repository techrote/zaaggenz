"""Run optional local vocal capture beside the normal Compose timeline."""
import argparse,webbrowser
from .server import VocalServer

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8765);p.add_argument('--open',action='store_true');p.add_argument('--verbose',action='store_true');a=p.parse_args()
    if not 0<=a.port<=65535:p.error('port must be 0..65535')
    with VocalServer(a.port,verbose=a.verbose) as server:
        url=f'http://127.0.0.1:{server.server_port}/vocal';print('zaaggenz vocal:',url,flush=True)
        if a.open:webbrowser.open(url)
        try:server.serve_forever(.2)
        except KeyboardInterrupt:pass
if __name__=='__main__':main()
