# RC9 Container Security Candidate

Status: **SECURITY GATE BLOCKED**. No RC9 image was published and no
production deployment was performed.

## RC8 root-cause matrix

The exact RC8 JSON results are `rc8-api-trivy.json` and
`rc8-frontend-trivy.json`. Every Critical/High finding is in the Debian OS
target; Python/Node findings are zero. Thus each finding is
`introduced_by_base_image=YES`, `package_runtime_required=YES` in the sense
that the package is present in the final runtime filesystem, and
`package_not_runtime_required=NO` for the scanner-visible package. Builder
compiler/dev headers are not copied into the final API layer; frontend build
dependencies are not copied into the Next standalone runner.

| RC8 image | Critical | High | fix available | no fix in current DB |
|---|---:|---:|---:|---:|
| API `sha256:52b6f0f0d00b7ba5bb83694939bae06e66ec9ec82168f6322e050d81a39b73af` | 5 | 57 | 12 | 60 |
| frontend `sha256:b8b9173fc4adbf90932cbec22af343d65225aa40c49b993707e15a107c658cf8` | 6 | 58 | 8 | 56 |

The fix-available API items include `libpcre2-8-0` and selected package
updates; the Critical `libsqlite3-0`/`perl-base`/`zlib1g` findings have no
fixed version in the current Trivy database for the installed bookworm
versions. Frontend's fix-available items additionally include `libcap2` and
`libgnutls30`. The raw JSON contains the per-CVE package, installed version,
fixed version, severity, and target.

The repeated no-fix findings are grouped by package/CVE in the raw evidence:
`bsdutils`, `libblkid1`, `libmount1`, `libsmartcols1`, `libuuid1`, `mount`,
`util-linux`, `util-linux-extra` (util-linux CVEs); `perl-base`; ncurses;
`libsystemd0`/`libudev1`; `gzip`; `libacl1`; `libsqlite3-0`; and `zlib1g`.
These remain unresolved rather than being ignored. Essential/required base
packages such as `perl-base`, `util-linux`, `bsdutils`, and `gzip` were not
deleted because doing so would invalidate the glibc/Python/Node runtime.

`.echo/echomimic_repo` remains `NOT_RUNTIME_REACHABLE`: root `.dockerignore`
excludes it, the API Dockerfile does not copy it, and frontend build context
does not contain it. It is excluded from the release-runtime matrix but not
deleted.

## RC9 candidate change

- API base: `python:3.12-slim-trixie@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`
- frontend base: `node:20-trixie-slim@sha256:1694ccde5ea9efb3060bb8612b1f287256061ff2a04d75dc1b71f57cb7239520`
- Final layers execute same-distribution `apt-get dist-upgrade` and remove
  apt lists.
- API no longer installs `build-essential`/`libpq-dev`: the locked production
  requirements have compatible manylinux wheels and the builder enforces
  `--only-binary=:all:`.
- Frontend runner retains only Next standalone/static/public output and removes
  npm/npx/corepack.
- Alpine/musl was not used; `onnxruntime==1.29.0` requires glibc-compatible
  manylinux wheels.

The candidate build was started with `--no-cache --pull` but canceled after
the Debian mirror stalled while downloading gcc-14. Therefore no candidate
image digest, Trivy result, GHCR push, fresh pull proof, or RC9 release SHA
exists yet. The source baseline is RC8 peeled commit
`617a3d964e3ed1d24c90f52e4a3b471f3633c809`; the candidate Dockerfile changes
are not a public tag.

## Gate decision

- RC8 tag unchanged: **YES**.
- RC9 tag: **NOT CREATED**.
- API/frontend RC9 Trivy: **NOT RUN — no image produced**.
- Fix-available runtime Critical/High after fix: **UNKNOWN; gate not passed**.
- `check.sh`, npm audit, pip-audit, gitleaks: **NOT RUN for RC9**.
- Staging canary, Veya live gate, regression gates, and 30-minute soak:
  **NOT RUN**, as required while security gate is blocked.
- Production deployed: **NO**.
- P0 blocker: candidate image build did not complete; RC8 runtime security
  findings remain unresolved.
- P1 blocker: none beyond the P0 security/build blocker.
- RC9 qualified: **NO**.
- Next gate: **FIX BUILD/SECURITY BLOCKERS**, then exact-image Trivy and only
  after PASS run RC9 staging qualification.
