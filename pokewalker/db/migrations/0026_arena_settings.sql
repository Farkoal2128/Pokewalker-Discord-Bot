ALTER TABLE profiles ADD COLUMN arena_stop_pct INTEGER NOT NULL DEFAULT 50
    CHECK(arena_stop_pct IN (10,20,30,40,50,60,70,80,90));
ALTER TABLE profiles ADD COLUMN arena_auto_order INTEGER NOT NULL DEFAULT 0
    CHECK(arena_auto_order IN (0,1));
