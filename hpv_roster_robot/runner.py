from __future__ import annotations
import argparse
import json
from hpv_roster_robot.service import run_fixture

def main() -> int:
    parser=argparse.ArgumentParser(description='适龄HPV接种名册核验机器人')
    parser.add_argument("fixture")
    parser.add_argument("--db",default="/tmp/hpv_roster_robot.sqlite3")
    args=parser.parse_args()
    result=run_fixture(args.fixture,args.db)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0

if __name__ == "__main__": raise SystemExit(main())
