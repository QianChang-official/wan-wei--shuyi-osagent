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
    # 抓取 FPM 错误上下文（前后若干行）
    run(h, "grep -n -iE 'fpm|error|ERR_|cannot|no such|not found|failed' ~/wanwei/build.log | head -40", wait=2)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
