# Terminal addons

Vendored, unmodified browser bundles from the official MIT-licensed
[xterm.js project](https://github.com/xtermjs/xterm.js), used with DSH's xterm 6.0.0.
Keeping these here makes patch installation independent of network/CDN access.
Each adjacent `*-LICENSE` contains the upstream license.

| Package | npm tarball | Bundle SHA-256 |
| --- | --- | --- |
| `@xterm/addon-search@0.16.0` | [npm archive](https://registry.npmjs.org/@xterm/addon-search/-/addon-search-0.16.0.tgz) | `7bc1b8c7b3549411f6f6f779524c4ded6ca621fd80d64b40a70ae7c78aefbf55` |
| `@xterm/addon-web-links@0.12.0` | [npm archive](https://registry.npmjs.org/@xterm/addon-web-links/-/addon-web-links-0.12.0.tgz) | `b74864125ef3889753b94e61eb4dabb99b2a27f920f0c9a7bd53cbe6d10f032a` |

The patch verifies these digests and wraps the UMD bundles in local CommonJS
scopes; it does not add globals, evaluate remote scripts or use a runtime CDN.
To update, review compatibility against the pinned DSH/xterm versions, download
the npm tarballs, verify their registry SHA-512 integrity, extract only
`package/lib/addon-*.js` and `package/LICENSE`, then update the digests and tests.
Source maps are not installed; their comments are omitted when embedding.
