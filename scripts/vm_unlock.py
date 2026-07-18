import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP

PASSWORD = "@Qwe123asdf"

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
