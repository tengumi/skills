# Конфигурация

Основной паттерн:

```python
from concoction import Configuration
from pydantic import BaseModel, Field

@Configuration("app.chat-openai")
class ChatOpenAiConfig(BaseModel):
    model_name: str
    openai_api_base: str
    openai_api_key: str = "abc"
    max_retries: int = 5
```

Декоратор `@Configuration` связывает поле класса с его конфигурацией.
Для инициализации класса используется библиотека Concoction, которая подгружает параметры из источников.

**Источники в порядке возрастания приоритета:**

в папке

```
/home/work/22411082@sigma.sbrf.ru/IdeaProjects/sberorm-agent-risk-assessment/projects/sber_orm_agent_risk_assessment/sber_orm_agent_risk_assessment/resources
```

* `application.yaml` в папке resources проекта
* `application-<stand-name>.yaml`
* Локальные переменные окружения (в которых находятся секреты, такие как креденшиалы и ключи)


