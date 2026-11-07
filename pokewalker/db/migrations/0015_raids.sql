ALTER TABLE guilds ADD COLUMN raids_enabled INTEGER NOT NULL DEFAULT 0 CHECK(raids_enabled IN (0,1));
ALTER TABLE guilds ADD COLUMN raid_channel_id TEXT;
CREATE TABLE world_spawns (
    spawn_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    pokemon_id INTEGER NOT NULL,
    identity_id TEXT NOT NULL,
    spawned_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    spawned_by_profile_id TEXT REFERENCES profiles(profile_id) ON DELETE SET NULL,
    post_state TEXT NOT NULL CHECK(post_state IN ('pending','attempted','sent')),
    message_id TEXT,
    ended INTEGER NOT NULL DEFAULT 0 CHECK(ended IN (0,1)),
    content_version TEXT NOT NULL
);
CREATE UNIQUE INDEX world_spawns_active_guild ON world_spawns(guild_id) WHERE ended=0;
CREATE TABLE raid_participation (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    spawn_id TEXT NOT NULL REFERENCES world_spawns ON DELETE CASCADE,
    encounter_id TEXT REFERENCES encounters ON DELETE SET NULL,
    joined_at REAL NOT NULL,
    PRIMARY KEY(guild_id,user_id,spawn_id)
);
ALTER TABLE encounters ADD COLUMN raid_spawn_id TEXT REFERENCES world_spawns ON DELETE CASCADE;
DROP TRIGGER encounter_queue_insert;
DROP TRIGGER encounter_queue_update;
CREATE TRIGGER encounter_queue_insert BEFORE INSERT ON encounters
WHEN NEW.raid_spawn_id IS NULL AND NEW.state IN ('queued','revealed') AND
    (SELECT count(*) FROM encounters WHERE profile_id=NEW.profile_id AND state IN ('queued','revealed')
     AND raid_spawn_id IS NULL)>=3
BEGIN SELECT RAISE(ABORT,'Encounter queue full'); END;
CREATE TRIGGER encounter_queue_update BEFORE UPDATE OF state,profile_id,raid_spawn_id ON encounters
WHEN NEW.raid_spawn_id IS NULL AND NEW.state IN ('queued','revealed') AND
    (SELECT count(*) FROM encounters WHERE profile_id=NEW.profile_id AND state IN ('queued','revealed')
     AND raid_spawn_id IS NULL AND encounter_id<>OLD.encounter_id)>=3
BEGIN SELECT RAISE(ABORT,'Encounter queue full'); END;
