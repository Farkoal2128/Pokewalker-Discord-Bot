-- Audit fix 2026-11-12: profile deletion cascades through these foreign keys. Without an
-- index each deleted parent row scans the whole child table inside the single writer.
CREATE INDEX catch_attempts_receipt ON catch_attempts(receipt_key);
CREATE INDEX gym_deployments_pokemon ON gym_deployments(pokemon_uid);
CREATE INDEX resource_ledger_profile ON resource_ledger(profile_id);
