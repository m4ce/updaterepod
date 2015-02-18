#
# Updaterepo daemon spec file
#

%if 0%{?suse_version} > 1210
%global _with_systemd 1
%else
%global _with_systemd 0
%endif

Name: updaterepod
Version: %{pkg_version}
Release: %{pkg_build}
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
mkdir -p %{buildroot}%{_sysconfdir}/{updaterepod,sysconfig}
cp etc/*.yaml %{buildroot}%{_sysconfdir}/updaterepod
cp ext/rpm/updaterepod.sysconfig %{buildroot}%{_sysconfdir}/sysconfig/updaterepod

%if 0%{?_with_systemd}
%{__install} -d -m0755 %{buildroot}%{_unitdir}
%{__install} -m0644 ext/rpm/updaterepod.service %{buildroot}%{_unitdir}/updaterepod.service
%else
%{__install} -d -m0755 %{buildroot}%{_sysconfdir}/init.d
%if 0%{?suse_version}
%{__install} -m0755 ext/rpm/updaterepod.init %{buildroot}%{_sysconfdir}/init.d/updaterepod
%endif
%endif

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
%dir %{_sysconfdir}/updaterepod
%config(noreplace) %attr(0644,-,-) %{_sysconfdir}/updaterepod/config.yaml
%config(noreplace) %attr(0644,-,-) %{_sysconfdir}/sysconfig/updaterepod
%{_sbindir}/updaterepod
%if 0%{?_with_systemd}
%dir %{_unitdir}
%{_unitdir}/updaterepod.service
%else
%{_sysconfdir}/init.d/updaterepod
%endif

%changelog
* Wed Feb 18 2015 <matteo.cerutti@hotmail.co.uk>
First release
