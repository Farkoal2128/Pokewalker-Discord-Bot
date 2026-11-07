ALTER TABLE profiles ADD COLUMN overflow_uid TEXT REFERENCES pokemon(pokemon_uid) ON DELETE SET NULL;
