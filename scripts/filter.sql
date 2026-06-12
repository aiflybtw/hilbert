-- ============================================================
-- filter.sql — Flag non-relevant entries and short descriptions
-- ============================================================
-- Step 1: Flag non-DevOps/SRE roles
-- Non-relevant roles include frontend, mobile, data scientist, QA, etc.
UPDATE vacancies
SET needs_review = true,
    review_reasons = COALESCE(review_reasons, '') || '; non-devops title'
WHERE title IS NOT NULL
  AND (
    -- Frontend
    lower(title) ~ '\b(frontend|front-end|front end|фронтенд)\b'
    -- Mobile
    OR lower(title) ~ '\b(ios|android|mobile|flutter|react native)\b'
    -- Data Science (not MLOps)
    OR lower(title) ~ '\bdata scientist\b'
    -- QA / Testing (not DevOps-related)
    OR lower(title) ~ '\b(qa|тестировщик|test engineer|auto.?test)\b'
    -- Design
    OR lower(title) ~ '\b(designer|ux|ui|дизайнер)\b'
    -- Management (non-technical)
    OR lower(title) ~ '\b(product manager|project manager|hr|recruiter|менеджер\s+проекта)\b'
    -- Backend-only (non-DevOps)
    OR lower(title) ~ '\b(backend|back-end|back end)'
      AND lower(title) !~ '\b(devops|sre|mlops)\b'
    -- 1C (non-infrastructure)
    OR lower(title) ~ '\b1с\b'
      AND lower(title) !~ '\b(devops|администрирование|инфраструктур)\b'
    -- Helpdesk / Support (not SRE)
    OR lower(title) ~ '\b(helpdesk|help desk|техподдержка|support engineer)\b'
      AND lower(title) !~ '\b(sre|devops)\b'
  );

-- Step 2: Flag very short descriptions (< 50 chars)
UPDATE vacancies
SET needs_review = true,
    review_reasons = COALESCE(review_reasons, '') || '; short description'
WHERE description IS NOT NULL
  AND length(trim(description)) < 50
  AND needs_review = false;

-- Step 3: Summary
SELECT
  (SELECT count(*) FROM vacancies) AS total,
  (SELECT count(*) FROM vacancies WHERE needs_review = true) AS flagged,
  (SELECT count(*) FROM vacancies WHERE needs_review = true
    AND review_reasons LIKE '%non-devops title%') AS flagged_title,
  (SELECT count(*) FROM vacancies WHERE needs_review = true
    AND review_reasons LIKE '%short description%') AS flagged_short_desc;
