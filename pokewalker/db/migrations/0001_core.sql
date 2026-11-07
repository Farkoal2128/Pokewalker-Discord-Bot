CREATE TABLE guilds (
    guild_id TEXT PRIMARY KEY NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE guild_channels (
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    count_steps INTEGER NOT NULL DEFAULT 1 CHECK(count_steps IN (0,1)),
    react INTEGER NOT NULL DEFAULT 1 CHECK(react IN (0,1)),
    PRIMARY KEY(guild_id,channel_id)
);
CREATE TABLE profiles (
    profile_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    route_id TEXT NOT NULL DEFAULT 'refreshing_field',
    companion_uid TEXT REFERENCES pokemon(pokemon_uid) ON DELETE SET NULL,
    stardust INTEGER NOT NULL DEFAULT 0 CHECK(typeof(stardust)='integer' AND stardust>=0),
    encounter_meter_c INTEGER NOT NULL DEFAULT 0 CHECK(typeof(encounter_meter_c)='integer' AND encounter_meter_c>=0),
    find_meter_c INTEGER NOT NULL DEFAULT 0 CHECK(typeof(find_meter_c)='integer' AND find_meter_c>=0),
    companion_meter_c INTEGER NOT NULL DEFAULT 0 CHECK(typeof(companion_meter_c)='integer' AND companion_meter_c>=0),
    last_checkin_at REAL,
    created_at REAL NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    UNIQUE(guild_id,user_id)
);
CREATE TABLE restrictions (
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
    paused_until REAL,
    excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0,1)),
    share_banned INTEGER NOT NULL DEFAULT 0 CHECK(share_banned IN (0,1)),
    PRIMARY KEY(guild_id,user_id)
);
CREATE TABLE mod_audit (
    audit_id INTEGER PRIMARY KEY,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    actor_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('user','channel')),
    target_id TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(length(trim(reason))>0),
    created_at REAL NOT NULL
);
CREATE TABLE step_events (
    message_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    eligible_words INTEGER NOT NULL CHECK(eligible_words>=0),
    accepted_words INTEGER NOT NULL CHECK(accepted_words>=0),
    discarded_words INTEGER NOT NULL DEFAULT 0 CHECK(discarded_words>=0),
    awarded_c INTEGER NOT NULL CHECK(typeof(awarded_c)='integer' AND awarded_c>=0),
    reason TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX step_events_profile_time ON step_events(profile_id,created_at);
CREATE TABLE encounters (
    encounter_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    source_channel_id TEXT,
    source_message_id TEXT,
    pokemon_id INTEGER NOT NULL,
    level_x2 INTEGER NOT NULL CHECK(level_x2 BETWEEN 2 AND 80),
    iv_attack INTEGER NOT NULL CHECK(iv_attack BETWEEN 0 AND 15),
    iv_defense INTEGER NOT NULL CHECK(iv_defense BETWEEN 0 AND 15),
    iv_stamina INTEGER NOT NULL CHECK(iv_stamina BETWEEN 0 AND 15),
    gender TEXT NOT NULL CHECK(gender IN ('male','female','genderless')),
    shiny INTEGER NOT NULL CHECK(shiny IN (0,1)),
    tier TEXT NOT NULL,
    route_id TEXT NOT NULL,
    lure_id TEXT,
    state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','revealed','caught','fled','ran')),
    attempt_ordinal INTEGER NOT NULL DEFAULT 0 CHECK(attempt_ordinal>=0),
    revision INTEGER NOT NULL DEFAULT 0,
    content_version TEXT NOT NULL,
    created_at REAL NOT NULL,
    resolved_at REAL,
    acknowledged_at REAL
);
CREATE INDEX encounters_profile_state_time ON encounters(profile_id,state,created_at);
CREATE TRIGGER encounter_queue_insert BEFORE INSERT ON encounters
WHEN NEW.state IN ('queued','revealed') AND
    (SELECT count(*) FROM encounters WHERE profile_id=NEW.profile_id AND state IN ('queued','revealed'))>=3
BEGIN SELECT RAISE(ABORT,'Encounter queue full'); END;
CREATE TRIGGER encounter_queue_update BEFORE UPDATE OF state,profile_id ON encounters
WHEN NEW.state IN ('queued','revealed') AND
    (SELECT count(*) FROM encounters WHERE profile_id=NEW.profile_id AND state IN ('queued','revealed')
     AND encounter_id<>OLD.encounter_id)>=3
BEGIN SELECT RAISE(ABORT,'Encounter queue full'); END;
CREATE TABLE catch_attempts (
    encounter_id TEXT NOT NULL REFERENCES encounters ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    ball TEXT NOT NULL,
    berry TEXT,
    p REAL NOT NULL CHECK(p BETWEEN 0 AND 1),
    success INTEGER NOT NULL CHECK(success IN (0,1)),
    fled INTEGER NOT NULL CHECK(fled IN (0,1)),
    receipt_key TEXT REFERENCES action_receipts(key) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(encounter_id,ordinal)
);
CREATE TABLE pokemon (
    pokemon_uid TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    pokemon_id INTEGER NOT NULL,
    level_x2 INTEGER NOT NULL CHECK(level_x2 BETWEEN 2 AND 80),
    iv_attack INTEGER NOT NULL CHECK(iv_attack BETWEEN 0 AND 15),
    iv_defense INTEGER NOT NULL CHECK(iv_defense BETWEEN 0 AND 15),
    iv_stamina INTEGER NOT NULL CHECK(iv_stamina BETWEEN 0 AND 15),
    gender TEXT NOT NULL CHECK(gender IN ('male','female','genderless')),
    shiny INTEGER NOT NULL CHECK(shiny IN (0,1)),
    origin TEXT NOT NULL CHECK(origin IN ('starter','catch')),
    source_encounter_id TEXT UNIQUE REFERENCES encounters ON DELETE SET NULL,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0,1)),
    state TEXT NOT NULL DEFAULT 'owned' CHECK(state IN ('owned','sent')),
    content_version TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    caught_at REAL NOT NULL
);
CREATE TABLE inventory (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>=0),
    PRIMARY KEY(profile_id,item_id)
);
CREATE TABLE candy (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    family_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>=0),
    PRIMARY KEY(profile_id,family_id)
);
CREATE TABLE pokedex (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    pokemon_id INTEGER NOT NULL,
    seen_at REAL NOT NULL,
    caught_at REAL,
    PRIMARY KEY(profile_id,pokemon_id)
);
CREATE TABLE reactions (
    message_id TEXT PRIMARY KEY NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    desired TEXT NOT NULL CHECK(desired IN ('add','remove')),
    actual TEXT NOT NULL DEFAULT 'none' CHECK(actual IN ('none','added')),
    revision INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE action_receipts (
    key TEXT PRIMARY KEY NOT NULL,
    action TEXT NOT NULL,
    result TEXT NOT NULL CHECK(json_valid(result)),
    created_at REAL NOT NULL
);
CREATE TABLE resource_ledger (
    receipt_key TEXT NOT NULL REFERENCES action_receipts(key) ON DELETE CASCADE,
    line_key INTEGER NOT NULL,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    resource TEXT NOT NULL,
    resource_id TEXT,
    delta INTEGER NOT NULL CHECK(typeof(delta)='integer'),
    reason TEXT NOT NULL,
    PRIMARY KEY(receipt_key,line_key)
);
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    profile_id TEXT REFERENCES profiles ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL,
    selection TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(selection))
);
