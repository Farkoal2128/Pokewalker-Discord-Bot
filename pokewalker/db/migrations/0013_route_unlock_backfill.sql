UPDATE profiles
SET route_id='refreshing_field'
WHERE (SELECT coalesce(sum(awarded_c),0) FROM step_events
       WHERE step_events.profile_id=profiles.profile_id) < CASE route_id
    WHEN 'rugged_road' THEN 100000
    WHEN 'beautiful_beach' THEN 250000
    WHEN 'suburban_area' THEN 500000
    WHEN 'dim_cave' THEN 800000
    WHEN 'blue_lake' THEN 1200000
    WHEN 'volcano_path' THEN 1800000
    ELSE 0
END;
