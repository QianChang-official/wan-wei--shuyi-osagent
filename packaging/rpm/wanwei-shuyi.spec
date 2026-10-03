# Copyright (c) 2026 QianChang-official
#
# 宛委·枢忆 is licensed under Mulan PSL v2.
# 遵循银河麒麟桌面操作系统打包规范（V10 规范适配至 RPM 格式）：
#   - 包名小写字母/数字/. - +；文件名形如 name-version-release.arch.rpm
#   - 应用主体安装至 /opt/apps/<packagename>/
#   - .desktop 至 /usr/share/applications/（含 Name/Name[zh_CN]/Icon/Exec/Type）
#   - SVG 图标至 /usr/share/icons/hicolor/scalable/apps/<packagename>.svg
#   - 维护脚本以 root 运行且妥善处理错误；依赖在安装时自动联网下载

%define debug_package %{nil}

Name:           wanwei-shuyi
Version:        1.0.0
Release:        1
Summary:        宛委·枢忆 — 端侧记忆治理与多智能体编排控制台
License:        Mulan PSL v2
URL:            https://github.com/QianChang-official/wan-wei--shuyi-osagent
BuildArch:      noarch

# 运行时依赖：系统 python3（3.10+）；pip 依赖由 %post 自动联网下载
Requires:       python3
Requires:       curl

Source0:        %{name}-%{version}.tar.gz

%description
宛委·枢忆（Wanwei Shuyi）端侧记忆治理与多智能体编排控制台。

包含 FastAPI 后端（wanwei-shuyi-memoryops-autopilot v1.0.0）与
「花朝台」Web 控制台（三栏智能体工作台，单页静态构建）。
安装时自动联网创建 Python 虚拟环境并从镜像源下载全部依赖；
安装完成后以 systemd 服务运行，控制台地址 http://127.0.0.1:8010/console/ 。

%prep
%setup -q

%build
# 纯 Python + 预构建静态前端，无需编译

%install
rm -rf %{buildroot}

# 应用主体 → /opt/apps/wanwei-shuyi
install -d %{buildroot}/opt/apps/wanwei-shuyi
cp -a backend frontend bin packaging doc %{buildroot}/opt/apps/wanwei-shuyi/
chmod 755 %{buildroot}/opt/apps/wanwei-shuyi/bin/wanwei-shuyi
chmod 755 %{buildroot}/opt/apps/wanwei-shuyi/bin/install-deps.sh

# 桌面入口（规范 3.3）
install -Dm 644 packaging/desktop/wanwei-shuyi.desktop \
    %{buildroot}/usr/share/applications/wanwei-shuyi.desktop

# SVG 矢量图标（规范 3.4）
install -Dm 644 packaging/icons/wanwei-shuyi.svg \
    %{buildroot}/usr/share/icons/hicolor/scalable/apps/wanwei-shuyi.svg

%files
/opt/apps/wanwei-shuyi
/usr/share/applications/wanwei-shuyi.desktop
/usr/share/icons/hicolor/scalable/apps/wanwei-shuyi.svg

%post
# 安装/升级后：联网下载全部 Python 依赖并启动服务（规范 3.5，root 执行）
bash /opt/apps/wanwei-shuyi/bin/install-deps.sh

%preun
# 卸载（非升级）前停止并摘除服务
if [ "$1" = "0" ]; then
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl stop wanwei-shuyi.service 2>/dev/null || true
        systemctl disable wanwei-shuyi.service 2>/dev/null || true
        rm -f /etc/systemd/system/wanwei-shuyi.service
        systemctl daemon-reload 2>/dev/null || true
    fi
fi

%postun
if [ "$1" = "0" ]; then
    # 卸载后清理可再生成的虚拟环境；用户数据 /var/lib/wanwei-shuyi 保留
    rm -rf /opt/apps/wanwei-shuyi/venv
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications 2>/dev/null || true
    fi
fi

%changelog
* Tue Sep 15 2026 QianChang-official - 1.0.0-1
- 首个 RPM 发布：三栏控制台 + FastAPI 后端，依赖安装时自动联网下载
