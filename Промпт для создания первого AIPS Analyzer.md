# AIPS Analyzer — Prototype v0.1

Нужно создать отдельный standalone-проект `aips-analyzer` для автоматического обследования существующих программных проектов.

## Главная цель текущего этапа

Сделать **первый работающий deterministic analyzer** и проверить его на существующем проекте:

`freelance_pulse`

На этом этапе **НЕ создавать Flask UI и НЕ подключать AI**.

Нам нужно сначала получить реальный структурированный файл:

`evidence.json`

и проверить, насколько хорошо Analyzer способен объективно описать проект.

---

# 1. Важные архитектурные правила

`aips-analyzer` должен быть отдельным проектом и не должен изменять исходный `freelance_pulse`.

Архитектура должна быть примерно такой:

```text
aips-analyzer/
├── aips_analyzer/
│   ├── __init__.py
│   ├── analyzer.py
│   ├── models.py
│   ├── evidence.py
│   └── analyzers/
│       ├── __init__.py
│       ├── discovery.py
│       ├── technology.py
│       ├── repository.py
│       ├── dependencies.py
│       ├── git.py
│       └── architecture.py
├── tests/
├── output/
├── pyproject.toml
└── README.md
```

Допускается немного изменить структуру, если это архитектурно оправдано, но:

- engine должен быть отделён от CLI;
- analyzers должны быть отдельными модулями;
- результат должен быть структурированным JSON;
- проект должен быть расширяемым;
- не создавать монолитный скрипт на 1000 строк.

---

# 2. Не использовать AI

Первый прототип должен быть полностью deterministic.

НЕ использовать:

- OpenAI;
- Claude;
- Gemini;
- OpenRouter;
- Ollama;
- LLM;
- embeddings;
- AI classification.

Причина: сначала мы хотим увидеть **чистые факты о проекте**, не интерпретацию модели.

---

# 3. Не создавать Flask

Flask будет следующим уровнем системы.

Сейчас нужен только Analyzer Engine + CLI.

CLI является временным способом запуска и тестирования engine.

В будущем архитектура должна позволять использовать тот же engine из:

```text
CLI
Flask
Celery
API
```

Например концептуально:

```python
result = analyze_project("/path/to/project")
```

CLI только вызывает этот engine.

---

# 4. Первый запуск

Analyzer должен уметь запускаться примерно так:

```bash
python -m aips_analyzer /path/to/freelance_pulse
```

или через удобную CLI-команду:

```bash
aips-analyze /path/to/freelance_pulse
```

Можно поддержать оба варианта.

Результат должен сохраняться, например:

```text
output/
└── freelance_pulse/
    ├── evidence.json
    └── run.log
```

Путь должен быть удобным для последующего анализа.

---

# 5. Analyzer №1 — Discovery

Определить структуру проекта.

Нужно собрать как минимум:

- project root;
- количество файлов;
- количество директорий;
- типы файлов;
- Python files;
- HTML/templates;
- CSS;
- JavaScript;
- JSON;
- YAML/YML;
- Markdown;
- SQL;
- migrations;
- tests;
- configuration files.

Обязательно исключать из статистики:

```text
.git
.venv
venv
env
node_modules
__pycache__
.pytest_cache
.mypy_cache
.ruff_cache
coverage
dist
build
```

Список исключений должен быть централизованным и расширяемым.

Не считать файлы из `.git`.

---

# 6. Analyzer №2 — Technology Detection

Попытаться deterministic-способом определить:

### Language

Например:

```json
"languages": {
  "Python": 184,
  "JavaScript": 27,
  "HTML": 47,
  "CSS": 12
}
```

### Frameworks

Искать подтверждения через:

- pyproject.toml;
- requirements.txt;
- requirements/*.txt;
- package.json;
- imports;
- характерные configuration files;
- directory structure.

Для `freelance_pulse` ожидается возможность обнаружить как минимум:

- Python;
- Django;
- PostgreSQL-related tooling;
- Celery;
- pytest;
- HTMX, если имеются объективные признаки.

Но **не подставлять ожидаемые значения вручную**.

Каждое обнаружение должно иметь evidence/source.

Например:

```json
{
  "name": "Django",
  "detected": true,
  "confidence": 1.0,
  "sources": [
    "pyproject.toml",
    "manage.py",
    "django imports"
  ]
}
```

---

# 7. Analyzer №3 — Repository Metrics

Собрать объективные метрики:

- total files;
- total lines;
- code lines;
- comment lines, если возможно;
- blank lines;
- Python LOC;
- JS LOC;
- HTML LOC;
- CSS LOC;
- number of modules;
- number of packages;
- number of Django apps;
- number of templates;
- number of migrations;
- number of test files.

Не пытаться сейчас оценивать качество.

Только измеряем.

---

# 8. Analyzer №4 — Dependencies

Проанализировать зависимости.

Поддержать как минимум:

### Python

Искать:

```text
pyproject.toml
requirements.txt
requirements/*.txt
Pipfile
Pipfile.lock
poetry.lock
uv.lock
```

### Node

Искать:

```text
package.json
package-lock.json
pnpm-lock.yaml
yarn.lock
```

Нужно определить:

- production dependencies;
- development dependencies;
- количество зависимостей;
- lockfile presence;
- package manager;
- версии, если доступны.

Не устанавливать зависимости проекта на этом этапе.

**Важно: не выполнять код проекта.**

---

# 9. Analyzer №5 — Git

Если директория является Git repository, собрать:

- current branch;
- HEAD commit;
- number of commits;
- number of branches;
- first commit date, если доступно;
- latest commit date;
- contributors count, если возможно;
- modified files;
- deleted files;
- basic commit activity;
- top changed files;
- basic churn metrics, если их можно получить безопасно.

Использовать Git CLI read-only.

Не делать:

```text
git checkout
git pull
git reset
git clean
git commit
```

Analyzer не должен менять repository.

Если Git отсутствует — не падать.

Возвращать:

```json
"git": {
  "available": false
}
```

---

# 10. Analyzer №6 — Basic Architecture

Это особенно важно.

Нужно попробовать построить **объективную карту архитектуры**, но пока без LLM.

Для Python:

- packages;
- modules;
- imports;
- internal imports;
- external imports;
- Django apps;
- services;
- API modules;
- models;
- views;
- URLs;
- management commands;
- Celery tasks;
- tests.

Использовать Python AST.

Не исполнять Python-код.

Попробовать определить зависимости между внутренними модулями:

```text
core → services
marketplace → services
api → core
...
```

И найти:

- циклические зависимости;
- modules with very high fan-in;
- modules with very high fan-out;
- unusually large modules.

На этом этапе это **candidate architecture evidence**, а не окончательный архитектурный verdict.

Например:

```json
{
  "cycles": [
    ["module_a", "module_b", "module_a"]
  ]
}
```

---

# 11. Evidence model

Очень важно: Analyzer не должен сразу выдавать субъективные conclusions.

Нужна концепция:

```text
Evidence → Metrics → Candidate Findings
```

На текущем этапе реализовать прежде всего:

```text
Evidence
Metrics
```

Candidate Findings можно реализовать только там, где факт определяется однозначно.

Каждое evidence желательно иметь идентификатор:

```text
E-001
E-002
E-003
...
```

Например:

```json
{
  "id": "E-001",
  "type": "technology",
  "source": "pyproject.toml",
  "subject": "Django",
  "value": {
    "version": "5.2.10"
  }
}
```

Или:

```json
{
  "id": "E-014",
  "type": "repository_metric",
  "source": "filesystem",
  "subject": "python_files",
  "value": 184
}
```

---

# 12. Итоговый JSON

Создать версионированный формат:

```json
{
  "schema": "aips-evidence/v1",
  "analyzer": {
    "name": "aips-analyzer",
    "version": "0.1.0"
  },
  "project": {},
  "discovery": {},
  "technology": {},
  "repository": {},
  "dependencies": {},
  "git": {},
  "architecture": {},
  "evidence": [],
  "metrics": [],
  "warnings": []
}
```

Не надо пытаться сделать идеальную схему сейчас.

Главное:

**JSON должен быть стабильным, понятным и расширяемым.**

---

# 13. Evidence provenance

Для важных обнаружений обязательно сохранять источник.

Например:

```json
{
  "id": "E-003",
  "type": "dependency",
  "subject": "django",
  "value": "5.2.10",
  "source": {
    "file": "pyproject.toml",
    "section": "dependencies"
  }
}
```

Это необходимо потому, что в дальнейшем AI должен получать не просто:

> Django 5.2.10

а:

> Django 5.2.10 найден в pyproject.toml → dependencies.

---

# 14. Ошибки

Один сломанный analyzer не должен останавливать весь анализ.

Например:

```text
Git analyzer failed
```

не должен приводить к полному failure.

Результат:

```json
"warnings": [
  {
    "analyzer": "git",
    "error": "...",
    "recoverable": true
  }
]
```

И остальные analyzers продолжают работу.

---

# 15. Безопасность

Очень важно.

На этом этапе Analyzer **не должен выполнять произвольный код анализируемого проекта**.

НЕ делать:

```bash
python setup.py
pip install -r requirements.txt
npm install
npm run build
pytest
manage.py
```

и любые другие команды, которые могут исполнять код проекта.

Разрешены:

- чтение файлов;
- Python AST parsing;
- JSON/TOML/YAML parsing;
- filesystem traversal;
- read-only Git commands.

Позже выполнение проекта будет происходить только внутри sandbox.

---

# 16. Tests

Создать unit tests для engine и основных analyzers.

Минимально проверить:

- discovery;
- technology;
- dependencies;
- Git handling;
- architecture AST;
- exclusions;
- malformed files;
- missing files;
- non-Git directory;
- analyzer failure isolation.

Создать маленький fixture project для тестов.

Не использовать весь `freelance_pulse` как unit-test fixture.

---

# 17. README

README должен объяснить:

1. Что такое AIPS Analyzer.
2. Что он анализирует.
3. Что он НЕ делает.
4. Как запустить.
5. Как выглядит output.
6. Architecture.
7. Safety limitations.
8. Future integration with Flask.

Отдельно написать:

```text
Current version does not use AI.
Current version does not execute analyzed project code.
Current version does not provide a web UI.
```

---

# 18. После реализации

Не просто написать код и остановиться.

Нужно:

### Step 1

Проверить:

```bash
python -m compileall ...
```

### Step 2

Запустить unit tests.

### Step 3

Проверить CLI.

### Step 4

Запустить Analyzer непосредственно на:

```text
freelance_pulse
```

### Step 5

Получить:

```text
output/freelance_pulse/evidence.json
```

### Step 6

Показать в терминале краткую сводку:

```text
AIPS Analyzer 0.1.0

Project: freelance_pulse

Files: ...
Python files: ...
Django apps: ...
Dependencies: ...
Tests detected: ...
Git commits: ...
Architecture modules: ...
Warnings: ...

Evidence: output/freelance_pulse/evidence.json
```

---

# 19. Очень важное ограничение

НЕ исправлять найденные проблемы в `freelance_pulse`.

НЕ рефакторить `freelance_pulse`.

НЕ добавлять туда AIPS Analyzer.

НЕ создавать `.ai` файлы в `freelance_pulse`.

НЕ менять его dependencies.

НЕ менять его settings.

Analyzer должен только читать проект.

---

# 20. Финальный отчёт после запуска

После завершения работы НЕ ограничивайся сообщением:

> Done.

Сообщи:

### A. Что создано

Список файлов/модулей.

### B. Что проверено

Команды и результаты.

### C. Где находится JSON

Точный относительный путь.

### D. Краткая статистика

Что Analyzer реально обнаружил в `freelance_pulse`.

### E. Проблемы Analyzer

Что не удалось определить или что требует улучшения.

### F. Пример структуры `evidence.json`

Покажи первые/важные части JSON, но не вставляй огромный файл целиком.

### G. Архитектурные наблюдения

Отдельно перечисли, какие данные уже можно использовать для будущего AIPS Audit, а каких данных пока недостаточно.

---

## Ключевой принцип проекта

Не пытайся сделать сейчас "умный AI-аудитор".

Сначала сделай:

```text
REAL PROJECT
     ↓
DETERMINISTIC ANALYZERS
     ↓
RAW EVIDENCE
     ↓
STRUCTURED JSON
```

Нам сейчас нужно проверить именно этот фундамент.

После получения `evidence.json` дальнейшую архитектуру будем принимать **по фактическому результату**, а не заранее придумывать поля и выводы.