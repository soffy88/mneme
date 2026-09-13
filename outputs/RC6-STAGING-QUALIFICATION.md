# Mneme v0.1.0-rc6 staging qualification

Status: **NOT QUALIFIED**.

RC6 artifacts are durably published and pass the independent pull-by-digest
gate. Full isolated-staging qualification has not yet been rerun against the
registry-pulled RC6 images, so RC6 must not be marked qualified.

## Published artifacts

See [`RELEASE-MANIFEST-v0.1.0-rc6.json`](RELEASE-MANIFEST-v0.1.0-rc6.json)
for the complete repository and digest records. The manifest records:

- release version `v0.1.0-rc6`;
- code release SHA `905e6d52abfbc8e58b85239320b8fad0ba279e87`;
- peeled source commit `49fbd442021785c4623dc2b3aef7a280056766fe`;
- runtime delta versus RC5: `NONE`;
- production deployed: `false`.

## Gates still required

- registry-pulled isolated staging deployment;
- canary A/B and core regression;
- live Veya `veya1.2-free` completion with token/cost capability results;
- provider failure non-advancement and no-double-write checks;
- full security audit set and a 30-minute staging soak.

Immersive remains OFF, the canary allowlist remains EMPTY, and production has
not been deployed or enabled.
