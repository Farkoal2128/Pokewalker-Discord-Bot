CREATE TABLE fusions (
    pokemon_uid TEXT PRIMARY KEY NOT NULL REFERENCES pokemon ON DELETE CASCADE,
    partner_uid TEXT NOT NULL UNIQUE,
    partner TEXT NOT NULL CHECK(json_valid(partner)),
    fused_at REAL NOT NULL
);
