-- ============================================================
-- ЖЁСТКАЯ ФИЛЬТРАЦИЯ — оставляем ТОЛЬКО:
-- DevOps / DevSecOps / SRE / MLOps / FinOps / DataOps
-- и их вариации написания (латиница, кириллица, слитно/раздельно)
-- Фильтрация ТОЛЬКО по названию вакансии (title)
-- ============================================================

-- ШАГ 1: Резервная копия
DROP TABLE IF EXISTS vacancies_backup;
CREATE TABLE vacancies_backup AS SELECT * FROM vacancies;

SELECT (SELECT count(*) FROM vacancies) AS total_before;

-- ШАГ 2: Очистка
DO $$
DECLARE

    -- Оставляем только вакансии, у которых title содержит хотя бы одно из:
    target TEXT := '('

        -- DevOps
        || 'devops'          -- devops, devops-инженер, devops engineer...
        || '|dev ops'        -- dev ops (через пробел)
        || '|девопс'         -- девопс
        || '|де ?воп'        -- девоп, де воп (опечатки/сокращения)

        -- DevSecOps
        || '|devsecops'
        || '|dev sec ops'
        || '|девсекопс'
        || '|девсек'

        -- SRE
        || '|\bsre\b'                  -- строго SRE как отдельное слово
        || '|site reliability'
        || '|site.reliability'
        || '|инженер по надежности'
        || '|инженер по обеспечению надежности'
        || '|инженер надежности'

        -- MLOps
        || '|mlops'
        || '|ml ops'
        || '|млопс'

        -- LLMOps (подмножество MLOps)
        || '|llmops'
        || '|llm ops'

        -- MLSecOps
        || '|mlsecops'
        || '|ml sec ops'

        -- FinOps
        || '|finops'
        || '|fin ops'
        || '|финопс'

        -- DataOps
        || '|dataops'
        || '|data ops'
        || '|датаопс'

    || ')';

    deleted_count BIGINT;
BEGIN

    WITH cleaned AS (
        SELECT
            id,
            regexp_replace(lower(title), '[^a-zа-я0-9 ]+', ' ', 'g') AS t
        FROM vacancies
    )
    DELETE FROM vacancies
    WHERE id IN (
        SELECT id FROM cleaned
        WHERE t !~ target
    );

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RAISE NOTICE '>>> Удалено вакансий: %', deleted_count;
END;
$$;

-- ШАГ 3: Итог
SELECT
    (SELECT count(*) FROM vacancies_backup) AS было,
    (SELECT count(*) FROM vacancies)        AS стало,
    (SELECT count(*) FROM vacancies_backup) - (SELECT count(*) FROM vacancies) AS удалено;


-- ============================================================
-- УТИЛИТЫ
-- ============================================================

/*
-- Посмотреть что осталось:
SELECT id, title FROM vacancies ORDER BY title;

-- Посмотреть что удалилось:
SELECT b.id, b.title
FROM vacancies_backup b
LEFT JOIN vacancies v ON b.id = v.id
WHERE v.id IS NULL
ORDER BY b.title;

-- Откат:
TRUNCATE vacancies;
INSERT INTO vacancies SELECT * FROM vacancies_backup;
*/