# Restricted JVM dependency network

This operator tool provisions a dedicated internal Docker bridge, an egress
bridge, and a bounded proxy for JVM dependency SETUP. Future JVM execution
containers must join only the internal bridge; the proxy joins both bridges.
The proxy and probe run as UID/GID `65532:65532`, with a read-only filesystem,
dropped capabilities, no new privileges, and fixed CPU, memory and PID limits.
They receive no host ports, host mounts, Docker socket or credentials. Inherited
HTTP proxy variables are cleared and Docker logging is disabled.

The proxy accepts only `CONNECT repo.maven.apache.org:443`. It rejects other
hosts, literal IPs, other ports and ordinary forward HTTP. Every resolved IPv4
address must be public; the connection then uses a checked address without a
second DNS lookup. IPv6 upstream connections are unsupported. Connection,
header, timeout and byte limits bound each tunnel.

TLS remains end to end between the client and Maven Central. The proxy does not
inspect TLS SNI, URL paths, tunneled HTTP methods or artifact contents. Package
checksums and repository declarations remain separate responsibilities. The
Web dependency proxy and its allowlist are unchanged.

## Create and verify

Run from the repository's Python environment, using a local Linux/amd64 Docker
engine and its matching local `docker` Buildx driver:

```powershell
.venv/Scripts/python.exe scripts/sprint12_bootstrap_jvm_dependency_network.py create --repo-root C:/work/orchestwin-studio --output-root C:/evidence/jvm-dependencies-001 --docker-context desktop-linux
```

Both paths must be absolute and free of symlinks or junctions. The output
directory must not exist and must be outside the repository, without containing
the repository. The normal mode requires a clean checkout and verifies the
provisioning inputs against the current commit before and after provisioning.
The loaded Python package must belong to the selected checkout.

The build uses the digest-pinned Node base, `--network=none`, and a minimal
context containing only the Dockerfile and proxy source. Created resources have
UUID-scoped names, ownership labels and recorded immutable Docker IDs. The tool
checks the actual container restrictions and network membership.

An independent probe container on the internal bridge performs eight checks:

| Check | Required observation |
| --- | --- |
| Maven Central TLS | Download the JUnit Jupiter 5.11.4 POM with valid TLS and expected coordinates. |
| Unknown host | Deny `example.com:443`. |
| Literal IP | Deny `127.0.0.1:443`. |
| Metadata IP | Deny `169.254.169.254:443`. |
| Invalid port | Deny Maven Central on port 80. |
| Forward HTTP | Reject an ordinary HTTP proxy request. |
| Direct egress | Prevent a direct TCP connection to `1.1.1.1:443`. |
| Web host | Deny `registry.npmjs.org:443`. |

All eight must pass before `manifest.json` reports `READY`. The manifest binds
the source hashes, commit, environment, image, resources, policy and bounded
observations. Its `controlled_network` object matches `ControlledJvmNetwork`.
These are provisioning observations, not exhaustive routing proofs or profile
validation evidence; `level_d_validated` remains `false`.

Add `--development` only for diagnostics using uncommitted inputs. This records
`development: true` and `committed_sources_verified: false`; it does not grant
Level D or approve Gate 7 execution. Repeat normal provisioning from the owner's
committed clean checkout before using it as a validation prerequisite. Neither
mode accesses a database or writes Git state.

## Attempt-scoped cache configuration

`src/orchestwin/jvm_execution/dependency_setup.py` provides the pure
`setup_configuration(target, attempt_id, network)` factory. It returns immutable
environment values and file payloads under
`/workspace/.orchestwin/jvm/<attempt UUID hex>`. File payload paths are relative
to the mounted workspace. Gradle receives separate HOME and GRADLE_USER_HOME
locations plus `gradle.properties`. sbt receives HOME, SBT_OPTS, separate boot,
global, Ivy and Coursier caches, and an explicit Maven Central repositories file.

A network binding supplies explicit proxy settings without a bypass list.
Passing `None` preserves the same attempt cache paths and removes SETUP proxy
settings; sbt also receives `sbt.offline=true`. Gradle still requires `--offline`
and all post-SETUP containers require Docker networking disabled.

The factory performs no I/O and does not create or populate caches. Integration
with the JVM executor is still required: materialize payloads safely, reject
unapproved inherited environment, verify the live network binding, seed the
launchers, resolve all dependency artifacts, and enforce phase isolation.
Successful provisioning does not establish those execution capabilities.

## Remove owned resources

After all dependent containers have finished and detached:

```powershell
.venv/Scripts/python.exe scripts/sprint12_bootstrap_jvm_dependency_network.py remove --manifest C:/evidence/jvm-dependencies-001/manifest.json --docker-context desktop-linux
```

Removal validates the Docker endpoint, IDs, names and ownership labels before
removing the owned containers and networks. It retains the proxy image and
evidence files, and writes a new `removal-<UUID>/manifest.json` receipt.
Creation failures attempt bounded cleanup and retain their failure manifest.

Use a `REMOVAL_FAILED` receipt to retry incomplete cleanup. If creation was
interrupted before its final manifest, use the latest `progress-*.json` receipt.
A failed inspect alone does not prove absence: cleanup requires a successful
Docker inventory confirming it. Preserve receipts and resolve any remaining
owned resources without Docker-wide pruning.

Local proxy tests use injected DNS/dial functions and loopback sockets:

```text
node --test infra/jvm-runners/dependency-network/proxy.test.mjs
```
