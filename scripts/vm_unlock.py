# 一次性 QA 脚本：经 QEMU HMP 唤醒麒麟 V11 虚拟机锁屏并输入密码解锁。
# 锁屏密码从环境变量 WANWEI_VM_PASSWORD 读取；未设置时拒绝运行，不再硬编码。
import os
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

PASSWORD = os.environ.get("WANWEI_VM_PASSWORD")
if not PASSWORD:
    sys.exit("错误：未设置环境变量 WANWEI_VM_PASSWORD（麒麟 VM 的 sudo/锁屏密码），请先设置后再运行本脚本。")

def main():
    h = HMP()
    # 唤醒锁屏：按一下空格/回车，让密码框出现
    h.sendkey("spc")
    time.sleep(2)
    # 输入密码（HMP sendkey 支持 shift-x 组合）
    h.type_text(PASSWORD, delay=0.12)
    time.sleep(0.5)
    h.sendkey("ret")
    time.sleep(3)
    h.close()
    print("unlock sequence sent")

if __name__ == "__main__":
    main()
