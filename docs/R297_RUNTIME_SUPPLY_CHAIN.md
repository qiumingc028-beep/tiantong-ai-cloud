# R297 Runtime Supply Chain

The JD browser runtime uses the digest-pinned Microsoft Playwright 1.62.1 Noble image. Chromium is supplied by that image, and the npm Playwright version must remain exactly `1.62.1`. Every directly installed Ubuntu package has an exact version; builds must not replace those values with unversioned installs.

To upgrade, update the Playwright tag, verified MCR digest, npm lockfile, OCI labels, and explicit APT package versions together in one reviewed change. CI must then build the image, verify the expected labels and installed Chromium executable, run the runtime tests, and exercise the authenticated noVNC proxy. Never run an implicit browser download during the image build.
