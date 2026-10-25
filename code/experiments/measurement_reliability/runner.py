from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from storygen_platform.cli import main
if __name__=="__main__":
    raise SystemExit(main([*(sys.argv[1:2] or ["inspect"]),"measurement_reliability",*sys.argv[2:]]))
