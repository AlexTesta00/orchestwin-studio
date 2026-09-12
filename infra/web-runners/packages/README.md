# PHP archive extraction package

The PHP runner installs the repository-owned Debian package offline. Composer
requires a ZIP extractor to install the locked PHPUnit dependencies. No package
manager network access is used during the PHP image build.

- Package: `unzip`, version `6.0-28+deb12u1`, architecture `amd64` (Debian 12).
- Size: 166504 bytes.
- SHA-256: `1c27c879f4f7f056499c5393d422fd6c77ff6fbfa450c3f91f2f205ca788cc36`.
- [Official package metadata and checksum](https://packages.debian.org/bookworm/amd64/unzip/download).
- [Official Debian security archive](https://security.debian.org/debian-security/pool/updates/main/u/unzip/unzip_6.0-28+deb12u1_amd64.deb).
- Retrieved and checked: 2026-09-12.

The Dockerfile verifies architecture and SHA-256 before installation. Bootstrap
input hashing captures the complete package bytes and Dockerfile in the PHP
recipe identity. This recipe supports the validated Linux amd64 environment;
other architectures require a separately verified package and validation.

The Debian package includes its distribution copyright and license notices in
`/usr/share/doc/unzip/copyright` after installation.
