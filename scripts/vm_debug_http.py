# 一次性 QA 脚本：经 QEMU HMP 排查麒麟 V11 虚拟机内 http.server 进程与日志，并重启 9000 端口服务。
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

def run(h, text, delay=0.06, wait=1.0):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    run(h, "ps aux | grep http.server | grep -v grep", wait=1)
    run(h, "cat /tmp/http.log", wait=1)
    run(h, "python3 -m http.server 9000 --bind 127.0.0.1 &", wait=1)
    time.sleep(1)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
