# 一次性 QA 脚本：经 QEMU HMP 诊断麒麟 V11 虚拟机网络（guest→host 可达性、本机 ssh 自连）。
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

def run(h, text, delay=0.06, wait=0.6):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    # guest -> host 方向：确认能访问宿主机
    run(h, "curl -s -m 5 http://10.0.2.2:8000/ping && echo HOST_REACHABLE || echo HOST_UNREACHABLE", wait=3)
    # 诊断 sshd：本机自连
    run(h, "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 wanwei@localhost echo LOCAL_SSH_OK", wait=6)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
