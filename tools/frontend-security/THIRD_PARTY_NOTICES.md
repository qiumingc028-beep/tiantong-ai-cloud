# Third-party notices

## Acorn

- Package: `acorn`
- Version: `8.17.0`
- Scope: test-only static analysis
- Source: `https://registry.npmjs.org/acorn/-/acorn-8.17.0.tgz`
- Registry integrity: `sha512-xRQbDb9BnwDafYNn6Vwl839DYVjqXYb1XVGtWAZ1kcDc6iwAL4hg3B1dZlRiuENFeO2H53gFG3in621AdERVAg==`
- Vendored tarball SHA-256: `afa83fff751e6c9739eea552d84328414d3860408f98ce5c7f3cc7e2a3996424`
- License: MIT

Acorn is used only by the repository's frontend security tests. It is not
imported by production frontend code and is not copied into the Nginx image.

The Acorn MIT license is included in the vendored package tarball as
`package/LICENSE`.
