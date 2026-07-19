# 一次性 QA 脚本：经 QEMU HMP 重启麒麟 V11 虚拟机内的 ssh 服务（需 sudo 密码）。
# sudo 密码从环境变量 WANWEI_VM_PASSWORD 读取；未设置时拒绝运行，不再硬编码。
import os
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
    run(h, "sudo systemctl restart ssh.socket ssh.service", wait=2)
    run(h, PASSWORD, delay=0.1, wait=2)
    run(h, "ss -tlnp | grep :22 || sudo ss -tlnp | grep :22", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
