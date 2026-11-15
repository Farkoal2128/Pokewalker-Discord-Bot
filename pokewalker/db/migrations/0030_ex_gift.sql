CREATE TABLE ex_gifts (
    gift_id TEXT PRIMARY KEY NOT NULL,
    owner_id TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('all','server','user')),
    guild_id TEXT CHECK((scope='all')=(guild_id IS NULL)),
    items TEXT NOT NULL CHECK(json_valid(items) AND json_array_length(items) BETWEEN 1 AND 10),
    servers INTEGER NOT NULL CHECK(typeof(servers)='integer' AND servers>=0),
    servers_with_recipients INTEGER NOT NULL
        CHECK(typeof(servers_with_recipients)='integer' AND servers_with_recipients>=0),
    recipients INTEGER NOT NULL CHECK(typeof(recipients)='integer' AND recipients>=1),
    created_at REAL NOT NULL
);
CREATE INDEX ex_gifts_created_at ON ex_gifts(created_at);

CREATE TABLE ex_gift_recipients (
    gift_id TEXT NOT NULL REFERENCES ex_gifts ON DELETE CASCADE,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    claimed_at REAL,
    PRIMARY KEY(gift_id,profile_id)
);
CREATE INDEX ex_gift_recipients_profile_claimed ON ex_gift_recipients(profile_id,claimed_at);

CREATE TABLE ex_items (
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    item_id TEXT NOT NULL CHECK(item_id IN ('time_gear_fragment','shiny_patch','golden_bottlecap',
                                          'ex_attack','ex_defense','arena_ex_voucher')),
    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity>=0),
    PRIMARY KEY(profile_id,item_id)
);

ALTER TABLE profiles ADD COLUMN ex_attack_armed INTEGER NOT NULL DEFAULT 0 CHECK(ex_attack_armed IN (0,1));
ALTER TABLE profiles ADD COLUMN ex_defense_armed INTEGER NOT NULL DEFAULT 0 CHECK(ex_defense_armed IN (0,1));
ALTER TABLE arena_runs ADD COLUMN ex_attack INTEGER NOT NULL DEFAULT 0 CHECK(ex_attack IN (0,1));
ALTER TABLE arena_runs ADD COLUMN ex_defense INTEGER NOT NULL DEFAULT 0 CHECK(ex_defense IN (0,1));

CREATE TABLE inbox_items_new (
    inbox_id INTEGER PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles ON DELETE CASCADE,
    milestone_id TEXT NOT NULL,
    resource TEXT NOT NULL CHECK(resource IN ('item','stardust','candy','arena_ticket')),
    resource_id TEXT,
    remaining INTEGER NOT NULL CHECK(typeof(remaining)='integer' AND remaining>=0),
    created_at REAL NOT NULL
);
INSERT INTO inbox_items_new SELECT * FROM inbox_items;
DROP TABLE inbox_items;
ALTER TABLE inbox_items_new RENAME TO inbox_items;
CREATE INDEX inbox_items_profile_id ON inbox_items(profile_id);
