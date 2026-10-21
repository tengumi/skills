# MLE PEP8

Создал: Кондратьев Алексей Алексеевич. Редактировал: Васильев Пётр Андреевич
(мар. 31, 2026).

На данной странице собраны требования, рекомендации, а также шишки, набитые при
внедрении моделей. Статья призвана оптимизировать процесс внедрения моделей
машинного обучения и в целом написания кода на Python. Ориентирована не только
на MLOps/MLE, но и на коллег DS.

---

## 1. Общие правила

### 1.1. python >= 3.12

**Мотивация.** На более новых версиях питона меньше не забаненных в sberosc
библиотек.

### 1.2. type hints для pandas.DataFrame

Если у функций, работающих с DataFrame, вы явно указали входные и выходные
колонки — вы мой герой.

**Плохо**
```python
import pandas as pd

class MyModel:
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        ...
        first = df["a"] / df["b"].mean()
        ...
        second = df["c"] + df["d"]
        ...
        third = df["e"] / 20
        ...
        df_res = pd.DataFrame()
        df_res["first"] = first
        df_res["second"] = second
        df_res["third"] = third
        return df_res
```

**Хорошо**
```python
import pandas as pd

class MyModel:
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Make a prediction

        Args:
            df (pd.DataFrame): входные данные
                Columns:
                    a: float
                    b: float
                    c: float
                    d: float
                    e: float

        Returns:
            pd.DataFrame:
                Columns:
                    first: float
                    second: float
                    third: float
        """
        ...
```

### 1.3. Названия колонок только на английском

**Мотивация.** Код становится проще писать. Если хочется где-то использовать
кириллицу, лучше написать документацию.

### 1.4. Не сохранять в .pickle то, что можно положить в обычный .json

Так и DS, и MLE будет проще понять, что за структура там лежит, а также
отредактировать её.

**Плохо** — нечитаемые байты pickle
```
\x80\x04\x95 ... SBR_КП00043 ... SOH1 ...
```

**Хорошо**
```json
{
    "SBR_КП00043": "1"
}
```

### 1.5. predict: len(input) == len(output)

Это кажется очевидным, но иногда встречаются случаи, как в «Плохо». В целом
пример даже работает, но «Явное лучше неявного» (PEP20).

**Плохо**
```python
def predict(model, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # тут таблица меняет свой размер
    cond = ...
    df = df[cond]

    # вставляем предсказания
    pred_col = "pred"
    df[pred_col] = model.predict(df)

    return df

df_in = pd.DataFrame(...)
df_out = predict(model, df_in)
# здесь len(df_out) != len(df_in)

# Это работает, и даже правильно. Благодаря индексу, в места,
# неудовлетворяющие cond, вставятся nan-ы
df_in["pred"] = df_out["pred"]
```

**Хорошо**
```python
def predict(model, df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    cond = ...
    df.loc[cond, "pred"] = model.predict(df[cond])
    return df["pred"]

df_in = pd.DataFrame(...)
df_out = predict(model, df_in)
# здесь len(df_out) == len(df_in)

df_in["pred"] = df_out
```

### 1.6. Промпты должны храниться в отдельных .md файлах

Если только их не нужно конструировать динамически.

```python
with open("prompt.md") as f:
    prompt = f.read()
```

### 1.7. Не должно быть бессмысленной обработки исключений

Если что-то пошло не так — код должен упасть. Не удалось загрузить данные — не
надо заменять их на пустую строку. Не удалось достучаться до эндпойнта — не надо
делать вид, что всё норм.

**Очень плохо**
```python
try:
    model = GigaChat(...)
except Exception as e:
    model = None
    # Хе-хе-хе, теперь я упаду где-то дальше по коду,
    # и разраб долго будет искать, откуда у него вместо модели None
```

### 1.8. Не использовать лишних символов в промте

Каждый символ не в составе слова — это отдельный токен, за который мы платим
временем и деньгами. Лучше обходиться только словами и значимыми синтаксическими
символами. Пробелы в отступах к JSON — тоже символы.

**Плохо**
```
===============--- ПРОМПТ ---=================
| Ты - многоумный Гигачат. Скажи "Привет"!   |
==============================================
```

**Хорошо**
```
Ты - многоумный Гигачат. Скажи "Привет"!
```

### 1.9. Изменяемые параметры — в pydantic класс-конфиг, не константы/словари

Тогда этот класс можно будет легко подцепить к configmap на стенде, чтобы легко
конфигурировать эти параметры.

**Нежелательно**
```python
CONFIG = {
    # Минимальная длина чанка в токенах, чтобы не индексировать
    "MIN_CHUNK_TOKENS": 25,
    # Порог: если >N% строк содержат | ... | — считаем чанк табличным
    "TABLE_LINE_RATIO": 0.6,
}
```

**Нежелательно**
```python
# Минимальная длина чанка в токенах, чтобы не индексировать
MIN_CHUNK_TOKENS = 25

# Порог: если >N% строк содержат | ... | — считаем чанк табличным
TABLE_LINE_RATIO = 0.6
```

**Хорошо**
```python
from pydantic import BaseModel

class ReactUpdaterConfig(BaseModel):
    # Маркер склейки нескольких документов в одном bundle-файле
    bundle_separator: re.Pattern = re.compile(r"={10,}\s*DOCUMENT:\s*")

    # Минимальная длина чанка в токенах, чтобы не индексировать
    min_chunk_tokens: int = 25

    # Порог: если >N% строк содержат | ... | — считаем чанк табличным
    table_line_ratio: float = 0.6
```

### 1.10. Зависимости должны создаваться вне класса с логикой

Так происходит в продакшен-коде; ваш код будет проще интегрировать, если в нём
будет так же.

**Плохо**
```python
class MyLogic:
    def __init__(
        self,
        os_host: str,
        os_port: int,
        os_auth: tuple,
    ):
        logger.info(f"Подключение к OpenSearch на {os_host}:{os_port}...")
        self.os_client = OpenSearch(
            hosts=[{"host": os_host, "port": os_port}],
            http_auth=os_auth,
            use_ssl=True,
            verify_certs=False,
            ssl_show_warn=False,
        )
```

**Хорошо**
```python
class MyLogic:
    def __init__(self, os_client: OpenSearch):
        self.os_client = os_client
```

Если в `__init__` не остаётся вообще никакой логики, то гораздо удобнее, когда
сделан датакласс.

**Вообще отлично**
```python
@dataclass
class MyLogic:
    os_client: OpenSearch
```

### 1.11. Вариативность в типах аргументов нежелательна

Настоящая опциональность параметров редко является необходимой. Вопрос со
значениями по умолчанию можно решать на уровне конфигов. Если аргумент может
быть одного из двух альтернативных типов — выберите один и уберите из кода
обработку второго случая.

**Плохо**
```python
class Updater:
    def __init__(self, updater_config: Optional[Dict[str, Any]] = None):
        if not updater_config:
            updater_config = {
                "param1": 1,
                "param2": 100,
            }
        self.updater_config = updater_config
```

**Хорошо**
```python
class UpdaterConfig(BaseModel):
    param1: int = 2
    param2: float = 1000

@dataclass
class Updater:
    config: UpdaterConfig
```

### 1.12. Код должен быть вычищен

Не должно быть неиспользуемых параметров конфигов, лишних аргументов функций,
методов, которые нигде не вызываются и не предполагаются к вызову.

### 1.13. Работа с файлами — отдельно от логики

Получение файлов из файловой системы и их запись должны быть вынесены в
отдельные функции. В идеале — происходить только в начале и в конце пайплайна.

При внедрении разработчики работают не с файловой системой, а с БД и данными из
запросов. Нам будет удобно, если можно будет легко заменить функции получения
данных, оставив при этом основную логику нетронутой.

**Очень плохо**
```python
def get_final_prompt():
    final_prompt = ""
    for dirpath, _, filenames in os.walk(target_dir_abs):
        for filename in filenames:
            with open(filename, "r") as f:
                final_prompt += f.read()
    return final_prompt
```

**Очень хорошо**
```python
# Эта функция будет заменена на другую при внедрении
def get_prompt_chunks():
    prompt_chunks = []
    for dirpath, _, filenames in os.walk(target_dir_abs):
        for filename in filenames:
            with open(filename, "r") as f:
                prompt_chunks.append(f.read())
    return prompt_chunks

# Эта функция останется полностью нетронутой, и к ней легко написать тест
def _get_final_prompt(prompt_chunks):
    return "".join(prompt_chunks)

def get_final_prompt():
    prompt_chunks = get_prompt_chunks()
    final_prompt = _get_final_prompt(prompt_chunks)
    return final_prompt
```

---

## 2. Подготовка отдельного кода к внедрению

### 2.1. Фиксация зависимостей

К внедряемому коду должны прилагаться зависимости в `requirements.txt` или в
другом удобном формате.

Библиотеки, версии которых следует брать точь-в-точь:

- **pymorphy2** — между версиями обновляются словари, что приводит к изменению
  токенизации и, как следствие, предсказаний.

### 2.2. Про .ipynb

**Мотивация.** Если ваш `.ipynb` занимает более четырёх экранов, его
читабельность под вопросом.

Если всё-таки без ноутбука не обойтись, старайтесь сначала сделать все импорты,
объявить все функции и классы. После этого можно писать содержательную часть с
тренировкой/инференсом. Это позволит ничего не потерять при переносе пайплайна
из ноутбука в класс.

---

## 3. Создание пул-реквестов в репозитории с кодом

### 3.1. Покрытие всех функций данными для тестирования

Нас обязали покрывать тестами 80% кода. Если вы готовы покрыть свой код тестами
сами — честь вам и хвала, такой вариант удобен всем. В генерации тестов хорошо
может помочь LLM. Если пишете сами, дальше этот пункт можно не читать. В
противном случае нужно для каждой функции предоставить примеры использования.
Каждый пример должен состоять из таких данных:

- Входные данные
- Данные, получаемые от интеграций (например, ответы LLM)
- Выходные данные

На основе этого разработчиками будет написан тест, который выполнит эту функцию с
этими данными и проверит, что выходные значения такие, какие ожидаются.

Ниже — пример того, как эти данные могут быть переданы. Удобнее всего, если они
сразу будут помещены в папку с тестами в соответствующую тест-кейсу функцию. В
остальном выражение свободное. Главное — чтобы разработчик понял, что куда
подставлять.

```python
async def test_think_node_calls_tool():
    # Вызываемая функция:
    sber_orm_agent_text_to_sql.agents.graph.Nodes.think_node

    # Входные данные
    sample_state = {
        "messages": [HumanMessage(content="Test query")],
        "user_query": "Test query",
        "tenant_id": "tenant123",
    }

    # выражение await self.llm_with_tools.ainvoke(invocation_messages)
    # на строке 175 возвращает:
    AIMessage(
        "Hello",
        tool_calls=[
            {
                "id": "id",
                "name": "run_sql",
                "args": {"sql_query": "SELECT * FROM table1"},
            }
        ],
    )

    # на выходе должно получиться:
    result = [
        HumanMessage(content="Test query", additional_kwargs={}, response_metadata={}),
        AIMessage(
            content="Hello",
            additional_kwargs={},
            response_metadata={},
            tool_calls=[
                {"name": "run_sql", "args": {"sql_query": "SELECT * FROM table1"}, "id": "id", "type": "tool_call"}
            ],
        ),
    ]
```

Данные удобнее всего снимать из дебаггера. Для этого во время локального прогона:

1. поставить точку останова в нужном месте;
2. в дебаггере найти строчку Evaluate Expression и вбить в ней
   `print(variable_name)`;
3. скопировать то, что вывелось во вкладке Console дебаггера.

Приведённый выше пример разработчиком будет переработан в тест:
https://stash.sigma.sbrf.ru/projects/SBERORM/repos/sberorm-agent-text-to-sql/browse/projects/sber_orm_agent_text_to_sql/tests/agents/test_graph.py#79

Такие тест-кейсы должны покрывать весь закоммиченный или отредактированный код.
Если есть `if`-ы — очень желательно заходить такими кейсами во все случаи. Для
маленьких функций тест-кейсы можно создавать как отдельно, так и прогонять их в
составе больших.

#### В чём цель

Цель этого всего — обеспечить покрытие тестами с минимальной болью для DS и
разработки. Мы пытаемся сделать так, чтобы:

- DS не учился писать тесты, если это не входит в его круг интересов;
- разработчики не пытались угадывать, какой сложный JSON данных нужно в тесте
  передать в функцию, чтобы она корректно отработала.

Если у вас есть идеи, как улучшить взаимодействие для покрытия тестами — пишите
Петру Васильеву. Если вы DS и хотите научиться писать тесты самостоятельно —
тоже смело обращайтесь к любому из разработчиков.

Ещё пример, как могут выглядеть тесты:
https://stash.sigma.sbrf.ru/projects/SBERORM/repos/sberorm-agent-risk-assessment/browse/projects/sber_orm_agent_risk_assessment/tests/unit/test_rescore_node.py

---

## 4. Оптимизация

### 4.1. Поиск в коллекции — на примере удаления стоп-слов

Довольно распространённая ошибка. Когда мы что-то ищем в коллекции, надо
использовать `set` или `dict`, потому что там поиск за O(1).

**Очень плохо**
```python
stop_words = ["что", "где", "когда"]
tokens = [...]

filtered_tokens = [token for token in tokens if token in stop_words]
```

**Хорошо**
```python
stop_words = {"что", "где", "когда"}
tokens = [...]

filtered_tokens = [token for token in tokens if token in stop_words]
```

### 4.2. pandas, numpy, torch vs циклы

Если вы работаете с объектом `pd.Series`, `pd.DataFrame`, `np.ndarray`,
`torch.tensor` и вдруг захотели пробежаться по нему циклом — стоит поискать
соответствующий метод, который производит аналогичную векторную операцию. Это
будет гораздо быстрее, как правило в десятки раз.

### 4.3. predict не должен работать с файловой системой, если это не задумано моделью

**Мотивация.** Читать файлы с диска — медленно. А если это один и тот же,
заранее известный файл — неразумно. Стремимся к тому, что любой разрабатываемый
нами ПИМ легко масштабируется и работает на любом числе исполнителей. Для этого
модель сериализуется и отправляется на каждый из них. Но файлы-то нет — придётся
отдельно их отправлять и класть в нужное место на каждом исполнителе. Лучше,
когда нужные структуры данных уже инкапсулированы в модель.

**Плохо**
```python
class MyModel:
    def predict(self, tokens: List[str]):
        ...
        with open("stop_words.pickle", "rb") as f:
            stop_words = pickle.load(f)

        valid_tokens = [i for i in tokens if i not in stop_words]
        ...
```

**Хорошо**
```python
class MyModel:
    def __init__(self, stop_words_path: Path):
        with open(stop_words_path, "rb") as f:
            self.stop_words = pickle.load(f)

    def predict(self, tokens: List[str]):
        ...
        valid_tokens = [i for i in tokens if i not in self.stop_words]
        ...
```

**Очень хорошо**
```python
class MyModel:
    def __init__(self, stop_words: Set[str]):
        self.stop_words = stop_words

    @classmethod
    def from_path(cls, stop_words_path: Path):
        with open(stop_words_path, "rb") as f:
            stop_words = pickle.load(f)
        return cls(stop_words)

    def predict(self, tokens: List[str]):
        ...
        valid_tokens = [i for i in tokens if i not in self.stop_words]
        ...
```

### 4.4. Кэширование pymorphy2

Очень часто для лемматизации мы используем подобный блок кода.

**Плохо**
```python
from pymorphy2 import MorphAnalyzer
morph = MorphAnalyzer()

def lemmatize(token: str) -> str:
    return morph.normal_forms(token)[0]
```

Очень много времени может сэкономить следующее улучшение.

**Хорошо**
```python
from pymorphy2 import MorphAnalyzer
from functools import lru_cache

morph = MorphAnalyzer()

@lru_cache(maxsize=None)
def lemmatize(token: str) -> str:
    return morph.normal_forms(token)[0]
```

### 4.5. torch.no_grad()

Никогда нельзя забывать, если речь идёт об инференсе. В противном случае
градиенты будут не только считаться, но и накапливаться в памяти. Рано или поздно
это приводит к OOM, особенно критично, если речь идёт о MEF-обёртках.

**Плохо**
```python
from transformers import AutoModel

model = AutoModel.from_pretrained("rubert-base-cased")
inputs = {...}

outputs = model(**inputs)
```

**Хорошо**
```python
import torch
from transformers import AutoModel

model = AutoModel.from_pretrained("rubert-base-cased")
inputs = {...}

with torch.no_grad():
    outputs = model(**inputs)
```

### 4.6. Не использовать += с коллекциями

`+=` создаёт новый инстанс коллекции и записывает в него два операнда. Если этот
оператор используется в цикле — это тратит кучу времени.

**Плохо**
```python
res = []
for i in range(1000):
    res += [i, i + 1, i + 2]
```

**Хорошо**
```python
res = []
for i in range(1000):
    res.extend([i, i + 1, i + 2])
```

