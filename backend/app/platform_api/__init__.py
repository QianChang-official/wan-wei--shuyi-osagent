"""万枢协作平台 API 聚合包（自动发现）。

本包内每个子模块代表一个平台领域（工作台、模型接入、智能体……）。
凡子模块顶层暴露 ``router``（``fastapi.APIRouter`` 实例）者，启动时自动
``include_router`` 进 ``api_router``，由 ``app.main`` 统一以 ``/platform``
前缀挂载。

单个子模块导入失败仅打印警告并跳过，不拖垮整体启动——保证某个并行
子代理的模块出错时，其余平台接口仍可用。
"""
import importlib
import pkgutil

from fastapi import APIRouter

api_router = APIRouter()


def _discover_routers() -> None:
    for info in pkgutil.iter_modules(__path__):
        name = info.name
        if name.startswith('_'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{name}')
        except Exception as exc:  # noqa: BLE001 —— 故意宽捕获，隔离故障模块
            print(f'[platform_api] 子模块 {name} 导入失败，已跳过：{exc!r}')
            continue
        router = getattr(module, 'router', None)
        if isinstance(router, APIRouter):
            api_router.include_router(router)


_discover_routers()
