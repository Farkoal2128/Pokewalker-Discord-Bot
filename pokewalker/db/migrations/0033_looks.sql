ALTER TABLE encounters ADD COLUMN look_id INTEGER CHECK(look_id IS NULL OR (typeof(look_id)='integer' AND look_id>0));
ALTER TABLE pokemon ADD COLUMN look_id INTEGER CHECK(look_id IS NULL OR (typeof(look_id)='integer' AND look_id>0));
CREATE TABLE look_unlocks (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    look_id INTEGER NOT NULL,
    unlocked_at REAL NOT NULL,
    PRIMARY KEY(profile_id, look_id)
);
