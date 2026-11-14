-- D64 (owner decision 2026-11-13): the Shiny Charm comes from the 100% Pokedex milestone
-- (milestone_awards 'pokedex:100'); players may switch it off. 0 means on.
ALTER TABLE profiles ADD COLUMN shiny_charm_off INTEGER NOT NULL DEFAULT 0
    CHECK(shiny_charm_off IN (0,1));
