"""Fetch the D51 immutable CSV snapshot and verify every reused cache byte.

``fetch_csvs`` returns and saves source_commit, sha256 (filename -> digest), and
optional_missing. A recorded hash mismatch raises ValueError without replacing
that file. The injected opener has urllib.request.urlopen's call contract.
"""

import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


SOURCE_COMMIT = "e5b79b2e15d7c50735a945936afd4cd1cfd94eae"
BASE_URL = f"https://raw.githubusercontent.com/PokeAPI/pokeapi/{SOURCE_COMMIT}/data/v2/csv"
CACHE_DIR = Path("build/pokeapi/e5b79b2e")
REQUIRED_CSVS = (
    "pokemon_species", "pokemon", "pokemon_forms", "pokemon_stats", "pokemon_types",
    "pokemon_form_types", "pokemon_species_names", "pokemon_form_names", "types",
    "pokemon_habitats", "pokemon_evolution", "stats", "items", "item_names", "type_efficacy",
)
OPTIONAL_CSVS = ("pokemon_sprites", "pokemon_form_sprites")


def fetch_csvs(directory=CACHE_DIR, *, opener=urlopen):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "source_commit": SOURCE_COMMIT, "sha256": {}, "optional_missing": [],
    }
    if manifest["source_commit"] != SOURCE_COMMIT:
        raise ValueError("cache source commit differs from D51 pin")
    hashes = manifest["sha256"]
    # Validate the whole existing cache before any download or replacement.
    for filename, expected in hashes.items():
        path = directory / filename
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"hash mismatch: {filename}")
    manifest["optional_missing"] = []
    for name in REQUIRED_CSVS + OPTIONAL_CSVS:
        filename = name + ".csv"
        path = directory / filename
        if path.exists() and filename in hashes:
            continue
        try:
            with opener(f"{BASE_URL}/{filename}", timeout=30) as response:
                data = response.read()
        except HTTPError as error:
            if name in OPTIONAL_CSVS and error.code == 404:
                manifest["optional_missing"].append(name)
                continue
            raise
        digest = hashlib.sha256(data).hexdigest()
        if filename in hashes and digest != hashes[filename]:
            raise ValueError(f"hash mismatch: {filename}")
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f"hash mismatch: unrecorded {filename}")
        temporary = path.with_suffix(".csv.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        hashes[filename] = digest
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


if __name__ == "__main__":
    print(json.dumps(fetch_csvs(), indent=2, sort_keys=True))
