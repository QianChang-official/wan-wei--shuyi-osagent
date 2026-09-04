# 麒麟验证

README 性能实测表记录：银河麒麟 V11 虚拟机原生 SDK 端到端检索 30 次（预热 1 次剔除），p50 195.320ms、p95 246.473ms，全部请求 backend=`kylin_native`。原始样本和状态证据位于 [reports/kylin-native-sdk-evidence/](../reports/kylin-native-sdk-evidence/)。

桌面端采用 Electron，支持 XDG 用户目录、UKUI 主题、托盘、防睡眠与 deb 交付规划。原生向量 SDK 不可用时会回退 FTS5；当前项目仍是单节点 alpha，不宣称生产级高可用。
