"""
AI-MCP-DB 서버 종료 스크립트
- port 8801 (FastAPI)
- port 8802 (MCP Server)
"""
import os
import signal
import subprocess
import sys


def find_pids_for_port_linux(port: int) -> set:
    hex_port = format(port, '04X')
    inodes = set()

    for tcp_file in ['/proc/net/tcp', '/proc/net/tcp6']:
        try:
            with open(tcp_file) as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local_port = parts[1].split(':')[1]
                    state = parts[3]
                    inode = parts[9]
                    if local_port.upper() == hex_port and state == '0A':
                        inodes.add(inode)
        except FileNotFoundError:
            pass

    pids = set()
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        fd_dir = f'/proc/{pid}/fd'
        try:
            for fd in os.listdir(fd_dir):
                try:
                    link = os.readlink(f'{fd_dir}/{fd}')
                    for inode in inodes:
                        if f'socket:[{inode}]' in link:
                            pids.add(int(pid))
                except OSError:
                    pass
        except OSError:
            pass
    return pids


def kill_port(port: int):
    if sys.platform == "win32":
        result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        pids = set()
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
        pids = find_pids_for_port_linux(port)
        if not pids:
            print(f"  port {port}: 실행 중인 프로세스 없음")
            return
        for pid in pids:
            os.kill(pid, signal.SIGKILL)
            print(f"  port {port}: PID {pid} 종료")


if __name__ == "__main__":
    print("AI-MCP-DB 서버 종료 중...")
    kill_port(8801)
    kill_port(8802)
    print("완료")
