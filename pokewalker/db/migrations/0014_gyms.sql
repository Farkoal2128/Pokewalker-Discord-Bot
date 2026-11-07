CREATE TABLE gyms (
    gym_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 32),
    created_at REAL NOT NULL,
    retired_at REAL,
    UNIQUE(guild_id,name),
    UNIQUE(gym_id,guild_id)
);
CREATE UNIQUE INDEX profiles_guild_key ON profiles(profile_id,guild_id);
CREATE TABLE gym_deployments (
    deployment_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL,
    gym_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    pokemon_uid TEXT NOT NULL REFERENCES pokemon ON DELETE CASCADE,
    deployed_at REAL NOT NULL,
    ends_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT CHECK(end_reason IN ('recalled','defeated','expired','mod_recall','excluded','retired')),
    paid_hours INTEGER NOT NULL DEFAULT 0 CHECK(typeof(paid_hours)='integer' AND paid_hours BETWEEN 0 AND 8),
    survivor_rolled INTEGER NOT NULL DEFAULT 0 CHECK(survivor_rolled IN (0,1)),
    FOREIGN KEY(gym_id,guild_id) REFERENCES gyms(gym_id,guild_id),
    FOREIGN KEY(profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX gym_active_gym ON gym_deployments(gym_id) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX gym_active_profile ON gym_deployments(profile_id) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX gym_active_pokemon ON gym_deployments(pokemon_uid) WHERE ended_at IS NULL;
CREATE TABLE gym_battles (
    battle_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL,
    gym_id TEXT NOT NULL,
    deployment_id TEXT REFERENCES gym_deployments ON DELETE SET NULL,
    challenger_profile_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    ticks INTEGER NOT NULL,
    events TEXT NOT NULL CHECK(json_valid(events)),
    engine TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(gym_id,guild_id) REFERENCES gyms(gym_id,guild_id),
    FOREIGN KEY(challenger_profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
ALTER TABLE profiles ADD COLUMN last_battle_at REAL;
ALTER TABLE pokemon ADD COLUMN gym_deployment_id TEXT REFERENCES gym_deployments ON DELETE SET NULL;
CREATE TRIGGER pokemon_deployed_guard BEFORE UPDATE OF state,level_x2,pokemon_id ON pokemon
WHEN OLD.gym_deployment_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'Pokemon is deployed'); END;
CREATE TRIGGER companion_deployed_guard BEFORE UPDATE OF companion_uid ON profiles
WHEN EXISTS (SELECT 1 FROM pokemon WHERE pokemon_uid=NEW.companion_uid AND gym_deployment_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'Pokemon is deployed'); END;
