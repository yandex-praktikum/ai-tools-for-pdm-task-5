# Локальный RAG-помощник «Листка»

Проект ищет сведения в регламентах сервиса доставки продуктов «Листок»: о заказах, заменах, возврате денег, оплате и работе поддержки. В `docs/` находятся 12 демонстрационных документов; состав корпуса задаёт `inventory.csv`.

Python создаёт локальный индекс и выполняет семантический поиск. ИИ с доступом к терминалу и файлам проекта читает найденные фрагменты, составляет ответ с цитатами и запускает проверку источников. Правила этого маршрута находятся в `rag-policy.md`.

`ask` и `retrieve` возвращают **результат поиска**, а не готовый ответ. `finalize` проверяет происхождение цитат и сохраняет результат. Смысловую связь между утверждениями и цитатами нужно оценивать отдельно.

## Что находится в проекте

- `rag_demo/` — код загрузки документов, работы с моделью, индекса, поиска и проверки цитат.
- `docs/`, `inventory.csv`, `corpus-passport.md` — документы и описание корпуса.
- `requirements.txt` и `requirements-windows.txt` / `requirements-macos.txt` — зависимости.
- `spec.md` — технические требования.
- `AGENTS.md` — инструкции ИИ для установки и обслуживания проекта.
- `rag-policy.md` — правила обработки вопросов.

Во время установки и первого запуска создаются `.venv/`, `models/`, `.cache/`, `.rag_store/` и `evidence/`. Эти каталоги не входят в исходный комплект и исключены в `.gitignore`.

## Перед установкой

Нужны обычный 64-разрядный Python **3.13**, доступ к интернету для установки зависимостей и первой загрузки модели, несколько гигабайт свободного места.

Конфигурации:

- **Windows x64**, PowerShell, CPU-версия PyTorch.
- **macOS на Apple Silicon** (M1 и новее), Terminal, Python arm64. Вычисления также выполняются на CPU.

Инструкция macOS рассчитана на Apple Silicon. Для Mac с Intel нужен другой набор совместимых версий Python и PyTorch; `requirements-macos.txt` для него не предназначен.

Скачайте или распакуйте проект. Откройте терминал **в папке с этим README**, `inventory.csv` и каталогом `rag_demo`. На Windows выбирайте короткий путь к папке: глубокие вложенные каталоги могут мешать установке PyTorch.

## Установка и первый запуск на Windows

### 1. Установите Python 3.13

Проверьте доступность нужной версии:

~~~powershell
py -3.13 --version
~~~

Если её нет, установите [Python Install Manager](https://www.python.org/downloads/) по [официальной инструкции](https://docs.python.org/3/using/windows.html). Откройте новое окно PowerShell и выполните:

~~~powershell
pymanager install 3.13
pymanager exec -V:3.13 --version
~~~

`pymanager` позволяет установить нужную версию даже при наличии старого launcher `py`. В выводе проверки должна быть версия `Python 3.13.x`.

### 2. Создайте окружение и установите зависимости

Все следующие команды выполняйте из корня проекта:

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv\Scripts\python.exe -m pip check
~~~

Успешная проверка выводит `No broken requirements found.` Активация окружения не требуется: команды используют его интерпретатор напрямую.

Если старый launcher `py` не видит версию, установленную через Install Manager, вместо первой команды создания окружения используйте:

~~~powershell
pymanager exec -V:3.13 -m venv .venv
~~~

После создания окружения продолжайте команды через `.venv\Scripts\python.exe`.

Проверьте версию и архитектуру:

~~~powershell
.\.venv\Scripts\python.exe -c "import sys, platform; print(sys.version); print(platform.machine()); assert sys.version_info[:2] == (3, 13)"
~~~

### 3. Загрузите модель и создайте индекс

~~~powershell
.\.venv\Scripts\python.exe -m rag_demo prepare-model
.\.venv\Scripts\python.exe -m rag_demo validate-docs
.\.venv\Scripts\python.exe -m rag_demo index
~~~

Первая команда скачивает файлы модели и проверяет локальную загрузку. `validate-docs` должен вернуть `status: documents_valid` и состав включённых документов. `index` возвращает `status: indexed`, число документов и фрагментов; для исходного корпуса число документов определяется inventory.csv, число фрагментов — разбиением регламентов, размерность вектора — **768**.

### 4. Выполните первый поиск

~~~powershell
.\.venv\Scripts\python.exe -m rag_demo ask --question 'В какой срок клиент Листка может сообщить о недостающем товаре и обязательна ли фотография?' --top-k 8
~~~

В выводе будет JSON с `status: retrieval_only`, вопросом и массивом `hits`. Команда сама сохраняет поиск и его историю в `evidence/`, а путь к файлу выводит отдельным сообщением. Если не указан `--output`, имя файла уникально.

## Установка и первый запуск на macOS

### 1. Установите Python 3.13 для Apple Silicon

Проверьте архитектуру Terminal:

~~~bash
uname -m
~~~

Ожидается `arm64`. Если отображается `x86_64` на Mac с Apple Silicon, откройте Terminal без режима Rosetta.

Для установки используйте [Homebrew](https://brew.sh/). После его настройки установите [python@3.13](https://formulae.brew.sh/formula/python@3.13):

~~~bash
brew install python@3.13
"$(brew --prefix python@3.13)/bin/python3.13" --version
~~~

Ожидается `Python 3.13.x`.

### 2. Создайте окружение и установите зависимости

Откройте Terminal в корне проекта:

~~~bash
"$(brew --prefix python@3.13)/bin/python3.13" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-macos.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'import sys, platform; print(sys.version); print(platform.machine()); assert sys.version_info[:2] == (3, 13); assert platform.machine() == "arm64"'
~~~

Для Mac используется `requirements-macos.txt`. Windows-файл содержит другую сборку PyTorch и не подходит для этой установки. Активация окружения не требуется.

### 3. Загрузите модель, создайте индекс и выполните поиск

~~~bash
.venv/bin/python -m rag_demo prepare-model
.venv/bin/python -m rag_demo validate-docs
.venv/bin/python -m rag_demo index
.venv/bin/python -m rag_demo ask --question 'В какой срок клиент Листка может сообщить о недостающем товаре и обязательна ли фотография?' --top-k 8
~~~

Ожидаемые результаты такие же, как на Windows: `model_ready`, `documents_valid`, `indexed` и `retrieval_only`. Индекс сохраняется на диске, поэтому повторный поиск не требует повторной индексации.

## Работа с ИИ в папке проекта

1. Откройте папку проекта в среде, где ИИ может читать и создавать файлы и выполнять команды.
2. Для помощи с установкой поручите ему прочитать `AGENTS.md` и раздел README для вашей ОС. ИИ проверяет имеющуюся среду и выполняет недостающие действия.
3. Перед вопросами о регламентах поручите ИИ прочитать **сохранённый `rag-policy.md`**.
4. Задайте вопрос своими словами. ИИ сам выполняет новый поиск, читает его результат, сохраняет фактический ответ и запускает `finalize`.
5. После успешной проверки ИИ показывает ответ, цитаты, источники и пути к сохранённым файлам.

Вручную передавать JSON поиска не нужно. Если ИИ ждёт его от вас, проверьте чтение актуальной policy и доступ к терминалу. Отсутствие результата ещё не выполненного поиска не означает недостаток данных в документах.

## Эмбеддинговая модель

Используется [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base): локальные векторы размерности 768, нормализация, префиксы `passage: ` для документов и `query: ` для вопросов. Эти параметры заданы в `rag_demo/config.py`.

Обычный способ загрузки — команда `prepare-model` выше. Последующие `index` и `ask` загружают модель только из `models/multilingual-e5-base/`.

### Ручная загрузка с Hugging Face

1. Откройте [Files and versions](https://huggingface.co/intfloat/multilingual-e5-base/tree/main).
2. Внутри проекта создайте `models/multilingual-e5-base/`, а в ней — `1_Pooling/`.
3. Откройте каждый файл из списка ниже и скачайте его кнопкой загрузки. Сохраняйте сам файл, а не HTML страницы; не меняйте расширения.
4. `1_Pooling/config.json` положите в подпапку `1_Pooling`. Остальные файлы — в корень папки модели.
5. Скачивайте все файлы из одной версии репозитория. После изменения файлов модели потребуется новый индекс.

Нужны десять файлов:

~~~text
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
~~~

После ручной загрузки выполните `index`. В случае неполного набора файлов команда перечислит отсутствующие файлы.

## Команды и сохранённые результаты

| Команда | Назначение |
| --- | --- |
| `prepare-model` | Скачать и проверить локальную модель |
| `validate-docs` | Проверить документы и инвентарь |
| `chunks` | Сохранить структурные фрагменты в `evidence/chunks.json` |
| `compare-chunking` | Сравнить структурное разбиение с фиксированными окнами |
| `index` | Создать или обновить сохранённый индекс |
| `ask` / `retrieve` | Выполнить поиск по произвольному вопросу |
| `finalize` | Проверить сохранённый ответ и его цитаты |

Подробный поиск можно сохранить под выбранным именем:

~~~powershell
.\.venv\Scripts\python.exe -m rag_demo ask --question 'Можно ли вернуть деньги на другую карту?' --top-k 8 --output evidence/retrieval-card.json
~~~

~~~bash
.venv/bin/python -m rag_demo ask --question 'Можно ли вернуть деньги на другую карту?' --top-k 8 --output evidence/retrieval-card.json
~~~

ИИ читает этот результат и сохраняет реальный ответ в `evidence/answer-card.raw.json` с полями `answer`, `citations` и `decision`. Каждая цитата содержит `document_id`, `chunk_id` и дословную `quote` из текущего найденного фрагмента. Затем ИИ запускает:

~~~powershell
.\.venv\Scripts\python.exe -m rag_demo finalize --retrieval evidence/retrieval-card.json --answer-file evidence/answer-card.raw.json
~~~

~~~bash
.venv/bin/python -m rag_demo finalize --retrieval evidence/retrieval-card.json --answer-file evidence/answer-card.raw.json
~~~

`finalize` сверяет актуальность индекса, структуру поиска и ответа, принадлежность цитат найденным документам и дословность текста. Успех создаёт уникальные `result-*.json`, `trace-*.json` и `citation-map-*.json`. Ошибка возвращает ненулевой код завершения с объяснением причины. Проверка не определяет, следует ли смысл утверждения из цитаты.

Для повторного запуска выбирайте новые имена retrieval/raw, чтобы сохранить предыдущие ответы. Поиск выводит JSON в stdout, а диагностические сообщения — в stderr.

## Повторный запуск и обновление документов

После закрытия терминала откройте его снова в корне проекта и используйте тот же интерпретатор `.venv`. Повторная установка зависимостей и загрузка модели не нужны.

Если изменены `docs/`, `inventory.csv`, файлы модели или параметры профиля, выполните новый `index`, затем новый поиск. Старый результат поиска относится к своему `index_id` и не принимается для проверки обновлённого индекса.

## Если возникла ошибка

- **Python 3.13 не найден:** повторите проверку версии; на Windows после установки откройте новый терминал и используйте `pymanager install 3.13`.
- **No matching distribution found:** проверьте Python 3.13, архитектуру и файл зависимостей для своей ОС. На Mac ожидается arm64.
- **Слишком длинный путь на Windows:** распакуйте проект в более короткий путь и создайте окружение там заново.
- **Local model files missing:** выполните `prepare-model` либо проверьте десять файлов ручной загрузки.
- **No saved index:** выполните `index`.
- **Stale index:** документы или профиль изменились; выполните новый `index` и новый поиск.
- **Ошибка цитаты в finalize:** ИИ должен исправить ID или цитату по результату того же поиска и повторить проверку.
- **Ошибка доступа или сети:** проверьте доступ к папке и адресам установки/загрузки. Это техническая ошибка; она не означает отсутствие ответа в корпусе.

