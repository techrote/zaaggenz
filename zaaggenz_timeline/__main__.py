"""Open Compose through the authoritative single-origin ZaagGenZ runtime."""
from zaaggenz_runtime.__main__ import run

def main():run(default_workspace='compose',default_open=False)
if __name__=='__main__':main()
