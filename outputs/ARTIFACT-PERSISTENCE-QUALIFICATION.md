# RC6/RC7 artifact persistence qualification

Status: **PASS** for registry publication and fresh pull-by-digest.

- Registry: GHCR (`ghcr.io/soffy88`).
- Workflow: `Publish immutable Mneme release artifacts`, run `34790182132`.
- The publish job built and pushed API, worker, beat, and frontend images,
  generated the manifest and SBOM, and uploaded only this release's files.
- An independent GitHub-hosted runner pulled all four images by the recorded
  digest and verified `org.opencontainers.image.revision` against the manifest:
  **PASS**.
- Artifact source is registry content, not a local Docker store. OCI labels
  include revision, version, created timestamp, and source repository.

The first verification run was intentionally rejected because the upload glob
included historical manifests. The workflow was corrected to upload and select
only the requested release manifest; the subsequent fresh-runner gate passed.

RC5 remains unchanged and its lost local-only images were not reconstructed.
RC7 publication and fresh-pull verification also passed in workflow run
`34791859610`; its complete refs are in
`RELEASE-MANIFEST-v0.1.0-rc7.json`.
