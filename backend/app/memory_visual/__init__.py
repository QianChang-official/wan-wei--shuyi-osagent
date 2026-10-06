# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# You can use this software according to the terms of the Mulan PSL v2.
# You may obtain a copy of Mulan PSL v2 at:
# http://license.coscl.org.cn/MulanPSL2
#
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND,
# EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT,
# MERCHANTABILITY OR FIT FOR A PARTICULAR PURPOSE.
# See the Mulan PSL v2 for more details.

"""视觉记忆子系统（VISTA 启发）。

把「图片」升格为一等记忆资产：无损入库（sha256 锚定）、可区域回看
（inspect/read_pixels，见 inspect.py）、可溯源派生（derived_from 链），
并整体纳入既有治理闭环——生命周期十态裁决、不可变账本、删除七处取证。

设计借鉴 VISTA（https://github.com/joshhhhhan/VISTA, arXiv:2610.02200）
的 lossless visual memory：观察以原始字节归档，回看时按需裁剪/采样，
而不是入库前先做有损压缩或一次性 OCR 后丢弃原图。
"""

from .store import (
    MAX_VISUAL_BYTES,
    MAX_VISUAL_DIMENSION,
    VisualValidationError,
    get_asset,
    list_assets,
    purge_assets_in_transaction,
    read_asset_bytes,
    write_visual_capsule,
)

__all__ = [
    "MAX_VISUAL_BYTES",
    "MAX_VISUAL_DIMENSION",
    "VisualValidationError",
    "get_asset",
    "list_assets",
    "purge_assets_in_transaction",
    "read_asset_bytes",
    "write_visual_capsule",
]
