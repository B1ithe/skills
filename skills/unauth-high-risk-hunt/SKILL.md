---
name: unauth-high-risk-hunt
description: >
  Hunt remote unauthenticated high-impact bugs (RCE, or a chain that reaches
  a command sink without credentials) on a target the operator can test.
  Covers auth bypass, parse-diff, SQL injection, file read/write, SSRF, token
  minting, and pre-auth protocol/binary bugs.
  Use when the user asks to dig unauth RCE, unauthenticated high-risk vulns,
  auth bypass, SQLi, arbitrary file read/write, path traversal, parse-diff,
  remaining attack surface, or runs /unauth-high-risk-hunt.
  Also trigger on 未授权高危, 未授权RCE, 鉴权绕过, SQL注入, 任意文件读, 任意文件写.
---

# Unauth high-risk hunt

Product-security hunt for **remote + unauthenticated + high impact** (code execution).
The process is the skill. A closed negative hunt with a remaining-bridge map is a
valid finish. Lowering the bar so something "counts" is not.

SQL injection and arbitrary file read/write are **mandatory primitives**, but by
default they are in-scope high-impact only if they reach a command sink or arm a
proven exec chain. `SELECT version()` or SPA HTML is a negative, not RCE.

The method is language-agnostic (Go, Java, Python, C/C++, PHP, Node, and others
follow the same loop). API names in this file are examples; swap in the target
stack's equivalents during static work.

Work only on systems the operator owns or has written permission to test.
Do not write public exploit kits, malware, or attack unrelated systems.

## 0. Freeze the bar

Write one acceptance sentence and keep it in view:

> A finding is in-scope iff an unauthenticated remote client, with no
> operator-set password and no local/unix/loopback-only precondition,
> can cause attacker-controlled code execution (or a live chain that
> necessarily reaches a command sink on this build).

Default **exclusions** (override only if the operator explicitly expands the bar):

| Exclude | Why |
|---------|-----|
| Operator-set admin / default passwords | Not a product vuln precondition |
| Local-only unix sockets, loopback admin ports | Not remote |
| Cluster vote / HA membership APIs | State ≠ exec unless it reaches a sink |
| Worker crash, SIGABRT/SIGFPE, connection DoS | Not code execution |
| Info leak, user enum, captcha OCR, SMS flood | Not high-impact exec |
| Unauth SQLi / LFI that only reads non-secret data | Leak ≠ exec; in-scope only if it yields a ticket/key that is then used, or writes a disk path that is executed |
| Fail-open that only spawns a login GUI / fixed argv | Not arbitrary command |
| Skip-auth that still dies on IAM / business auth | Reached handler, not sink |
| CVE/public writeups as evidence | Must be grounded in **this** build |

Lab hygiene, unless the operator names the action:

- Do not POST reboot / shutdown / factory-reset / firmware-patch / image-import.
- Do not dump live secrets into chat (datastore passwords, live OTPs, session
  codes, full DB dumps). Describe key/column **shape** and whether a value is present.
- File-write proofs land on a `/tmp` marker or an operator-named path. Do not
  overwrite system disks or drop a webshell into production webroot.
- Destructive live proofs only with an explicit go-ahead. Never a reverse shell
  into a third party.

If the environment drops, continue **static** on the same build; re-prove live
when it returns. Do not mix evidence across versions.

## 1. Map the surface before endpoints

Build three listen tables. Do not hunt HTTP until these exist.

1. **WAN** — TLS/TCP ports reachable from the attacker host.
2. **Loopback** — `127.0.0.1` / `::1` admin, RPC, patch, debug.
3. **Local IPC** — unix sockets, named pipes, mode bits (world-writable is local
   RCE material, not remote), which process owns them.

For HTTP, map **reverse-proxy location → unix/TCP backend → process → artifact**
(ELF, JAR, interpreter script, etc.).
The same process or artifact may expose many sockets (API vs static vs OpenAPI vs plugin).
A second `listen N` server in the proxy is **not** WAN-reachable unless stream/SNI
actually steers there.

Deliverable: `attack_surface_inventory.md` with columns
`surface | bind | process | researched? | remaining question`.

Always add two rows even if unfinished: **unauth SQL entry points**,
**unauth file read/write entry points**.

## 2. Auth once, then scan

Do not randomly POST handlers. Find how authentication is applied.

1. Gateway / reverse-proxy auth vs application middleware vs IAM / ACL.
2. Whitelist / `none` / `try-auth` / empty middleware that just continues.
3. **Which view of the request is authenticated** (normalized path, raw URI,
   a forwarded header the proxy overwrites or injects, Host, method+service).
4. **Which view is routed** to the business handler.
5. Session source: cookie, `Authorization`, capability token, protocol-level
   SSO. Can it be minted unauth, or only reused?

Then **exhaust generated routes** (OpenAPI, gRPC-gateway / protobuf HTTP rules,
Spring mappings, Django urls, Express/mux dumps), not a guessed subset:

- Direct unauth request.
- If a parse-diff exists, the same route through that diff.
- Record status + whether the **named handler** ran (logs beat status codes).

Classify every 2xx/4xx:

| Result | Meaning |
|--------|---------|
| Auth reject before handler | Closed for unauth |
| Handler ran, then IAM/business fail-closed | Reach ≠ sink; keep as desync note |
| Handler ran and returned data/write | In-scope primitive; see §5–§10 |
| Handler concatenates user input into SQL or a filesystem path | Must hunt; grade in §6–§7 |
| Feature-disabled / missing config | Conditional; see §10 |

## 3. Parse-diff (proxy vs app)

Whenever a proxy sits in front of a different HTTP stack, compare:

- URI: decode, `..` collapse, `//` authority, `;`, `#`, `%2e`, extra prefixes.
- Headers: hop-by-hop, underscored names, duplicates, `X-Forwarded-*`,
  headers the proxy **overwrites** vs **passes**.
- HTTP/2 / smuggling only if the edge actually speaks them.

A useful desync **simultaneously**:

1. Makes the authenticator see a whitelisted path, and
2. Makes the router/handler see a sensitive path.

If (1) works and (2) still 403s on missing session/IAM, **stop claiming
auth bypass to RCE**. Log it as "unauth can enter handler X; sink still
requires Y". Do not spend the next week on the same prefix.

The same split applies to file paths: the path after the proxy folds `..`,
versus the path the app decodes and then joins. Probe both.

Frontend bundles and extra anonymous / weak-auth prefixes are a **late** HTTP
pass, after generated-route scan, not a first pass.

## 4. Command sinks, then reachability

Inventory every exec-like sink in **this** build:

- Process: language process-spawn APIs (`os/exec`, `Runtime.exec`, `subprocess`,
  `os.system`, `ProcessBuilder`, `popen`, …), installer/update scripts, plugin
  load/reload, command templates with format placeholders.
- Database: `COPY PROGRAM`, `xp_cmdshell`, `INTO DUMPFILE` / `INTO OUTFILE`,
  Postgres `COPY TO PROGRAM`, UDFs.
- Files that will be executed or loaded after landing: webroot, plugin dirs,
  cron, authorized keys, conf that a proven upgrade chain reads.

For each sink record: callee, argv/SQL fixed vs attacker-controlled, bind
address, auth on the caller, live proof of exec (or why not).

**Then** hunt how an unauth remote client reaches that caller:

- HTTP handler that invokes it.
- SSRF to a loopback admin that invokes it (§8).
- Unauth write of config/plugin/executable landing files that arms a **known**
  chain (§7, §10).
- SQL injection that execs in-DB or writes a file (§6).
- Mint of a ticket the gateway already uses to spawn helpers (§5).

World-writable plugin/control sockets and unauth loopback JSON-RPC are
**local** primitives. They go in the inventory. They are not the remote
finding unless you also have a remote hop.

## 5. Token, session, store

Find every unauth writer and reader of credentials:

- Session create on "get config" / captcha / login start.
- OTP / reset codes: CSPRNG vs ordinary PRNG; TTL; attempt cap; where stored.
- SSO / one-time / capability keys: format string, TTL, who `SET`s them.
- Datastore bind: loopback + password vs WAN port.

A WAN port that **speaks** Redis/MySQL/PG/RDP/VNC is often a **protocol
facade** that still calls `RequestSession`-style SSO. Prove with a real
`GET`/`AUTH`/`handshake`. Using the **real** datastore password as AUTH on
the facade and still failing SSO is evidence they are not the same service.

If secrets live in a session JSON/hash keyed by a client-visible session id,
local datastore access can read them; that is **host access**, not remote
unauth, unless the facade or an HTTP handler exposes `GET`/`HGET`.
If SQLi / arbitrary file read can produce the same secret, attach it to the
mint bridge via §6–§7.

## 6. SQL injection

On unauth (or parse-diff-reachable) handlers, any user input that enters a
query must be graded. Do not stop at "injection exists".

### 6.1 How to find it

- String concat, format (`sprintf` / f-string / `+`) into SQL, input used as
  an identifier (`ORDER BY`, table, column).
- ORM / query-builder raw SQL, unsafe `WHERE` / `ORDER BY` interpolation.
- Second-order: a field written unauth, later concatenated by login or a job.
- Record error-based, time-based, boolean, and stacked capabilities separately;
  do not try only one.

### 6.2 How to grade (against the bar)

| Live capability | Grade |
|-----------------|-------|
| Only `SELECT version()` / non-secret tables | **Negative** (info leak) |
| Login tautology whose session **cannot** reach a sink | Default exclude; account takeover only if the operator expands the bar |
| Reads session / SSO / capability token / offline-usable key, **and actually mints a usable ticket** | Bridge 3; prove "read" **and** "used" |
| `INTO OUTFILE` / `COPY TO` onto a §4 landing path | Bridge 2; the path must be executed or loaded |
| `COPY PROGRAM` / `xp_cmdshell` / UDF | Direct command sink; prove the DBMS role has that privilege **on this instance** |
| Stacked hash rewrite that still needs the operator password to log in | Exclude (password as precondition again) |

DB role privileges (`FILE`, `SUPER`, stacked queries) must be verified on
**this instance**. Do not cite a default MySQL textbook as evidence.

The injection point itself must pass §2: reachable unauth or via parse-diff.
Authenticated SQLi is out of this skill's default scope.

## 7. File read / write

Treat the filesystem as a primitive. Probe static sites, download APIs, and
upload/extract separately.

### 7.1 Entry inventory

- Open / read / write / create, upload, download, extract, rename.
- Path join that consumes a user segment, zip-slip / tar traversal, symlinks,
  log paths, template export, enum tool-pack parameters, static file mapping.
- Proxy `..` folding vs app decode-then-join: two probes, not WAN-only.

### 7.2 Read

| Live result | Grade |
|-------------|-------|
| SPA missing-file fallback to `index.html`, 200 HTML | **Not** a file read |
| `..` → proxy 400 / app 500, empty body | Fail-closed |
| `{type}` / enum check; extra segments fall off the route → 401 | Fail-closed |
| Ordinary static assets, public installer packages | Negative |
| Ticket, key, plugin conf, datastore password, **and** it attaches to bridge 2 or 3 | In-scope; prove the value is **used** |

Record bypass-proxy direct-to-backend separately from WAN paths after proxy
folding. A 200 homepage is not `/etc/passwd`.

### 7.3 Write

A successful write is not enough. Ask whether the **landing path is executed
or loaded**:

- Yes: executable/includable webroot, plugin dir, cron, `authorized_keys`,
  conf a proven upgrade/migrate chain reads, DB `INTO OUTFILE` aimed at those.
- No: user cloud disk, audit archive, a zip only offered for download, an extra
  file in a fixed-argv tool-pack directory that is never run.

Prove with a `/tmp` marker or an operator-named path. For zip-slip, extract
overwrite, log paths, and upload extension/content-type, ask who later
`exec`s / `import`s / `Load`s the file.

Unauth write that never enters a §4 sink is a primitive, not remote RCE.

## 8. Outbound HTTP / SSRF

List unauth (or parse-diff-reachable) call sites that issue HTTP client
requests, redirects, or webhooks.

For each:

1. What is attacker-controlled (query IP, URL, Host, path)?
2. Validator (loopback, metadata IP, hostname, decimal/IPv4-mapped, port).
3. **Feature/config gate after the validator** — a valid public IP that never
   reaches a real outbound request is not SSRF.
4. A fixed URL template (`http://{ip}/fixed/path`) cannot aim at an arbitrary
   loopback sink.

Goal is a **live** fetch to a §4 loopback sink, not "the function exists".

## 9. Pre-auth binary / protocol

For each WAN protocol port:

1. Unpackers: length checks, fail-open vs fail-closed, "unformed" logs.
2. Auth advertised (None / password / NTLM / custom) vs actually required.
3. Whether a field is treated as an **SSO token** (hex of a challenge
   response, username, SID) rather than an OS password.
4. Dest-before-token: is a backend dialed before the ticket check?
5. Fail-open spawn: fixed helper argv vs attacker argv.

Memory corruption:

- Per-connection helper + seccomp + abort-on-teardown → usually worker DoS.
  Do not call it RCE without a surviving write that reaches a later sink in
  the same process.
- OOB **read** into an auth buffer that is not echoed is not exfil.

After unpackers fail-closed and auth is a token wall, **do not** keep mutating
handshake bytes. Switch back to HTTP mint / SSRF / SQL / file write.

## 10. Conditional chains

A chain that needs "plugin already configured", "migrate conf exists",
"IdP enrolled", or "CUSTOM plugin enabled" is **conditional**.

- Prove every hop that **is** live (SOAP reachable, decrypt works, unsigned
  payload accepted, local installer execs).
- Name the missing hop and whether any **unauth writer** (HTTP upload, zip-slip,
  SQLi file write) can create it.
- Do not create the missing conf yourself and call it unauth RCE.
- Do not use operator credentials to plant the precondition.

## 11. Remaining-bridge map

When HTTP desync, SSRF, mint, pre-auth protocol, SQL, and file I/O are all
fail-closed, remote unauth RCE usually collapses to four bridges. Track them:

1. **SSRF (or equiv) → loopback/unix command sink**
2. **Unauth write of something that will be executed or that arms a proven chain**
   (conf, plugin_data, webroot, cron, SQL `INTO OUTFILE`, zip-slip)
3. **Unauth mint of a ticket, or read of a secret that is then used as a ticket**
   (including via SQLi / file read)
4. **Auth view ≠ route view AND IAM/business also skipped**

SQLi and file I/O are **means** of crossing bridges 2 and 3, not a fifth
bridge. Close the line if you can only `version()` or only download installers.

A line of work is worth continuing only if it moves one of these.
Close and log lines that cannot.

## 12. Evidence and language

Every in-scope claim needs a **this-build** static anchor (function, key
format, argv, SQL concat site, path join) **and** a live probe (or an honest
"static only, env down").

Allowed phrasing:

- "Unauth remote client reached handler H; IAM returned 403."
- "Loopback Process execs gate G with no auth (not WAN)."
- "Conditional remote root if conf C exists; this snapshot has no C and
  no unauth writer for C."
- "Unauth SQLi can `SELECT version()`; current DB role has no `FILE`/stacked
  queries; cannot write disk or exec."
- "Unauth download treats type as an enum; `../` falls off the route → 401."
- "Unauth can write path P; that path is proven to enter an upgrade chain / `exec`."

Forbidden phrasing:

- Calling skip-auth+403, GUI fail-open, or local sock 0666 "remote unauth RCE".
- Calling `UNION SELECT 1` or SPA 200 arbitrary file read / RCE.
- Using another product's CVE as proof this build is vulnerable.

Keep three living files (names may vary):

- `attack_surface_inventory.md` — researched vs remaining
- `remaining_surfaces.md` — only open primitives
- changelog on the hunt doc — date, what was nailed, what is still open

Negatives belong in the changelog so the next session does not re-open them.

## 13. Session loop

Each session:

1. Re-read the bar and the remaining-bridge map.
2. Pick **one** bridge. Say which.
3. Static on this build until you can name a live probe.
4. Probe. Update inventory + changelog (positive or negative).
5. If the probe cannot move a bridge, **close the line** and pick another.

Same for SQL and file lines: first prove unauth reaches concat/join, then
prove the capability is more than a leak and lands on bridge 2 or 3.

Stop the whole hunt when the four bridges are closed on this snapshot, or
the operator changes the bar. Deliver the remaining map rather than a
forced "finding".
