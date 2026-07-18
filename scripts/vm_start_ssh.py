import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

PASSWORD = "@Qwe123asdf"

def run(h, text, delay=0.06, wait=0.5):
    h.type_text(text, delay=delay)
    h.sendkey("ret")
    time.sleep(wait)

def main():
    h = HMP()
    # UKUI 下打开终端：Ctrl+Alt+T
    h.sendkey("ctrl-alt-t")
    time.sleep(3)
    # 尝试启动 sshd（麒麟 V11 桌面版通常已装 openssh-server，服务名 ssh）
    run(h, "sudo systemctl start ssh", wait=1.5)
    # 输入 sudo 密码
    run(h, PASSWORD, delay=0.1, wait=2)
    run(h, "sudo systemctl enable ssh", wait=1)
    run(h, "systemctl status ssh --no-pager | head -5", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
