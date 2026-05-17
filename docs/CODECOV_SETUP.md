# Настройка Codacy Coverage для RozittaParser

## Что это даёт

После настройки каждый push/PR будет автоматически отправлять покрытие тестов на [codacy.com](https://codacy.com). Вы увидите:
- Общий % покрытия кода тестами
- Покрытие по каждому файлу
- Изменение покрытия в PR (покрытие выросло/упало)
- Бейдж для README: ![Coverage](https://img.shields.io/badge/coverage-58%25-yellow)

**Codacy бесплатен для public-репозиториев.**

---

## Шаг 1 — Регистрация на Codacy (2 минуты)

1. Откройте https://www.codacy.com
2. Нажмите **Sign up** → выберите **Continue with GitHub**
3. Разрешите доступ к вашим репозиториям (можно только один)

## Шаг 2 — Добавление репозитория (1 минута)

1. В дашборде Codacy нажмите **Add project**
2. Выберите **Nynchezyabka/RozittaParser**
3. Codacy начнёт анализ кода (займёт несколько минут)

## Шаг 3 — Получение токена (1 минута)

1. Откройте репозиторий на Codacy
2. Перейдите в **Settings → Integrations**
3. В разделе **Project API** нажмите **Generate token** (или скопируйте существующий)
4. Скопируйте значение — это ваш `CODACY_PROJECT_TOKEN`

> **Важно:** Токен даёт доступ только к отправке данных покрытия, не к коду. Но всё равно не публикуйте его открыто.

## Шаг 4 — Добавление токена в GitHub (1 минута)

1. Откройте https://github.com/Nynchezyabka/RozittaParser/settings/secrets/actions
2. Нажмите **New repository secret**
3. Name: `CODACY_PROJECT_TOKEN`
4. Value: вставьте токен из шага 3
5. Нажмите **Add secret**

## Шаг 5 — Проверка

1. Сделайте merge PR #83 (или любой push в main)
2. Откройте https://github.com/Nynchezyabka/RozittaParser/actions
3. Найдите последний запуск workflow **Tests**
4. В логах Ubuntu-раннера должны быть:
   - Шаг **"Run tests with coverage (Linux)"** — в конце таблица покрытия
   - Шаг **"Upload coverage to Codacy"** — сообщение об успешной загрузке
5. Через 1–2 минуты откройте репозиторий на Codacy → вкладка **Coverage**

## Бейдж в README (опционально)

После появления данных на Codacy можно добавить бейдж в `README.md`:

```markdown
[![Coverage](https://app.codacy.com/project/badge/Coverage/<project-id>)](https://www.codacy.com/gh/Nynchezyabka/RozittaParser/dashboard?utm_source=github.com&utm_medium=referral&utm_content=Nynchezyabka/RozittaParser&utm_campaign=Badge_Coverage)
```

Ссылку с вашим `<project-id>` можно взять на Codacy: **Settings → Badges**.

---

## Решение проблем

| Проблема | Решение |
|----------|---------|
| Шаг Codacy пропущен (skipped) | Токен не добавлен в GitHub Secrets |
| "Commit not found" на Codacy | Подождать 5–10 мин, Codacy синхронизируется |
| "Branch not enabled" | Включить ветку в Settings → Analysis на Codacy |
| Coverage = 0% | Проверить что `coverage.xml` генерируется (посмотреть лог CI) |
| Токен не работает | Перегенерировать токен на Codacy и обновить секрет |

## Что изменилось в CI

**Было:** pytest запускался 3 раза (Linux + Windows + отдельный шаг coverage)

**Стало:** pytest запускается 2 раза (Linux с coverage + Windows без coverage), XML автоматически загружается в Codacy
