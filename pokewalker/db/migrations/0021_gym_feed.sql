-- D62b (owner decision 2026-11-12): Razz Berry feeding heals the defender's hourly weakening.
-- heal_x10 is the stored feed total in tenths of the battle-HP factor (0.1x canonical HP); it never
-- exceeds the 7 hours of decay.
ALTER TABLE gym_deployments ADD COLUMN heal_x10 INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(heal_x10)='integer' AND heal_x10 BETWEEN 0 AND 7);
ALTER TABLE gym_deployments ADD COLUMN last_fed_at REAL;
