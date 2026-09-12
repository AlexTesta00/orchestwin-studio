# Restricted dependency network

The Web validation fixtures need npm and Composer dependencies during SETUP.
This operator bootstrap creates two dedicated Docker bridge networks and a
bounded proxy. Application containers attach only to the internal bridge; the
proxy also attaches to its own egress bridge. No host port, host mount, Docker
socket, credential, or privileged capability is given to the proxy.

The fixed proxy accepts CONNECT on port 443 to `registry.npmjs.org`,
`repo.packagist.org`, `api.github.com`, and `codeload.github.com`. All returned
IPv4 DNS addresses must be public, then the connection uses a checked literal
address without another lookup. Literal destinations, private/special ranges,
unknown hosts, other ports, ordinary forward HTTP, and upgrade requests fail
closed. Header, connection, time, and byte budgets bound resource use.

HTTP/1.0 CONNECT without a Host header is supported for the PHP stream
transport. HTTP/1.1 requires Host; any supplied Host must be unique and match
the allowed CONNECT authority. Host Docker proxy settings are explicitly
cleared in both containers. Their Docker log driver is disabled; the operator
command retains bounded build, inspect, probe, and cleanup observations.

TLS remains between the package client and the destination. This proxy does not
inspect TLS SNI, URL paths, HTTP methods inside a tunnel, or package content.
Its scope is the fixed destination allowlist. Package lock integrity checks
remain the package manager's responsibility. Existing runner policy disables
npm scripts and Composer scripts/plugins during SETUP; later execution phases
have networking disabled. IPv6 upstream connections are not supported.

## Operator bootstrap

Use the approved clean checkout and a verified runner bootstrap manifest:

```powershell
.venv/Scripts/python.exe scripts/sprint12_bootstrap_web_dependency_network.py create --repo-root C:/work/orchestwin-studio --runner-manifest C:/evidence/runners/manifest.json --output-root C:/evidence/dependency-network --docker-context desktop-linux
```

The output directory must be fresh and outside the repository. The command
builds the proxy image from the pinned Node base without build network access,
using only the proxy source and Dockerfile as context. It creates UUID-scoped
resources, records their immutable IDs and ownership labels, and verifies the
actual topology and container restrictions. The existing local Node base must
be available from the runner bootstrap. Remote Docker endpoints are rejected.

An independent non-root probe container on the internal network checks a real
TLS-verified npm metadata download, denied hosts/IPs/ports/forward HTTP, and a
denied direct TCP connection to an external address. The manifest records these
observations and input hashes; a failed probe prevents readiness. A successful
probe is a bounded network observation, not a proof of all possible routing or
host firewall behavior and not Level D evidence.

Use the returned manifest's `controlled_network` object in the
[campaign configuration](../level-d/README.md). Its execution-policy hash must
match the controlled execution policy expected by the runtime. The dependency
policy and input hashes are separately recorded. Preserve all output logs and
receipts. Keep these resources alive while the campaign needs SETUP access.

`--development` explicitly permits uncommitted inputs for development checks.
Such a manifest is marked as development output. It must not be used as the
operator prerequisite for a profile-validation campaign; repeat the bootstrap
from the owner's approved clean commit first. Neither mode grants Level D or
approves any Gate 7 operation, and neither accesses a database.

## Removal and failure handling

After the dependent execution has ended:

```powershell
.venv/Scripts/python.exe scripts/sprint12_bootstrap_web_dependency_network.py remove --manifest C:/evidence/dependency-network/manifest.json --docker-context desktop-linux
```

Removal checks immutable IDs and ownership labels before touching resources.
It removes only the owned proxy/probe containers and their two owned networks.
It does not prune Docker, remove unrelated containers, or delete evidence.
Creation failures attempt the same bounded cleanup and retain the failure
receipt. Investigate any unresolved cleanup; never substitute blanket Docker
cleanup commands. The proxy image remains available locally.

A removal receipt with `REMOVAL_FAILED` retains the remaining resources and can
be supplied to the same `remove --manifest` command to resume cleanup. Keep the
original receipt as well; removal writes a new receipt instead of overwriting it.
If creation was terminated before its final manifest was written, use the latest
`progress-*.json` receipt for removal. A missing resource is accepted only after
a successful Docker inventory confirms its absence; transport failures do not
count as proof that cleanup succeeded.

## Checks and references

`node --test infra/web-runners/dependency-network/proxy.test.mjs` uses injected
DNS/dial functions and local loopback sockets, without external network access.
The CI Web job builds the proxy offline and runs these tests inside the pinned
Node runner with Docker networking disabled. Python tests exercise provisioning
failures, observation validation, and ownership checks without Docker mutation.

The implementation uses the documented [Docker bridge network behavior](https://docs.docker.com/engine/network/drivers/bridge/),
[Node HTTP CONNECT API](https://nodejs.org/api/http.html#event-connect_1),
and [Node TLS verification](https://nodejs.org/api/tls.html).
