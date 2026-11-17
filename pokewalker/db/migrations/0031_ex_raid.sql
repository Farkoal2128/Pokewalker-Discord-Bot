CREATE TABLE ex_raids (
    ex_raid_id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    identity_id TEXT NOT NULL,
    shiny INTEGER CHECK(shiny IS NULL OR (typeof(shiny)='integer' AND shiny BETWEEN 0 AND 1)),
    level INTEGER CHECK(level IS NULL OR (typeof(level)='integer' AND level BETWEEN 1 AND 40)),
    iv_attack INTEGER CHECK(iv_attack IS NULL OR (typeof(iv_attack)='integer' AND iv_attack BETWEEN 0 AND 15)),
    iv_defense INTEGER CHECK(iv_defense IS NULL OR (typeof(iv_defense)='integer' AND iv_defense BETWEEN 0 AND 15)),
    iv_stamina INTEGER CHECK(iv_stamina IS NULL OR (typeof(iv_stamina)='integer' AND iv_stamina BETWEEN 0 AND 15)),
    hours INTEGER NOT NULL CHECK(typeof(hours)='integer' AND hours BETWEEN 1 AND 24),
    guild_id TEXT,
    servers INTEGER NOT NULL CHECK(typeof(servers)='integer' AND servers>=1),
    spawned INTEGER NOT NULL CHECK(typeof(spawned)='integer' AND spawned>=1),
    skipped TEXT NOT NULL CHECK(json_valid(skipped)),
    created_at REAL NOT NULL
);
CREATE INDEX ex_raids_created_at ON ex_raids(created_at);

ALTER TABLE world_spawns ADD COLUMN kind TEXT NOT NULL DEFAULT 'world' CHECK(kind IN ('world','ex'));
ALTER TABLE world_spawns ADD COLUMN ex_raid_id TEXT REFERENCES ex_raids;
DROP INDEX world_spawns_active_guild;
CREATE UNIQUE INDEX world_spawns_active_guild_kind ON world_spawns(guild_id,kind) WHERE ended=0;
