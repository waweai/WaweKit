# Wawekit

Professional open-source desktop cheminformatics toolkit built with Python,
RDKit and PySide6.

This documentation is built with [MkDocs](https://www.mkdocs.org/) and grows
alongside the application. See the `learning/` folder in the repository for a
graphical abstract and build notes for every completed module.

**→ See [FEATURES.md](FEATURES.md) for a complete reference of every feature:**
what it is, why it's useful, real-world applications, how it works internally,
and the step-by-step workflow to use it.

**→ See [PACKAGING.md](PACKAGING.md)** for building a distributable desktop
bundle with PyInstaller.

## Architecture at a glance

Wawekit uses a strict layered architecture where dependencies only point
downward:

```
gui  ->  services  ->  models  ->  core
```

- **core** — configuration, logging, cross-platform paths, constants.
- **models** — RDKit-backed domain objects (no Qt).
- **services** — orchestration and background workers.
- **gui** — PySide6 windows and widgets.
