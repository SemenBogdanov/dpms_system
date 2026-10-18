# Dagre 3.1.1

- Package: `@dagrejs/dagre@3.1.1` (official standalone ESM distribution).
- Upstream: https://github.com/dagrejs/dagre
- Tarball: https://registry.npmjs.org/@dagrejs/dagre/-/dagre-3.1.1.tgz
- Tarball integrity: `sha512-zroZB1dFOFiGgv4Xcrn1DckB1o4aOikPqD2NDQPV0WM//CXGcS6xiD0rNkqHmw6FEg4tabt4nxPLwgCWT+Vb2A==`
- Verification: the integrator verified tarball integrity and bundle version `3.1.1` before this implementation.
- `dagre-3.1.1.mjs` is the official standalone `.js` bundle mechanically renamed to `.mjs`, with no code changes.
- License: MIT. Colocated notices: `dagre-LICENSE.txt` and `dagre-LEGAL.txt`.

`layout-worker.mjs` imports `layout-engine.mjs`, which imports this local bundle.
Keep the engine off the main-thread import graph. No CDN, dynamic remote imports,
runtime network calls, or additional dependencies are required. The upstream
source-map comment is retained; no source map is needed at runtime.

## Lucide Icons

`../arrangement-icons.svg` is generated from the installed `lucide-react@0.323.0`
icon nodes, not hand-drawn replacements. Upstream: https://github.com/lucide-icons/lucide.
The copied ISC notice is `lucide-LICENSE.txt`. The sprite is served locally.
