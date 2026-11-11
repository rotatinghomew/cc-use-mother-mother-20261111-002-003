测试：python3 -m unittest discover -s tests/robot_sessions -p 'test_*.py'
构建：python3 -m compileall -q hpv_roster_robot
验收：python3 -m hpv_roster_robot.runner fixtures/demo.json --db /tmp/hpv_roster_robot-acceptance.sqlite3
