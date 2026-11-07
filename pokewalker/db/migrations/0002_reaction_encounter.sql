ALTER TABLE reactions ADD COLUMN encounter_id TEXT REFERENCES encounters ON DELETE CASCADE;
CREATE UNIQUE INDEX reactions_encounter ON reactions(encounter_id);
