"""Primary central runner; scientific stages are version-locked by the protocol."""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[3]
if __name__=='__main__':
 args=sys.argv[1:] or ['plan']
 tail=args if args[0] in {'--help','-h'} else [args[0],'e01_independent_extractor',*args[1:]]
 os.execve(sys.executable,[sys.executable,str(ROOT/'tools/experiments.py'),*tail],dict(os.environ))
