CREATE TABLE finds (
    find_id INTEGER PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    message_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>0),
    outcome TEXT NOT NULL CHECK(outcome IN ('granted','overflow','duplicate_rare','stardust')),
    created_at REAL NOT NULL
);
CREATE INDEX finds_profile_time ON finds(profile_id,created_at);
