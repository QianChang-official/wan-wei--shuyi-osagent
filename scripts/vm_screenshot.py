import struct
import sys
import time

sys.path.insert(0, r"C:\Users\Administrator\Documents\VScode-Workspace\wanwei2.0\wan-wei--shuyi-osagent\scripts")
from hmp_client import HMP, http_get


def ppm_bytes_to_png(ppm_path, out_path):
    from PIL import Image
    img = Image.open(ppm_path)
    img.save(out_path)
    return out_path


def take_screenshot(local_png):
    h = HMP()
    h.screendump(r"C:\VMs\Kylin-V11\screen.ppm")
    h.close()
    time.sleep(0.5)
    return ppm_bytes_to_png(r"C:\VMs\Kylin-V11\screen.ppm", local_png)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "shot.png"
    print(take_screenshot(out))
