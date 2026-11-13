# publishing

A standalone GitHub repository can be installed through HACS as a custom
repository. It needs one integration under `custom_components`, a versioned
manifest, documentation, an issue tracker and `hacs.json`.

This repository uses that layout. The release ZIP preserves the
`custom_components/vine_local` directory for manual installs. HACS reads the
integration from the tagged repository tree.

For a release, update `manifest.json`, run the checks, push the version tag and
publish a GitHub release with the ZIP. Preview builds should be marked prerelease.
The build script checks that only integration sources enter the archive:

```sh
python scripts/build_release.py
```

[HACS publishing requirements](https://www.hacs.xyz/docs/publish/integration/)
explain distribution. A [default HACS listing](https://www.hacs.xyz/docs/publish/include/)
is a separate submission and requires brand assets in Home Assistant's brands
repository. The current HACS validation skips only that brand-registry check.
A custom-repository release does not mean the integration has been accepted into
HACS's default catalog or Home Assistant Core.

Inclusion in [Home Assistant Core](https://developers.home-assistant.io/docs/creating_integration_manifest/)
is a separate upstream contribution with its own review, library and quality
requirements. A public custom integration lets owners validate device models
before pursuing that route.
