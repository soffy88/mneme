# RC8 Container Security Qualification

Status: **NOT QUALIFIED**. Production deployment: **NO**.

Date: 2026-09-14. Scans used Trivy 0.74.0 with the current vulnerability
database and `--scanners vuln --severity CRITICAL,HIGH`.

## RC7 exact-image baseline

| image | result | primary target |
|---|---:|---|
| `mneme-api@sha256:0e2ee0e0048e1c91b05f2aa3e9366f1c313d6e6a15d19b07e33a0936a4736c79` | 3 Critical / 53 High | Debian 13.6 OS packages |
| `mneme-web@sha256:ad2ae640a77d0d3cca9abcbe2cf59aa4d7d90e35dba7223d13b956608522a404` | 3 Critical / 84 High | Debian 13.4 OS packages |

The API result is machine-readable in `rc7-api-trivy.json`; the frontend
result is in `rc7-frontend-trivy.json`. Trivy produced zero findings in the
API `python-pkg`, `node-pkg`, and Rust binary targets. The API Critical matrix
is three `perl-base` findings at `5.40.1-6`, all with fixed version
`5.40.1-6+deb13u1`: CVE-2026-13221, CVE-2026-42496, and CVE-2026-8376.

The 53 API High findings are OS-package findings, primarily `util-linux`
family packages (`bsdutils`, `libblkid1`, `liblastlog2-2`, `libmount1`,
`libsmartcols1`, `libuuid1`, `login`, `mount`, `util-linux`) plus `perl-base`,
`libpcre2-8-0`, `libsqlite3-0`, `libsystemd0`, `libudev1`, ncurses, gzip, and
libacl. The raw JSON records installed/fixed versions and CVE IDs per item.

## RC8 exact published candidates

| image | digest | result | primary target |
|---|---|---:|---|
| `mneme-api` | `sha256:52b6f0f0d00b7ba5bb83694939bae06e66ec9ec82168f6322e050d81a39b73af` | 5 Critical / 57 High | Debian 12.15 OS packages |
| `mneme-web` | `sha256:b8b9173fc4adbf90932cbec22af343d65225aa40c49b993707e15a107c658cf8` | 6 Critical / 58 High | Debian 12.13 OS packages |

Machine-readable results are `rc8-api-trivy.json` and
`rc8-frontend-trivy.json`. No RC8 runtime Python or Node vulnerability was
reported in these scans; the remaining findings are in the image OS layer.
Several packages have a fixed version in the database, while many current
entries have `FixedVersion` unavailable. This is not accepted as a blanket
exception: runtime-reachable Critical/High counts remain non-zero.

## `.echo/echomimic_repo` disposition

`NOT_RUNTIME_REACHABLE`. The repository is excluded by the root `.dockerignore`,
is not copied by the API Dockerfile, and is outside the frontend Dockerfile
build context. No release image layer, package install, or runtime import path
was found. Its separate local filesystem findings remain debt and are not
silently accepted as release risk.

## Attempted remediation and release decision

The RC7-to-RC8 candidate changed the base from the old Debian 13.6/13.4
images to pinned Debian bookworm images, but the exact RC8 scans above still
fail the required Critical/High policy. A test switch to Alpine was reverted:
the locked runtime dependency `onnxruntime==1.29.0` has no
`musllinux_1_2_x86_64` wheel, so that change would not produce a valid runtime
image without an additional dependency/runtime change.

RC8 is already public (`tag object b9687852dad1935f593b88aa1ee4940dd197a46b`,
peeled commit `617a3d964e3ed1d24c90f52e4a3b471f3633c809`). It was not moved or
rewritten. Any subsequent image/base/dependency/build-context change must use
**RC9**, not RC8.

Because security acceptance failed, RC8 staging deployment, Veya live gate,
and 30-minute soak were not run and cannot be inferred from RC5–RC7 evidence.

## Gate summary

- Runtime/build change in this qualification turn: **NO** (the incompatible
  Alpine experiment was reverted).
- RC7 tag unchanged: **YES**.
- RC8 tag unchanged: **YES**.
- New exploitable Critical/High: **not zero**.
- RC8 qualified: **NO**.
- RC9 required for the next image change: **YES**.
- Next gate: **FIX BLOCKERS / RC9 security candidate**, then repeat staging
  qualification.
