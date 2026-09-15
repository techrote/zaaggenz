"""Open Inspector through the authoritative single-origin ZaagGenZ runtime."""
from zaaggenz_runtime.__main__ import run

def main():run(default_workspace='inspector',default_open=True)
if __name__=='__main__':main()
