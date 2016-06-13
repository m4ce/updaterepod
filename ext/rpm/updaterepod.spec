#
# Updaterepo daemon spec file
#

Name: updaterepod
Version: %{pkg_version}
Release: %{pkg_build}.%{?dist}
Group: System/Packages
License: GPLv2
Source: %{name}-%{version}.tar.gz
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires: python-pyinotify >= 0.9.4
Requires: updaterepo >= 0.9.9
Summary: Updaterepo daemon
BuildArch: noarch

%description
Updaterepo daemon

%prep
%setup -q

%build

%install
rm -rf %{buildroot}

mkdir -p %{buildroot}%{_sbindir}
cp bin/updaterepod.py %{buildroot}%{_sbindir}/updaterepod
cp etc/config.yaml %{buildroot}%{_sysconfdir}/updaterepod.yaml

%{__install} -d -m0755 %{buildroot}%{_unitdir}
%{__install} -m0644 ext/rpm/updaterepod.service %{buildroot}%{_unitdir}/updaterepod.service

%clean
rm -rf %{buildroot}

%post
%if 0%{?_with_systemd}
%service_add_post updaterepod.service
%else
%fillup_and_insserv -f updaterepod
%endif

%preun
%if 0%{?_with_systemd}
%service_del_preun updaterepod.service
%else
%stop_on_removal updaterepod
%endif

%postun
%if 0%{?_with_systemd}
%service_del_postun updaterepod.service
%else
%restart_on_update updaterepod
%insserv_cleanup
%endif

%files
%defattr(-,root,root)
%config(noreplace) %attr(0644,-,-) %{_sysconfdir}/updaterepod.yaml
%{_sbindir}/updaterepod
%dir %{_unitdir}
%{_unitdir}/updaterepod.service

%changelog
* Wed Feb 18 2015 <matteo.cerutti@hotmail.co.uk>
First release
