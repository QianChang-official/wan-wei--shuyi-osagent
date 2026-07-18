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
    run(h, "ldd ~/wanwei/app/desktop/node_modules/app-builder-bin/linux/x64/app-builder | head -20", wait=1.5)
    run(h, "~/wanwei/app/desktop/node_modules/app-builder-bin/linux/x64/app-builder --version 2>&1 | head -5", wait=2)
    run(h, "cat /etc/os-release | grep -E 'VERSION|ID_LIKE'", wait=1)
    h.close()
    print("done")

if __name__ == "__main__":
    main()
