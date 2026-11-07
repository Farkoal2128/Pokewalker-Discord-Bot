CREATE TABLE active_effects (
    effect_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind='shiny_lure'),
    starts_at REAL NOT NULL,
    expires_at REAL NOT NULL CHECK(expires_at>starts_at),
    receipt_key TEXT NOT NULL
);
CREATE INDEX active_effects_profile_expiry ON active_effects(profile_id,expires_at);
