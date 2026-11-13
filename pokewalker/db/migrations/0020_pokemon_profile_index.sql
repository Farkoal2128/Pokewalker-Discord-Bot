-- Audit fix 2026-11-12: storage counts and listings filter by owner on every throw.
CREATE INDEX pokemon_profile_state ON pokemon(profile_id,state);
