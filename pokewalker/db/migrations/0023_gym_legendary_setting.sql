-- D63 (owner decision 2026-11-12): servers choose whether Legendary/Mythical Pokemon may defend gyms.
ALTER TABLE guilds ADD COLUMN gym_legendary_defenders INTEGER NOT NULL DEFAULT 0
    CHECK(gym_legendary_defenders IN (0,1));
