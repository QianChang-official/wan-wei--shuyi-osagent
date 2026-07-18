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
    run(h, "ls -la ~/wanwei/app/desktop/release/linux-unpacked/ 2>/dev/null | head -15 || ls -la ~/wanwei/app/desktop/linux-unpacked/ 2>/dev/null | head -15", wait=1.5)
    run(h, "ls -la ~/wanwei/app/desktop/release/linux-unpacked/resources/ 2>/dev/null | head -10 || ls -la ~/wanwei/app/desktop/linux-unpacked/resources/ 2>/dev/null | head -10", wait=1.5)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
