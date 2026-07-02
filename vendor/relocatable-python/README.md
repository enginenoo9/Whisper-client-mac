# relocatable-python (vendored)

Source: https://github.com/gregneagle/relocatable-python
License: Apache License 2.0 (see `LICENSE` in this directory)
Retrieved: 2026-07-02, from the `main` branch

Unmodified except for this README. Used by `build-dmg.sh` to build a
`Python.framework` that actually works when copied somewhere other than
`/Library/Frameworks/` — the framework produced by python.org's official
installer has its binaries' library paths hard-coded to that absolute
location, so copying it as-is into an app bundle crashes with a
"Library not loaded" dyld error the moment it runs from anywhere else.
This tool downloads the same official installer and rewrites the Mach-O
binaries' load-command paths (via `install_name_tool`) to be relative, then
re-signs them.

Not vendored via git submodule/subtree so the build has no dependency on
reaching GitHub at build time (only python.org, which the tool itself talks
to) and so the exact reviewed version is pinned in this repo's history.
