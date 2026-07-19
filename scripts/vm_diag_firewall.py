# 一次性 QA 脚本：经 QEMU HMP 诊断麒麟 V11 虚拟机监听端口与 iptables 防火墙状态。
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
    run(h, "ss -tlnp 2>&1 | head -15 || netstat -tlnp 2>&1 | head -15", wait=2)
    run(h, "iptables -L -n 2>&1 | head -5 || echo no-iptables", wait=1)
    run(h, "python3 -m http.server --help 2>&1 | head -5", wait=1)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
