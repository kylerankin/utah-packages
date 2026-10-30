Name:           prefixdevname
Version:        0.2.0
Release:        1%{?dist}
Summary:        Udev helper utility that provides network interface naming using user defined prefix
License:        MIT
URL:            https://github.com/msekletar/prefixdevname
Source:         prefixdevname-%{version}-vendored.tar.xz

ExclusiveArch:  %{rust_arches}

BuildRequires:  cargo-rpm-macros
BuildRequires:  systemd-devel
BuildRequires:  systemd-rpm-macros
BuildRequires:  pkg-config

%description
This package provides a udev helper utility that tries to consistently name all
ethernet NICs using a user defined prefix (e.g. net.ifnames.prefix=net produces
NIC names net0, net1, ...). It is invoked from a udev rule and writes out a
configuration file for udev's net_setup_link built-in
(/etc/systemd/network/71-net-ifnames-prefix-<iface>.link).

%prep
%autosetup -n %{name}-%{version}
%cargo_prep -v vendor

%generate_buildrequires
%cargo_generate_buildrequires

%build
%cargo_build

%install
install -D -m 0755 target/release/prefixdevname %{buildroot}%{_udevdir}/prefixdevname
install -D -m 0644 rules/71-prefixdevname.rules %{buildroot}%{_udevrulesdir}/71-prefixdevname.rules
install -D -m 0755 dracut/71prefixdevname/module-setup.sh %{buildroot}%{_prefix}/lib/dracut/modules.d/71%{name}/module-setup.sh
install -D -m 0755 dracut/71prefixdevname-tools/module-setup.sh %{buildroot}%{_prefix}/lib/dracut/modules.d/71%{name}-tools/module-setup.sh

%files
%license LICENSE
%doc README.md
%{_udevdir}/prefixdevname
%{_udevrulesdir}/71-prefixdevname.rules
%dir %{_prefix}/lib/dracut/modules.d/71%{name}
%{_prefix}/lib/dracut/modules.d/71%{name}/module-setup.sh
%dir %{_prefix}/lib/dracut/modules.d/71%{name}-tools
%{_prefix}/lib/dracut/modules.d/71%{name}-tools/module-setup.sh

%changelog
* Fri Jan 16 2026 kylerankin <kylerankin@users.noreply.github.com> - 0.2.0-1
- Import recipe from msekletar/prefixdevname v0.2.0 for #505
