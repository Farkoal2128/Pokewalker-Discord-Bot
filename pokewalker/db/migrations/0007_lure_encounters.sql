CREATE TABLE active_effects_counted (
    effect_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind='shiny_lure'),
    starts_at REAL NOT NULL,
    expires_at REAL CHECK(expires_at>starts_at),
    receipt_key TEXT NOT NULL,
    remaining_encounters INTEGER NOT NULL
        CHECK(typeof(remaining_encounters)='integer' AND remaining_encounters BETWEEN 0 AND 10)
);
-- Keep history; a backward clock must not revive earlier activations.
INSERT INTO active_effects_counted
SELECT effect_id,profile_id,kind,starts_at,expires_at,receipt_key,
       CASE WHEN expires_at>unixepoch('now','subsec')
                 AND effect_id=(SELECT latest.effect_id FROM active_effects AS latest
                                WHERE latest.profile_id=active_effects.profile_id
                                ORDER BY latest.starts_at DESC,latest.rowid DESC LIMIT 1)
            THEN max(0,10-(SELECT count(*) FROM encounters WHERE lure_id=active_effects.effect_id))
            ELSE 0 END
FROM active_effects;
DROP TABLE active_effects;
ALTER TABLE active_effects_counted RENAME TO active_effects;
CREATE INDEX active_effects_profile_remaining ON active_effects(profile_id,remaining_encounters);
CREATE UNIQUE INDEX active_effects_one_active ON active_effects(profile_id) WHERE remaining_encounters>0;
