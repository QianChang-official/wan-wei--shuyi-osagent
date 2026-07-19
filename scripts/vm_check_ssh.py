# 一次性 QA 脚本：经 QEMU HMP 检查麒麟 V11 虚拟机内 sshd 状态与 openssh-server 安装情况。
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
    run(h, "systemctl status ssh --no-pager | head -8", wait=1.5)
    run(h, "dpkg -l | grep openssh-server || echo NO_OPENSSH", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
