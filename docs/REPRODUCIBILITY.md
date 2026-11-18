# Run and reproduce

[Home](../README.md) · [Code map](CODE_GUIDE.md) · [Validation](EVIDENCE_GUIDE.md)

## Open without installing anything

Use the live dashboard linked from the README, or read the PDF/slides/CSV directly in this repository.

## Preview the public review edition

With Python installed, run from the repository root:

```text
python review.py check
python review.py serve
```

Open http://127.0.0.1:8455. The server is local-only. Stop it with Ctrl+C. The prebuilt site requires no JavaScript build or numerical dependencies.

The public check verifies the release file hashes, the twenty-name order and the editable presentation structure. It verifies the delivered snapshot, not a fresh statistical refit.

## Work on the frontend

```text
npm --prefix dashboard ci
npm --prefix dashboard run dev
```

For a static frontend build:

```text
npm --prefix dashboard run build
```

The public source edition uses the frozen public JSON and documents. Model fitting is not part of a frontend build.

## Numerical reproduction boundary

The proprietary six-file pack, private identity/selection evidence and fitted caches are deliberately excluded. The analytical modules and their declared configuration explain the method, but the public copy alone cannot regenerate the authoritative selected twenty from raw records.

A complete statistical rebuild needs the licensed pack, the full operator pipeline and the private evidence layer. Dependencies for that environment are recorded in requirements.txt. Rankings and reports were regenerated from frozen scores, not refitted during presentation revisions.

The private project retains the Windows runner commands python run.py all, rankings, rankings_final and test, with matching Makefile targets. Those operator commands are not advertised as a data-free public workflow.

## Update this public snapshot

Generate the public export from the private project after the numerical and presentation checks pass. Publish that clean export, rather than the private working checkout or its history. Public manifest hashes describe the released snapshot and must be refreshed when an intentional new version is built.
