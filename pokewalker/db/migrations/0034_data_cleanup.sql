-- D74 (owner 2026-11-17): lifetime counters survive the cleanup of their source rows, and
-- the cleanup sweep and research auto-send read indexes instead of scanning.
ALTER TABLE profiles ADD COLUMN catch_total INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(catch_total)='integer' AND catch_total>=0);
ALTER TABLE profiles ADD COLUMN steps_total_c INTEGER NOT NULL DEFAULT 0
    CHECK(typeof(steps_total_c)='integer' AND steps_total_c>=0);
UPDATE profiles SET
    catch_total=(SELECT count(*) FROM catch_attempts a JOIN encounters e USING(encounter_id)
                 WHERE e.profile_id=profiles.profile_id AND a.success=1),
    steps_total_c=(SELECT coalesce(sum(awarded_c),0) FROM step_events
                   WHERE step_events.profile_id=profiles.profile_id);
CREATE INDEX encounters_resolved ON encounters(resolved_at);
CREATE INDEX encounters_unclaimed ON encounters(resolved_at) WHERE state='caught' AND acknowledged_at IS NULL;
CREATE INDEX gym_battles_created ON gym_battles(created_at);
CREATE INDEX step_events_created ON step_events(created_at);
