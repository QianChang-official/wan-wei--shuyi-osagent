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

%define debug_package %{nil}
Name:           wanwei-shuyi
Version:        1.0.0
Release:        1
Summary:        宛委·枢忆 — 端侧记忆治理与多智能体编排控制台
License:        Mulan PSL v2
URL:            https://github.com/QianChang-official/wan-wei--shuyi-osagent
BuildArch:      noarch
Requires:       python3 >= 3.10
Requires:       curl
Requires:       systemd >= 235
Requires:       /usr/sbin/runuser
Requires(pre):  /usr/sbin/useradd
Requires(pre):  /usr/sbin/groupadd
Requires(pre):  /usr/bin/getent
Source0:        %{name}-%{version}.tar.gz

%description
Source-only Python backend and prebuilt static Web console. No Python wheels,
native SDK, models or runtime data are bundled. Dependencies must be installed
explicitly by an administrator before enabling the unprivileged system service.
The RPM does not provision a logged-in user's desktop automation session.

%prep
%setup -q

%build
# No compilation or network access.

%install
install -d %{buildroot}/opt/apps/wanwei-shuyi
cp -a backend frontend bin doc MANIFEST.json %{buildroot}/opt/apps/wanwei-shuyi/
chmod 755 %{buildroot}/opt/apps/wanwei-shuyi/bin/*
install -Dm 644 packaging/desktop/wanwei-shuyi.desktop \
    %{buildroot}/usr/share/applications/wanwei-shuyi.desktop
install -Dm 644 packaging/icons/wanwei-shuyi.svg \
    %{buildroot}/usr/share/icons/hicolor/scalable/apps/wanwei-shuyi.svg
install -Dm 644 packaging/systemd/wanwei-shuyi.service \
    %{buildroot}/usr/lib/systemd/system/wanwei-shuyi.service
install -Dm 600 packaging/environment %{buildroot}/etc/wanwei-shuyi/environment

%pre
getent group wanwei-shuyi >/dev/null || groupadd --system wanwei-shuyi || exit 1
if ! getent passwd wanwei-shuyi >/dev/null; then
    useradd --system --gid wanwei-shuyi --home-dir /var/lib/wanwei-shuyi \
        --no-create-home --shell /sbin/nologin wanwei-shuyi || exit 1
fi
# Never reuse a privileged or interactive account with this reserved name.
getent passwd wanwei-shuyi | while IFS=: read -r name password uid gid gecos home shell; do
    [ "$uid" != 0 ] && [ "$gid" != 0 ] && [ "$home" = /var/lib/wanwei-shuyi ] || exit 1
    case "$shell" in */nologin|*/false) ;; *) exit 1 ;; esac
    [ "$(id -gn wanwei-shuyi)" = wanwei-shuyi ] || exit 1
done || exit 1

%post
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || printf '%s\n' 'Warning: run systemctl daemon-reload manually' >&2
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || :
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || :
fi
printf '%s\n' 'Installed source only. See /opt/apps/wanwei-shuyi/doc/INSTALL.md.' \
    'No dependencies downloaded and no service started. Run install-deps.sh explicitly.'

%preun
if [ "$1" = 0 ] && [ -d /run/systemd/system ]; then
    systemctl stop wanwei-shuyi.service || exit 1
    systemctl disable wanwei-shuyi.service || exit 1
fi

%postun
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || :
fi
# Preserve the account, API key, SQLite/JSON state and locally provisioned venv.

%files
%defattr(-,root,root,-)
/opt/apps/wanwei-shuyi
/usr/share/applications/wanwei-shuyi.desktop
/usr/share/icons/hicolor/scalable/apps/wanwei-shuyi.svg
/usr/lib/systemd/system/wanwei-shuyi.service
%dir %attr(0700,root,root) /etc/wanwei-shuyi
%config(noreplace) %attr(0600,root,root) /etc/wanwei-shuyi/environment

%changelog
* Tue Sep 15 2026 QianChang-official - 1.0.0-1
- Source-only RPM with explicit dependency provisioning and unprivileged service
