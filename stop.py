"""
AI-MCP-DB 서버 종료 스크립트
- port 8000 (FastAPI)
- port 8001 (MCP Server)
"""
import subprocess
import sys


def kill_port(port: int):
    pids = set()

    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    pids.add(parts[-1])

        if not pids:
            print(f"  port {port}: 실행 중인 프로세스 없음")
            return

        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            print(f"  port {port}: PID {pid} 종료")
    else:
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True
        )
        for pid in result.stdout.strip().splitlines():
            pid = pid.strip()
            if pid:
                subprocess.run(["kill", "-9", pid], capture_output=True)
                print(f"  port {port}: PID {pid} 종료")
        if not result.stdout.strip():
            print(f"  port {port}: 실행 중인 프로세스 없음")


if __name__ == "__main__":
    print("AI-MCP-DB 서버 종료 중...")
    kill_port(8000)
    kill_port(8001)
    print("완료")
