"""Export only benchmark artifacts; reject files containing the configured credential."""

import zipfile

from backend import config


def main():
    root = config.ROOT
    source = root / "runtime/benchmarks"
    files = {
        "baseline/results.json": source / "retail-full-before-20261027/results.json",
        "candidate-1/results.json": source / "retail-full-after-20261027/results.json",
        "candidate-2/results.json": source / "retail-full-optimized-20261027/results.json",
        "optimized/results.json": source / "retail-full-final-20261027/results.json",
        "comparison.json": root / "docs/reports/retail-full-20261027.json",
        "audit.md": root / "docs/reports/retail-full-audit-20261027.md",
    }
    payloads = {}
    for label, path in files.items():
        payload = path.read_bytes()
        if config.API_KEY and config.API_KEY.encode() in payload:
            raise ValueError("Credential detected; export blocked: " + label)
        payloads[label] = payload
    target = root / "docs/reports/retail-full-20261027.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for label, payload in payloads.items():
            archive.writestr(label, payload)
    print("Exported benchmark artifacts only:", target, "bytes:", target.stat().st_size)


if __name__ == "__main__":
    main()
