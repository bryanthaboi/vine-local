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

The current [custom integration publishing guide](https://contributors.home-assistant.io/marketplace/guides/integrations/)
covers the Marketplace and repository layout. A catalog listing is a separate
submission. A custom-repository release does not mean acceptance into that catalog
or Home Assistant Core.

Brand images ship locally in the integration's `brand/` folder, as supported since
Home Assistant 2026.3. They do not need a pull request to the upstream brands
repository. The HACS validation currently skips its legacy brand-registry check.

Inclusion in [Home Assistant Core](https://developers.home-assistant.io/docs/creating_integration_manifest/)
is a separate upstream contribution with its own review, library and quality
requirements. A public custom integration lets owners validate device models
before pursuing that route.
