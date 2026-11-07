CREATE TABLE opt_outs (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(guild_id,user_id)
);
CREATE TABLE marker_log_init (
    id INTEGER PRIMARY KEY CHECK(id=1),
    at REAL NOT NULL
);
