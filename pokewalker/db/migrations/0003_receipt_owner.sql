ALTER TABLE action_receipts ADD COLUMN profile_id TEXT REFERENCES profiles ON DELETE CASCADE;
CREATE INDEX action_receipts_profile_id ON action_receipts(profile_id);

UPDATE action_receipts SET profile_id = COALESCE(
    (SELECT profile_id FROM resource_ledger WHERE receipt_key = action_receipts.key LIMIT 1),
    (SELECT profile_id FROM encounters
     WHERE action_receipts.key LIKE 'throw:' || encounter_id || ':%'
        OR action_receipts.key LIKE 'run:' || encounter_id || ':%' LIMIT 1),
    (SELECT profile_id FROM profiles
     WHERE action_receipts.key = 'enroll:' || guild_id || ':' || user_id LIMIT 1)
);

-- RAISE is legal only inside a trigger; an unknown action must roll back the migration.
CREATE TEMP TRIGGER reject_unattributable_receipt BEFORE DELETE ON action_receipts
WHEN OLD.profile_id IS NULL AND OLD.action NOT IN ('enroll', 'throw', 'run')
BEGIN
    SELECT RAISE(ABORT, 'unattributable receipt action');
END;
DELETE FROM action_receipts WHERE profile_id IS NULL;
DROP TRIGGER reject_unattributable_receipt;
