# 发布检查表

公开 Release 由 `.github/workflows/release.yml` 生成。流水线只接受已存在的 `v*` tag，并在测试、构建和法律前置条件满足后发布源码包、容器镜像、SBOM、校验和与构建溯源。

## 法律与版本

- [ ] 项目所有者已选择并提交根目录 `LICENSE`。
- [ ] `backend/app/version.py` 的 `VERSION` 与 tag 完全一致。
- [ ] `VERSION_HISTORY[0]` 状态已更新为 `released`。
- [ ] `CHANGELOG.md` 已记录用户可见变更、迁移步骤和已知限制。
- [ ] README、部署、运维、API 与用户手册版本一致。

许可证属于项目所有者的法律/商业决策；自动化不会擅自选择，也不会在缺少 LICENSE 时公开发布。

## 工程验收

- [ ] Windows：`scripts/verify.ps1 -SkipInstall -IncludeArena` 通过。
- [ ] Linux：`WANWEI_SKIP_INSTALL=1 WANWEI_INCLUDE_ARENA=1 bash scripts/verify.sh` 通过。
- [ ] 运行时和开发 Python 依赖审计无已知漏洞。
- [ ] `npm audit --audit-level=high` 通过。
- [ ] CodeQL、Dependency Review 和 Trivy 无阻断项。
- [ ] 前端 `dist` 可由锁文件确定性重建且 `git diff` 为空。
- [ ] 容器以非 root、只读根文件系统、无 capabilities 运行并通过 smoke。

## 数据与灾备

- [ ] 从真实候选数据库创建备份并校验 SHA-256 清单。
- [ ] 在隔离环境完成恢复演练。
- [ ] 恢复后 Capsule、检索、审计和 workflow smoke 通过。
- [ ] 记录实测 RPO、RTO、数据库大小和恢复耗时。

## 赛题交付

- [ ] 银河麒麟目标环境适配报告包含真实系统版本、硬件、命令与截图。
- [ ] 偏好、知识召回和冲突处理指标有版本化数据集与原始结果。
- [ ] PPT、技术方案、测试报告、用户手册、演示视频和源码说明已冻结。
- [ ] 所有 `partial/planned/stub` 能力在材料中保持真实标注。

## 发布后

- [ ] GitHub Release 包含源码压缩包、CycloneDX SBOM 和 `SHA256SUMS`。
- [ ] GHCR 镜像 digest 与 provenance attestation 可查询。
- [ ] 用公开制品在干净环境完成一次安装和 smoke。
- [ ] 记录回滚镜像 tag 与升级前数据库备份位置。
