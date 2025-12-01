%define __os_install_post   %{nil}
%define __spec_install_post %{nil}
%define __spec_install_pre %{___build_pre}
%define _empty_manifest_terminate_build         0
%define _use_internal_dependency_generator     0
%define _source_payload w9.gzdio
%define _binary_payload w9.gzdio

Name:       %{name}
Version:    1
Release:    1
Summary:    Package %{name} built using bits.
License:    Public Domain
BuildArch:  %{arch}
Vendor:     CERN

%if "%{?requires}" != ""
Requires: %{requires}
%endif

%description

%prep

%build

%install
cp -a %{workdir}/%{path}/* %{buildroot}

%files
/*