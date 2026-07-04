from __future__ import annotations 

from enum import Enum 
from typing import Optional 

from pydantic import BaseModel ,Field ,model_validator 

class EntityType (str ,Enum ):
    MATERIAL ="Material"
    PROCESS ="Process"
    EQUIPMENT ="Equipment"
    CONDITION ="Condition"
    EXPERIMENT ="Experiment"
    PUBLICATION ="Publication"
    EXPERT ="Expert"
    FACILITY ="Facility"
    FINDING ="Finding"

class RelationType (str ,Enum ):
    USES_MATERIAL ="USES_MATERIAL"
    REQUIRES_CONDITION ="REQUIRES_CONDITION"
    OPERATES_AT_CONDITION ="OPERATES_AT_CONDITION"
    PRODUCES_OUTPUT ="PRODUCES_OUTPUT"
    PRODUCED ="PRODUCED"
    DESCRIBED_IN ="DESCRIBED_IN"
    VALIDATED_BY ="VALIDATED_BY"
    CONTRADICTS ="CONTRADICTS"
    AUTHORED_BY ="AUTHORED_BY"

RELATION_ENDPOINT_RULES :dict [RelationType ,tuple [frozenset [EntityType ],frozenset [EntityType ]]]={
RelationType .USES_MATERIAL :(
frozenset ({EntityType .PROCESS ,EntityType .EXPERIMENT ,EntityType .EQUIPMENT ,EntityType .FACILITY }),
frozenset ({EntityType .MATERIAL }),
),
RelationType .PRODUCES_OUTPUT :(
frozenset ({EntityType .PROCESS ,EntityType .EXPERIMENT ,EntityType .EQUIPMENT ,EntityType .FACILITY }),
frozenset ({EntityType .MATERIAL }),
),
RelationType .REQUIRES_CONDITION :(
frozenset ({EntityType .PROCESS ,EntityType .EXPERIMENT ,EntityType .MATERIAL ,EntityType .EQUIPMENT }),
frozenset ({EntityType .CONDITION }),
),
RelationType .OPERATES_AT_CONDITION :(
frozenset ({EntityType .EQUIPMENT ,EntityType .FACILITY ,EntityType .PROCESS }),
frozenset ({EntityType .CONDITION }),
),
RelationType .PRODUCED :(
frozenset ({EntityType .EXPERIMENT ,EntityType .PROCESS ,EntityType .FACILITY }),
frozenset ({EntityType .FINDING }),
),
RelationType .DESCRIBED_IN :(
frozenset ({EntityType .FINDING ,EntityType .EXPERIMENT ,EntityType .PROCESS ,EntityType .MATERIAL }),
frozenset ({EntityType .PUBLICATION }),
),
RelationType .VALIDATED_BY :(
frozenset ({EntityType .FINDING }),
frozenset ({EntityType .EXPERT }),
),
RelationType .CONTRADICTS :(
frozenset ({EntityType .FINDING }),
frozenset ({EntityType .FINDING }),
),
RelationType .AUTHORED_BY :(
frozenset ({EntityType .PUBLICATION ,EntityType .EXPERIMENT }),
frozenset ({EntityType .EXPERT }),
),
}

class ConditionOperator (str ,Enum ):
    LE ="<="
    GE =">="
    LT ="<"
    GT =">"
    EQ ="="
    RANGE ="range"
    CATEGORICAL ="is"

class Geography (str ,Enum ):
    RU ="RU"
    INTL ="INTL"
    UNKNOWN ="UNKNOWN"

class ConfidenceLevel (str ,Enum ):
    HIGH ="high"
    MEDIUM ="medium"
    LOW ="low"

class Condition (BaseModel ):
    parameter :str =Field (...,description ="Название параметра, напр. 'сульфаты', 'температура', 'скорость потока католита'")
    operator :ConditionOperator 
    value :Optional [float ]=Field (None ,description ="Числовое значение. Обязательно для всех operator, кроме CATEGORICAL")
    value_max :Optional [float ]=Field (None ,description ="Верхняя граница диапазона, только если operator == RANGE")
    unit :Optional [str ]=Field (None ,description ="Единица измерения, напр. 'мг/л', '°C', 'м3/ч'. Обязательна для числовых значений")
    value_text :Optional [str ]=Field (None ,description ="Текстовое значение для CATEGORICAL, напр. 'холодный'")

    @model_validator (mode ="after")
    def _check_value_consistency (self )->"Condition":
        if self .operator ==ConditionOperator .CATEGORICAL :
            if not self .value_text :
                raise ValueError ("CATEGORICAL condition требует value_text")
        else :
            if self .value is None :
                raise ValueError (f"operator={self .operator } требует числовое value")
            if not self .unit :
                raise ValueError (f"Числовой Condition ('{self .parameter }') требует unit — единица измерения обязательна")
        if self .operator ==ConditionOperator .RANGE :
            if self .value_max is None :
                raise ValueError ("operator=range требует value_max")

            if self .value is not None and self .value >self .value_max :
                self .value ,self .value_max =self .value_max ,self .value 
        return self 

class Entity (BaseModel ):
    local_id :str =Field (...,description ="Уникальный id в рамках ЭТОГО извлечения, напр. 'e1', 'e2'")
    type :EntityType 
    name :str =Field (...,description ="Каноническое имя на русском, как в тексте")
    name_en :Optional [str ]=Field (None ,description ="Английский эквивалент термина, если встречается в тексте (для сопоставления синонимов)")
    aliases :list [str ]=Field (default_factory =list ,description ="Другие встреченные в тексте варианты написания/сокращения, напр. ['ПВП', 'печь взвешенной плавки']")

    condition :Optional [Condition ]=Field (None ,description ="Заполняется только если type == CONDITION")
    geography :Optional [Geography ]=Field (None ,description ="Заполняется для Publication/Experiment/Facility, если география упомянута")
    year :Optional [int ]=Field (None ,description ="Год публикации/проведения эксперимента, если указан")
    author_or_org :Optional [str ]=Field (None ,description ="Автор/организация для Publication, Expert, Facility")

    source_span :str =Field (...,description ="Дословная цитата из чанка (≤200 симв.), на основании которой извлечена сущность — для аудита")
    confidence :ConfidenceLevel 

    @model_validator (mode ="after")
    def _check_type_specific_fields (self )->"Entity":
        if self .type ==EntityType .CONDITION and self .condition is None :
            raise ValueError ("Entity с type=CONDITION обязан содержать заполненный condition")
        if self .type !=EntityType .CONDITION and self .condition is not None :
            raise ValueError ("condition можно заполнять только для type=CONDITION")
        return self 

class Relation (BaseModel ):
    source_local_id :str =Field (...,description ="local_id сущности-источника из этого же извлечения")
    target_local_id :str =Field (...,description ="local_id сущности-цели из этого же извлечения")
    type :RelationType 
    source_span :str =Field (...,description ="Дословная цитата, подтверждающая связь (≤200 симв.)")
    confidence :ConfidenceLevel 

class ChunkExtractionResult (BaseModel ):
    chunk_id :str =Field (...,description ="id чанка в исходном документе, проставляется пайплайном до вызова LLM")
    entities :list [Entity ]=Field (default_factory =list )
    relations :list [Relation ]=Field (default_factory =list )

    @model_validator (mode ="after")
    def _check_integrity (self )->"ChunkExtractionResult":

        seen :set [str ]=set ()
        for e in self .entities :
            if e .local_id in seen :
                raise ValueError (f"Дубликат local_id '{e .local_id }' в списке entities")
            seen .add (e .local_id )

        by_id ={e .local_id :e for e in self .entities }

        for r in self .relations :

            if r .source_local_id not in by_id or r .target_local_id not in by_id :
                raise ValueError (
                f"Relation {r .type } ссылается на local_id вне списка entities "
                f"({r .source_local_id } -> {r .target_local_id })"
                )

        return self 

def sanitize_relations (result :ChunkExtractionResult )->tuple [ChunkExtractionResult ,list [str ]]:
    by_id ={e .local_id :e for e in result .entities }
    kept :list [Relation ]=[]
    dropped :list [str ]=[]
    for r in result .relations :
        src ,tgt =by_id [r .source_local_id ],by_id [r .target_local_id ]
        allowed_src ,allowed_tgt =RELATION_ENDPOINT_RULES [r .type ]
        if src .type in allowed_src and tgt .type in allowed_tgt :
            kept .append (r )
        else :
            dropped .append (f"{r .type .value }: {src .type .value }({src .name }) -> {tgt .type .value }({tgt .name })")
    if dropped :
        result =result .model_copy (update ={"relations":kept })
    return result ,dropped 

def build_extraction_system_prompt ()->str :
    schema_json =ChunkExtractionResult .model_json_schema ()
    endpoint_rules_text ="\n".join (
    f"- {rel .value }: {'/'.join (sorted (t .value for t in src ))} -> {'/'.join (sorted (t .value for t in tgt ))}"
    for rel ,(src ,tgt )in RELATION_ENDPOINT_RULES .items ()
    )
    return f"""Ты — эксперт по извлечению структурированных данных из технических текстов
по горно-металлургической тематике (гидрометаллургия, пирометаллургия, обогащение, экология).

Извлеки из текста ТОЛЬКО сущности и связи, явно упомянутые в тексте. Не додумывай и не добавляй
общеизвестные факты, которых нет в исходном фрагменте.

Обязательно для числовых ограничений (Condition): указывай parameter, operator, value И unit.
Если единица измерения не указана в тексте явно — НЕ извлекай это ограничение вообще
(лучше пропустить, чем ошибиться в единицах — это критичное требование).

Сопоставляй синонимы и русско-английские эквиваленты в поля name/name_en/aliases одной сущности,
не создавай отдельные сущности для одного и того же понятия на разных языках.

Каждая связь может соединять только следующие типы сущностей (источник -> цель):
{endpoint_rules_text }

Различай две похожие связи:
- PRODUCES_OUTPUT — процесс/печь/завод производит МАТЕРИАЛ (штейн, файнштейн, шлак, катод).
  Пример: "ПВП производит штейн" -> Equipment ПВП -PRODUCES_OUTPUT-> Material штейн.
- PRODUCED — эксперимент/процесс дал ВЫВОД/эффект (Finding), а не вещество.
  Пример: "ввод воздуха снизил Ni в шлаке до 0.25%" -> Process -PRODUCED-> Finding.
Если связь не укладывается ни в одну строку выше — НЕ выдумывай её, просто не создавай.

Верни СТРОГО валидный JSON по следующей схеме, без markdown-разметки, без пояснений до/после:

{schema_json }
"""

if __name__ =="__main__":

    example_llm_output ={
    "chunk_id":"doc12_chunk_0007",
    "entities":[
    {
    "local_id":"e1",
    "type":"Material",
    "name":"сульфаты",
    "name_en":"sulfates",
    "aliases":[],
    "source_span":"исходная вода содержит сульфаты, хлориды...",
    "confidence":"high",
    },
    {
    "local_id":"e2",
    "type":"Condition",
    "name":"концентрация сульфатов",
    "condition":{
    "parameter":"сульфаты",
    "operator":"range",
    "value":200 ,
    "value_max":300 ,
    "unit":"мг/л",
    },
    "source_span":"сульфаты... по 200-300 мг/л",
    "confidence":"high",
    },
    ],
    "relations":[
    {
    "source_local_id":"e1",
    "target_local_id":"e2",
    "type":"REQUIRES_CONDITION",
    "source_span":"сульфаты... по 200-300 мг/л",
    "confidence":"high",
    }
    ],
    }

    result =ChunkExtractionResult .model_validate (example_llm_output )
    print ("Валидация прошла успешно")
    print (result .model_dump_json (indent =2 ))
