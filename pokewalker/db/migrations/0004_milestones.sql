CREATE TABLE milestone_awards (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    milestone_id TEXT NOT NULL,
    earned_at REAL NOT NULL,
    PRIMARY KEY(profile_id,milestone_id)
);
CREATE TABLE inbox_items (
    inbox_id INTEGER PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    milestone_id TEXT NOT NULL,
    resource TEXT NOT NULL CHECK(resource IN ('item','stardust','candy')),
    resource_id TEXT,
    remaining INTEGER NOT NULL CHECK(typeof(remaining)='integer' AND remaining>=0),
    created_at REAL NOT NULL
);
CREATE INDEX inbox_items_profile_id ON inbox_items(profile_id);
