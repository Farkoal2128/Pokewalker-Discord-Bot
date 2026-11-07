ALTER TABLE pokemon ADD COLUMN form_id INTEGER CHECK(form_id IS NULL OR (typeof(form_id)='integer' AND form_id>0));
