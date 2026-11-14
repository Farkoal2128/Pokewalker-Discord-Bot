ALTER TABLE guilds ADD COLUMN arena_enabled INTEGER NOT NULL DEFAULT 1
    CHECK(arena_enabled IN (0,1));
ALTER TABLE profiles ADD COLUMN arena_best_floor INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(arena_best_floor)='integer' AND arena_best_floor>=0);

CREATE TABLE arena_runs (
    run_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT CHECK(end_reason IN ('loss','draw','expired')),
    revision INTEGER NOT NULL DEFAULT 0,
    floor INTEGER NOT NULL CHECK(typeof(floor)='integer' AND floor>=1),
    slot INTEGER NOT NULL CHECK(slot IN (0,1,2)),
    team TEXT NOT NULL CHECK(json_valid(team)),
    enemy TEXT NOT NULL CHECK(json_valid(enemy)),
    CHECK((ended_at IS NULL)=(end_reason IS NULL))
);
CREATE UNIQUE INDEX arena_runs_live ON arena_runs(profile_id) WHERE ended_at IS NULL;
CREATE INDEX arena_runs_profile ON arena_runs(profile_id,started_at);

CREATE TABLE arena_tickets (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    tier TEXT NOT NULL CHECK(tier IN ('bronze','silver','gold','platinum','diamond')),
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>=0),
    PRIMARY KEY(profile_id,tier)
);
