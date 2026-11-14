ALTER TABLE arena_runs ADD COLUMN x_attack_left INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(x_attack_left)='integer' AND x_attack_left>=0);
ALTER TABLE arena_runs ADD COLUMN x_defense_left INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(x_defense_left)='integer' AND x_defense_left>=0);
