from __future__ import annotations 

import os 
import re 
from dataclasses import dataclass 
from typing import Optional 

from neo4j import GraphDatabase ,Driver 

from extraction_schema import (
ChunkExtractionResult ,
Entity ,
EntityType ,
Relation ,
)

EMBEDDING_DIM =int (os .getenv ("EMBEDDING_DIM","256"))

_UNIT_ALIASES :dict [str ,str ]={
"мг/дм3":"мг/л","мг/дм³":"мг/л","mg/l":"мг/л","mg/dm3":"мг/л",
"г/дм3":"г/л","г/дм³":"г/л","g/l":"г/л",
"м3/ч":"м³/ч","m3/h":"м³/ч","куб.м/ч":"м³/ч",
"т/сут":"т/сут","т/сутки":"т/сут","t/day":"т/сут",
"с":"°C","гр.с":"°C","град.с":"°C","°с":"°C","c":"°C","°c":"°C",
"мпа":"МПа","mpa":"МПа","кпа":"кПа","kpa":"кПа",
"об/мин":"об/мин","rpm":"об/мин",
"а/м2":"А/м²","а/м²":"А/м²","a/m2":"А/м²",
"м/с":"м/с","m/s":"м/с",
"%":"%",
}

def norm_text (s :str )->str :
    s =s .strip ().lower ().replace ("ё","е")
    s =re .sub (r"\s+"," ",s )
    return s 

def norm_unit (unit :Optional [str ])->Optional [str ]:
    if unit is None :
        return None 
    key =norm_text (unit ).replace (" ","")
    return _UNIT_ALIASES .get (key ,unit .strip ())

def entity_norm_key (e :Entity )->str :
    if e .type ==EntityType .CONDITION and e .condition is not None :
        c =e .condition 
        parts =[
        norm_text (c .parameter ),
        c .operator .value ,
        ""if c .value is None else f"{c .value :g}",
        ""if c .value_max is None else f"{c .value_max :g}",
        norm_unit (c .unit )or "",
        norm_text (c .value_text )if c .value_text else "",
        ]
        return "|".join (parts )
    return norm_text (e .name )

def condition_display_name (e :Entity )->str :
    c =e .condition 
    assert c is not None 
    if c .operator .value =="is":
        return f"{c .parameter }: {c .value_text }"
    if c .operator .value =="range":
        return f"{c .parameter } {c .value :g}–{c .value_max :g} {norm_unit (c .unit )}"
    return f"{c .parameter } {c .operator .value } {c .value :g} {norm_unit (c .unit )}"

@dataclass 
class DocMeta :
    doc_id :str 
    title :str 
    year :Optional [int ]=None 
    author_or_org :Optional [str ]=None 
    geography :Optional [str ]=None 
    doc_type :Optional [str ]=None 

_ENTITY_LABELS =[t .value for t in EntityType ]

SCHEMA_STATEMENTS :list [str ]=[
*[
f"CREATE CONSTRAINT {label .lower ()}_key IF NOT EXISTS "
f"FOR (n:{label }) REQUIRE n.norm_key IS UNIQUE"
for label in _ENTITY_LABELS 
],
"CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.chunk_id IS UNIQUE",
"CREATE INDEX condition_parameter IF NOT EXISTS FOR (n:Condition) ON (n.parameter)",
"CREATE INDEX publication_year IF NOT EXISTS FOR (n:Publication) ON (n.year)",
"CREATE INDEX experiment_year IF NOT EXISTS FOR (n:Experiment) ON (n.year)",
"CREATE INDEX chunk_doc IF NOT EXISTS FOR (n:Chunk) ON (n.doc_id)",
f"""CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {{indexConfig: {{
          `vector.dimensions`: {EMBEDDING_DIM },
          `vector.similarity_function`: 'cosine'
        }}}}""",
"""CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
       FOR (n:Material|Process|Equipment|Experiment|Publication|Expert|Facility|Finding)
       ON EACH [n.name, n.name_en, n.aliases_text]""",
]

class GraphLoader :
    def __init__ (self ,driver :Driver ):
        self .driver =driver 

    @classmethod 
    def from_env (cls )->"GraphLoader":
        uri =os .environ ["NEO4J_URI"]
        user =os .environ .get ("NEO4J_USER","neo4j")
        password =os .environ ["NEO4J_PASSWORD"]
        return cls (GraphDatabase .driver (uri ,auth =(user ,password )))

    def close (self )->None :
        self .driver .close ()

    def ensure_schema (self )->None :
        with self .driver .session ()as session :
            for stmt in SCHEMA_STATEMENTS :
                session .run (stmt )

    def load_chunk (
    self ,
    result :ChunkExtractionResult ,
    doc :DocMeta ,
    chunk_text :str ,
    embedding :list [float ],
    position :int =0 ,
    )->None :
        if len (embedding )!=EMBEDDING_DIM :
            raise ValueError (
            f"Эмбеддинг длины {len (embedding )}, ожидалось {EMBEDDING_DIM }. "
            f"Проверь модель эмбеддингов или EMBEDDING_DIM."
            )

        key_by_local_id ={e .local_id :entity_norm_key (e )for e in result .entities }
        type_by_local_id ={e .local_id :e .type for e in result .entities }

        with self .driver .session ()as session :
            session .execute_write (
            self ._tx_load_chunk ,
            result ,doc ,chunk_text ,embedding ,position ,
            key_by_local_id ,type_by_local_id ,
            )

    @staticmethod 
    def _tx_load_chunk (
    tx ,
    result :ChunkExtractionResult ,
    doc :DocMeta ,
    chunk_text :str ,
    embedding :list [float ],
    position :int ,
    key_by_local_id :dict [str ,str ],
    type_by_local_id :dict [str ,EntityType ],
    )->None :

        tx .run (
        """
            MERGE (p:Publication {norm_key: $pub_key})
            ON CREATE SET p.created_at = datetime()
            SET p.name = $title,
                p.doc_id = $doc_id,
                p.year = coalesce($year, p.year),
                p.author_or_org = coalesce($author, p.author_or_org),
                p.geography = coalesce($geo, p.geography),
                p.doc_type = coalesce($doc_type, p.doc_type),
                p.updated_at = datetime()
            MERGE (c:Chunk {chunk_id: $chunk_id})
            SET c.text = $text, c.doc_id = $doc_id, c.position = $position
            WITH p, c
            CALL db.create.setNodeVectorProperty(c, 'embedding', $embedding)
            MERGE (p)-[:HAS_CHUNK]->(c)
            """,
        pub_key =norm_text (doc .title ),title =doc .title ,doc_id =doc .doc_id ,
        year =doc .year ,author =doc .author_or_org ,geo =doc .geography ,
        doc_type =doc .doc_type ,chunk_id =result .chunk_id ,
        text =chunk_text ,position =position ,embedding =embedding ,
        )

        by_label :dict [str ,list [dict ]]={}
        for e in result .entities :
            row ={
            "norm_key":key_by_local_id [e .local_id ],
            "name":e .name if e .type !=EntityType .CONDITION else condition_display_name (e ),
            "name_en":e .name_en ,
            "aliases":e .aliases ,
            "geography":e .geography .value if e .geography else None ,
            "year":e .year ,
            "author_or_org":e .author_or_org ,
            "source_span":e .source_span ,
            "confidence":e .confidence .value ,
            }
            if e .type ==EntityType .CONDITION :
                c =e .condition 
                row .update ({
                "parameter":norm_text (c .parameter ),
                "operator":c .operator .value ,
                "value":c .value ,
                "value_max":c .value_max ,
                "unit":norm_unit (c .unit ),
                "value_text":c .value_text ,
                })
            by_label .setdefault (e .type .value ,[]).append (row )

        for label ,rows in by_label .items ():
            extra =(
            """, n.parameter = row.parameter, n.operator = row.operator,
                    n.value = row.value, n.value_max = row.value_max,
                    n.unit = row.unit, n.value_text = row.value_text"""
            if label ==EntityType .CONDITION .value else ""
            )
            tx .run (
            f"""
                UNWIND $rows AS row
                MERGE (n:{label } {{norm_key: row.norm_key}})
                ON CREATE SET n.name = row.name, n.created_at = datetime()
                SET n.name_en = coalesce(row.name_en, n.name_en),
                    n.geography = coalesce(row.geography, n.geography),
                    n.year = coalesce(row.year, n.year),
                    n.author_or_org = coalesce(row.author_or_org, n.author_or_org),
                    n.aliases = reduce(acc = [], x IN coalesce(n.aliases, []) + row.aliases |
                                       CASE WHEN x IN acc THEN acc ELSE acc + x END),
                    n.updated_at = datetime()
                    {extra }
                SET n.aliases_text = reduce(s = '', a IN n.aliases | s + a + ' ')
                WITH n, row
                MATCH (c:Chunk {{chunk_id: $chunk_id}})
                MERGE (c)-[m:MENTIONS]->(n)
                SET m.source_span = row.source_span, m.confidence = row.confidence
                """,
            rows =rows ,chunk_id =result .chunk_id ,
            )

        rel_groups :dict [tuple [str ,str ,str ],list [dict ]]={}
        for r in result .relations :
            group =(
            r .type .value ,
            type_by_local_id [r .source_local_id ].value ,
            type_by_local_id [r .target_local_id ].value ,
            )
            rel_groups .setdefault (group ,[]).append ({
            "src_key":key_by_local_id [r .source_local_id ],
            "tgt_key":key_by_local_id [r .target_local_id ],
            "source_span":r .source_span ,
            "confidence":r .confidence .value ,
            })

        for (rel_type ,src_label ,tgt_label ),rows in rel_groups .items ():
            tx .run (
            f"""
                UNWIND $rows AS row
                MATCH (s:{src_label } {{norm_key: row.src_key}})
                MATCH (t:{tgt_label } {{norm_key: row.tgt_key}})
                MERGE (s)-[r:{rel_type }]->(t)
                ON CREATE SET r.created_at = datetime()
                SET r.source_span = row.source_span,
                    r.confidence = row.confidence,
                    r.chunk_id = $chunk_id,
                    r.updated_at = datetime()
                """,
            rows =rows ,chunk_id =result .chunk_id ,
            )

if __name__ =="__main__":
    from extraction_schema import ChunkExtractionResult 

    example ={
    "chunk_id":"doc12_chunk_0007",
    "entities":[
    {"local_id":"e1","type":"Process","name":"обратный осмос",
    "name_en":"reverse osmosis","aliases":["ОО"],
    "source_span":"установка обратного осмоса обеспечивает...",
    "confidence":"high"},
    {"local_id":"e2","type":"Condition","name":"концентрация сульфатов",
    "condition":{"parameter":"сульфаты","operator":"<=",
    "value":300 ,"unit":"мг/дм³"},
    "source_span":"при содержании сульфатов до 300 мг/дм3",
    "confidence":"high"},
    ],
    "relations":[
    {"source_local_id":"e1","target_local_id":"e2",
    "type":"REQUIRES_CONDITION",
    "source_span":"обратный осмос применим при содержании сульфатов до 300 мг/дм3",
    "confidence":"high"},
    ],
    }
    result =ChunkExtractionResult .model_validate (example )

    loader =GraphLoader .from_env ()
    loader .ensure_schema ()
    loader .load_chunk (
    result ,
    DocMeta (doc_id ="doc12.pdf",title ="Отчёт по обессоливанию воды ОФ",year =2023 ,
    author_or_org ="НИЦ Гидрометаллургии",geography ="RU",doc_type ="report"),
    chunk_text ="...установка обратного осмоса обеспечивает... при содержании сульфатов до 300 мг/дм3...",
    embedding =[0.0 ]*EMBEDDING_DIM ,
    position =7 ,
    )
    loader .close ()
    print ("Чанк загружен. Проверь в браузере: MATCH (n) RETURN n LIMIT 50")
