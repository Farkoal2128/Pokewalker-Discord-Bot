CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY NOT NULL,
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    initiator_profile_id TEXT NOT NULL,
    partner_profile_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','completed','cancelled','expired')),
    revision INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL CHECK(expires_at>created_at),
    ended_at REAL,
    UNIQUE(trade_id,guild_id),
    FOREIGN KEY(initiator_profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE,
    FOREIGN KEY(partner_profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
CREATE TABLE trade_sides (
    trade_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    side INTEGER NOT NULL CHECK(side IN (0,1)),
    profile_id TEXT NOT NULL,
    joined_at REAL,
    pokemon_uid TEXT,
    pokemon_revision INTEGER,
    confirmed_revision INTEGER,
    open INTEGER NOT NULL DEFAULT 0 CHECK(open IN (0,1)),
    CHECK(open=0 OR joined_at IS NOT NULL),
    PRIMARY KEY(trade_id,side),
    UNIQUE(trade_id,profile_id),
    FOREIGN KEY(trade_id,guild_id) REFERENCES trades(trade_id,guild_id) ON DELETE CASCADE,
    FOREIGN KEY(profile_id,guild_id) REFERENCES profiles(profile_id,guild_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX trade_sides_one_open ON trade_sides(profile_id) WHERE open=1;
CREATE TABLE trade_channels (
    guild_id TEXT NOT NULL REFERENCES guilds ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    PRIMARY KEY(guild_id,channel_id)
);
ALTER TABLE profiles ADD COLUMN last_trade_at REAL;
ALTER TABLE profiles ADD COLUMN last_trade_ping_at REAL;
CREATE TRIGGER trade_close_sides AFTER UPDATE OF state ON trades
WHEN NEW.state<>'open'
BEGIN UPDATE trade_sides SET open=0 WHERE trade_id=NEW.trade_id; END;
CREATE TRIGGER pokemon_trade_guard BEFORE UPDATE OF profile_id ON pokemon
WHEN NEW.profile_id IS NOT OLD.profile_id AND (OLD.state<>'owned' OR OLD.favorite<>0
    OR OLD.gym_deployment_id IS NOT NULL
    OR EXISTS (SELECT 1 FROM profiles WHERE companion_uid=OLD.pokemon_uid)
    OR (SELECT guild_id FROM profiles WHERE profile_id=OLD.profile_id)
       IS NOT (SELECT guild_id FROM profiles WHERE profile_id=NEW.profile_id))
BEGIN SELECT RAISE(ABORT,'Pokemon is not tradable'); END;
