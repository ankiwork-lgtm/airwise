# Vendored axe-core

- **Package**: `axe-core`
- **Version**: `4.14.1`
- **Release Date**: November 2026 (actively maintained)
- **Licence**: `MPL-2.0` (Mozilla Public License 2.0; licence header preserved in `axe.min.js`)
- **Source Tarball**: `https://registry.npmjs.org/axe-core/-/axe-core-4.14.1.tgz`
- **Tarball SHA-512**: `sha512-FHfa+lmNjQZfJz1q8wKqIDwC6DExcHt/pkjNQb09a3NPjCKg2rhu5qb2S4r76ASyFNNtuFooJpZe37OgudVGtQ==`
- **Extracted `package/axe.min.js` SHA-256**: `29348999450cdf2849a8e70b7912fc2da85a849da39c0d0d5394f51d4a9ed95c`

## How to update

1. Query `https://registry.npmjs.org/axe-core/latest` to get the latest stable version and its `dist.tarball` and `dist.integrity`.
2. Download the tarball over HTTPS and verify its SHA-512 hash against `dist.integrity`.
3. Extract `package/axe.min.js` in memory and write it to `tests/browser/vendor/axe.min.js`.
4. Calculate the SHA-256 of `tests/browser/vendor/axe.min.js` and update the hash recorded in this file and in `tests/browser/test_accessibility.py`.
5. Run the test suite to ensure the integrity assertion passes.
