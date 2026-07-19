# 一次性 QA 脚本：经 QEMU HMP 在麒麟 V11 虚拟机内拉取并执行 guest_setup.sh 环境准备。
# guest 内 sudo 密码从环境变量 WANWEI_VM_PASSWORD 读取并注入 guest 会话；未设置时拒绝运行，不再硬编码。
import os
import shlex
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

PASSWORD = os.environ.get("WANWEI_VM_PASSWORD")
if not PASSWORD:
    sys.exit("错误：未设置环境变量 WANWEI_VM_PASSWORD（麒麟 VM 的 sudo/锁屏密码），请先设置后再运行本脚本。")

def run(h, text, delay=0.06, wait=0.6):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    run(h, "mkdir -p ~/wanwei && cd ~/wanwei", wait=0.8)
    run(h, "curl -s -o guest_setup.sh http://10.0.2.2:8000/scripts/guest_setup.sh", wait=3)
    run(h, "ls -l guest_setup.sh && head -2 guest_setup.sh", wait=1)
    run(h, f"export WANWEI_VM_PASSWORD={shlex.quote(PASSWORD)}", wait=0.5)
    run(h, "bash guest_setup.sh 2>&1 | tee setup.log | tail -15", wait=90)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
