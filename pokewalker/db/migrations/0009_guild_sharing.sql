ALTER TABLE guilds ADD COLUMN sharing INTEGER NOT NULL DEFAULT 1 CHECK(sharing IN (0,1));
CREATE TABLE mod_audit_new (
    audit_id INTEGER PRIMARY KEY,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('user','channel','guild')),
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(trim(reason))>0),
    created_at REAL NOT NULL
);
INSERT INTO mod_audit_new SELECT * FROM mod_audit;
DROP TABLE mod_audit;
ALTER TABLE mod_audit_new RENAME TO mod_audit;
