# Локальный помощник «Листка»

Поиск по семи регламентам самовывоза, бонусов и хранения заказов. Проект содержит E5/Chroma-поиск, управление правилами, повторное использование результатов поиска и проверку цитат. Один документ имеет служебный доступ; исторический источник сохраняется в корпусе с отдельным статусом актуальности.

Python возвращает найденные фрагменты. ИИ с доступом к файлам и терминалу составляет ответ и запускает `finalize`. `ask` сам не генерирует ответ. Внешний API генерации и постоянно работающий сервер не нужны. Документы демонстрационные; локальная роль не заменяет аутентификацию.

## Состав проекта

- `rag_demo/` — код модели, документов, индекса, поиска, хранилища результатов и проверки цитат.
- `docs/`, `inventory.csv` — семь документов и состав корпуса.
- `behavior/` — параметры и системные правила; активна v2 с фильтрацией актуальных источников.
- `README.md`, `AGENTS.md`, `spec.md`, `rag-policy.md` — установка, инструкции ИИ, контракты и порядок ответа.
- `eval/eval-case.schema.json` — схема записей для оценки качества.
- `eval/inputs.json` — 12 исходных вопросов с идентификаторами и ролями, без ответов и оценок.
- `requirements*.txt` — зависимости Python.

При установке и запуске создаются `.venv/`, `models/`, `.cache/`, `.rag_store/`, `.query_cache/` и `evidence/`. Они исключены в `.gitignore` и не входят в исходный комплект.

## Windows x64: установка и запуск

Нужны 64-разрядный Python 3.13, PowerShell, интернет для первой установки и несколько гигабайт свободного места. Создайте локальную копию репозитория и откройте PowerShell в его основной папке, рядом с этим README. Короткий путь к проекту уменьшает риск ограничений длины путей при установке PyTorch.

1. Проверьте Python:

```powershell
py -3.13 --version
```

Если версии нет, установите её с [python.org](https://www.python.org/downloads/). При использовании Python Install Manager команды установки и проверки:

```powershell
pymanager install 3.13
pymanager exec -V:3.13 --version
```

2. Создайте окружение и установите зависимости:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import sys, platform; print(sys.version); print(platform.machine()); assert sys.version_info[:2] == (3, 13)"
```

Если старый launcher `py` не видит установленную версию, для создания окружения используйте `pymanager exec -V:3.13 -m venv .venv`. Активация окружения не нужна. `pip check` должен сообщить `No broken requirements found.`

3. Загрузите модель, проверьте документы и создайте индекс:

```powershell
.\.venv\Scripts\python.exe -m rag_demo prepare-model
.\.venv\Scripts\python.exe -m rag_demo validate-docs
.\.venv\Scripts\python.exe -m rag_demo index
.\.venv\Scripts\python.exe -m rag_demo policy show
```

Ожидаются `model_ready`, `documents_valid`, `indexed`, семь документов, 19 фрагментов и размерность 768. Активная политика — v2, `filter_current_sources=true`.

4. Замените текст-заполнитель своим вопросом и выполните поиск:

```powershell
.\.venv\Scripts\python.exe -m rag_demo ask --question 'ВАШ ВОПРОС' --role customer --top-k 8
```

Путь к новому результату выводится при запуске. Без `--output` имя файла выбирается автоматически и не перезаписывает историю.

## macOS Apple Silicon: установка и запуск

Поддерживаются M1 и новее, Python arm64, CPU. Файл `requirements-macos.txt` не предназначен для Mac с Intel. Откройте Terminal в папке проекта. Проверьте `uname -m`: ожидается arm64; на Apple Silicon не запускайте Terminal через Rosetta.

1. Установите Python 3.13 через [Homebrew](https://brew.sh/):

```bash
brew install python@3.13
"$(brew --prefix python@3.13)/bin/python3.13" --version
```

2. Создайте окружение и установите зависимости:

```bash
"$(brew --prefix python@3.13)/bin/python3.13" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-macos.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'import sys, platform; print(sys.version); print(platform.machine()); assert sys.version_info[:2] == (3, 13); assert platform.machine() == "arm64"'
```

3. Загрузите модель, создайте индекс и выполните поиск со своим вопросом:

```bash
.venv/bin/python -m rag_demo prepare-model
.venv/bin/python -m rag_demo validate-docs
.venv/bin/python -m rag_demo index
.venv/bin/python -m rag_demo policy show
.venv/bin/python -m rag_demo ask --question 'ВАШ ВОПРОС' --role customer --top-k 8
```

Результаты подготовки такие же, как на Windows. После первого запуска модель и индекс сохраняются; повторно загружать и создавать их перед каждым вопросом не нужно.

## Локальная модель и загрузка с Hugging Face

Используется [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base), размерность 768, нормализация векторов и префиксы `passage: ` / `query: `. Штатная команда загрузки — `prepare-model`. Дальнейшие команды используют только локальные файлы.

Для ручной загрузки:

1. Откройте [Files and versions](https://huggingface.co/intfloat/multilingual-e5-base/tree/main).
2. В проекте создайте `models/multilingual-e5-base/`, внутри неё — `1_Pooling/`.
3. Откройте и скачайте каждый файл из списка ниже. Сохраняйте файл, а не HTML страницы, без смены расширения.
4. Файл `1_Pooling/config.json` положите в `1_Pooling/`; остальные — в корень папки модели. Все файлы должны происходить из одной версии репозитория.
5. Выполните `index`; неполный набор файлов будет отклонён с перечнем недостающих имён.

```text
models/multilingual-e5-base/
├── config.json
├── model.safetensors
├── modules.json
├── sentence_bert_config.json
├── tokenizer.json
├── tokenizer_config.json
├── special_tokens_map.json
├── sentencepiece.bpe.model
├── README.md
└── 1_Pooling/
    └── config.json
```

Готовую папку модели можно перенести из другого экземпляра этого проекта, если совпадают модель и все файлы. Переносите собственное окружение только в поддерживаемой ОС; для другой ОС устанавливайте её requirements. После изменения документов или модели создайте индекс в текущем проекте.

## Работа с ИИ

Откройте папку в среде, где ИИ умеет читать и создавать файлы и выполнять команды. Для установки поручите ему прочитать `AGENTS.md` и README. Перед вопросами — `rag-policy.md` и текущие системные правила из `policy show`.

ИИ самостоятельно выполняет `ask`, читает новый результат, составляет ответ, сохраняет исходный ответ и запускает `finalize`. Человеку не нужно переносить JSON между терминалом и чатом. Каждому ответу соответствуют собственные файлы и идентификаторы. Вопрос, роль, найденные фрагменты и режим получения результата сохраняются в истории.

Исходный ответ содержит ровно `answer`, `citations`, `decision`. У цитаты три поля: `document_id`, `chunk_id`, `quote`. Цитата должна быть дословной частью текущего найденного фрагмента. Допустимые решения v2: `answer`, `clarify`, `refuse`, `escalate`. `finalize` проверяет структуру и происхождение цитат, но правильность вывода оценивается отдельно.

## Повторное использование и очистка результатов поиска

При повторном запросе проект может получить сохранённые фрагменты вместо нового вычисления вектора и поиска. Готовые ответы не сохраняются для повторной выдачи. Поле `search_execution.mode` имеет значение `fresh_search` или `cached_results`. Время `search_elapsed_ms` относится только к получению фрагментов после проверки индекса.

Для Windows:

```powershell
.\.venv\Scripts\python.exe -m rag_demo cache status
.\.venv\Scripts\python.exe -m rag_demo ask --question 'ВАШ ВОПРОС' --role customer --no-cache
.\.venv\Scripts\python.exe -m rag_demo cache clear
```

Для macOS:

```bash
.venv/bin/python -m rag_demo cache status
.venv/bin/python -m rag_demo ask --question 'ВАШ ВОПРОС' --role customer --no-cache
.venv/bin/python -m rag_demo cache clear
```

`--no-cache` не читает и не заполняет хранилище. `cache clear` сохраняет старые доказательства в `evidence/`. Для сравнения нескольких запусков фиксируйте последовательность запросов, роли и фактический режим получения фрагментов.

## Вопросы для проверки качества

В `eval/inputs.json` находится список `inputs` из 12 обращений. У каждого три поля: `case_id`, `question` и `role`. Эти обращения можно использовать для сопоставления поиска с сохранёнными результатами и без них. Файл содержит только входные данные; ожидаемые результаты и оценки определяются отдельно до запуска.

ИИ читает список и выполняет вопросы по одному через `ask`, используя точный текст и роль. Программа `ask` не читает этот файл автоматически. Для каждого обращения ИИ сохраняет отдельный ответ и запускает `finalize`. При повторных обращениях сохраняются новые файлы и их порядок.

Для контрольного прогона используется `--no-cache`. Затем тот же набор можно проверить с включённым повторным использованием результатов. Режим и начальное состояние хранилища фиксируются в отчёте. Успех одного режима не означает успех другого.

Для оформления ожиданий используется схема `eval/eval-case.schema.json`: значение входного `role` переносится в `user_role`. Исходный список вопросов сохраняется; расширенные наборы и отчёты записываются отдельно.

## Команды

| Команда | Назначение |
| --- | --- |
| `prepare-model` | Скачать и проверить модель |
| `validate-docs` | Проверить документы и inventory |
| `chunks` | Сохранить структурные фрагменты |
| `index` | Создать сохранённый индекс |
| `policy show` / `policy use --version v2` | Проверить или выбрать правила |
| `ask` / `retrieve` | Получить фрагменты по вопросу |
| `cache status` / `cache clear` | Проверить или очистить сохранённые результаты поиска |
| `finalize --retrieval evidence/ИМЯ.retrieval.json --answer-file evidence/ИМЯ.raw.json` | Проверить новый ответ и сохранить результат |

У `ask` можно задать `--output evidence/ИМЯ.retrieval.json`. Имя должно быть новым. Успешный `finalize` создаёт result, историю поиска и ответа и citation-map; ошибка возвращает ненулевой код. Менять старые файлы, чтобы выдать их за новый запуск, нельзя.
