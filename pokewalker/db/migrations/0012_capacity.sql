ALTER TABLE profiles ADD COLUMN storage_limit INTEGER NOT NULL DEFAULT 250
    CHECK(typeof(storage_limit)='integer' AND storage_limit BETWEEN 250 AND 1000);
ALTER TABLE profiles ADD COLUMN bag_limit INTEGER NOT NULL DEFAULT 250
    CHECK(typeof(bag_limit)='integer' AND bag_limit BETWEEN 250 AND 1000);
