"""万枢协作平台 API 聚合包（自动发现）。

本包内每个子模块代表一个平台领域（工作台、模型接入、智能体……）。
凡子模块顶层暴露 ``router``（``fastapi.APIRouter`` 实例）者，启动时自动
``include_router`` 进 ``api_router``，由 ``app.main`` 统一以 ``/platform``
前缀挂载。

单个子模块导入失败记 error 日志并跳过，不拖垮整体启动——保证某个并行
子代理的模块出错时，其余平台接口仍可用；失败模块名可通过
``failed_modules()`` 获取，由 readiness 暴露（03-#19）。
"""
import importlib
import logging
import pkgutil

from fastapi import APIRouter

logger = logging.getLogger(__name__)

api_router = APIRouter()
_LOADED_MODULES: list[str] = []
_FAILED_MODULES: dict[str, str] = {}


def _discover_routers() -> None:
    for info in pkgutil.iter_modules(__path__):
        name = info.name
        if name.startswith('_'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{name}')
        except Exception as exc:  # noqa: BLE001 —— 故意宽捕获，隔离故障模块
            # 03-#19: 仅 print 会在部署环境无声丢失；记 error 日志并登记
            # 失败模块名，供 readiness 暴露与运维排查。
            logger.error('[platform_api] 子模块 %s 导入失败，已跳过：%r', name, exc)
            _FAILED_MODULES[name] = repr(exc)
            continue
        router = getattr(module, 'router', None)
        if isinstance(router, APIRouter):
            api_router.include_router(router)
            _LOADED_MODULES.append(name)


_discover_routers()


def loaded_modules() -> list[str]:
    """返回已成功加载的平台 API 子模块清单，供健康检查使用。"""
    return list(_LOADED_MODULES)


def failed_modules() -> dict[str, str]:
    """返回导入失败被跳过的子模块 {模块名: 异常 repr}，供 readiness 暴露。"""
    return dict(_FAILED_MODULES)
