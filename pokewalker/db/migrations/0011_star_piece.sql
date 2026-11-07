CREATE TABLE active_effects_rewards (
    effect_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK(kind IN ('shiny_lure','star_piece')),
    starts_at REAL NOT NULL,
    expires_at REAL CHECK(expires_at>starts_at),
    receipt_key TEXT NOT NULL,
    remaining_encounters INTEGER NOT NULL
        CHECK(typeof(remaining_encounters)='integer' AND remaining_encounters BETWEEN 0 AND 10),
    remaining_rewards INTEGER NOT NULL DEFAULT 0
        CHECK(typeof(remaining_rewards)='integer' AND remaining_rewards BETWEEN 0 AND 10),
    CHECK((kind='shiny_lure' AND remaining_rewards=0)
       OR (kind='star_piece' AND remaining_encounters=0))
);
INSERT INTO active_effects_rewards
    (effect_id,profile_id,kind,starts_at,expires_at,receipt_key,remaining_encounters)
SELECT effect_id,profile_id,kind,starts_at,expires_at,receipt_key,remaining_encounters
FROM active_effects;
DROP TABLE active_effects;
ALTER TABLE active_effects_rewards RENAME TO active_effects;
CREATE INDEX active_effects_profile_remaining ON active_effects(profile_id,remaining_encounters);
CREATE UNIQUE INDEX active_effects_one_active ON active_effects(profile_id) WHERE remaining_encounters>0;
CREATE UNIQUE INDEX active_effects_one_star_piece ON active_effects(profile_id) WHERE remaining_rewards>0;
