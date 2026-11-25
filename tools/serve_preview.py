"""Local UI preview with explicit JS/WASM MIME types on Windows."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    extensions_map={**SimpleHTTPRequestHandler.extensions_map,
                    '.js':'text/javascript','.mjs':'text/javascript',
                    '.wasm':'application/wasm'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'web'
    print(f'Preview http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(root))).serve_forever()
