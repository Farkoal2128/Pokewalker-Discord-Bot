CREATE TABLE arena_month_scores (
    guild_id TEXT NOT NULL,
    month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month,6,2) BETWEEN '01' AND '12'),
    profile_id TEXT NOT NULL,
    floor INTEGER NOT NULL CHECK(typeof(floor)='integer' AND floor >= 1),
    reached_at REAL NOT NULL,
    PRIMARY KEY(profile_id,month),
    FOREIGN KEY(profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
CREATE INDEX arena_month_scores_guild_month ON arena_month_scores(guild_id,month);
CREATE TABLE arena_months (
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month,6,2) BETWEEN '01' AND '12'),
    settled_at REAL NOT NULL,
    PRIMARY KEY(guild_id,month)
);
CREATE TABLE arena_month_places (
    guild_id TEXT NOT NULL,
    month TEXT NOT NULL CHECK(month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]' AND substr(month,6,2) BETWEEN '01' AND '12'),
    place INTEGER NOT NULL CHECK(typeof(place)='integer' AND place >= 1),
    profile_id TEXT NOT NULL,
    floor INTEGER NOT NULL CHECK(typeof(floor)='integer' AND floor >= 1),
    PRIMARY KEY(guild_id,month,place),
    UNIQUE(profile_id,month),
    FOREIGN KEY(profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
