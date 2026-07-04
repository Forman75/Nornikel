from __future__ import annotations 

import json 
import re 
from dataclasses import dataclass ,field 
from typing import Optional 

from pydantic import BaseModel ,Field ,ValidationError 

class QueryIntent (BaseModel ):
    query_type :str =Field ("lookup",description ="lookup|comparison|gap_analysis|duplicate_check")
    materials :list [str ]=Field (default_factory =list )
    processes :list [str ]=Field (default_factory =list )
    terms :list [str ]=Field (default_factory =list ,description ="прочие ключевые термины для поиска")
    geography :Optional [str ]=Field (None ,description ="RU|INTL|None")
    year_from :Optional [int ]=None 
    year_to :Optional [int ]=None 

    def search_terms (self )->list [str ]:
        seen ,out =set (),[]
        for t in self .materials +self .processes +self .terms :
            t =t .strip ()
            if t and t .lower ()not in seen :
                seen .add (t .lower ());out .append (t )
        return out 

_INTENT_SYS ="""Ты разбираешь технический вопрос пользователя по горно-металлургической
тематике в JSON-намерение. Верни СТРОГО валидный JSON без markdown по схеме:
{
 "query_type": "lookup|comparison|gap_analysis|duplicate_check",
 "materials": ["никель","сульфаты"],
 "processes": ["электроэкстракция"],
 "terms": ["католит","скорость потока"],
 "geography": "RU|INTL|null",
 "year_from": 2019, "year_to": 2024
}
Правила: query_type=comparison если вопрос про сравнение РФ/зарубеж или методов;
gap_analysis если спрашивают «что не изучено/пробелы»; duplicate_check если
«было ли уже такое исследование». Поля-списки могут быть пустыми, годы/geography null."""

@dataclass 
class GraphNode :
    id :str 
    label :str 
    name :str 
    props :dict =field (default_factory =dict )

@dataclass 
class GraphEdge :
    source :str 
    target :str 
    type :str 

@dataclass 
class SourceCard :
    title :str 
    author :Optional [str ]
    year :Optional [int ]
    geography :Optional [str ]
    snippet :str 
    score :float 

@dataclass 
class QueryResult :
    answer :str 
    intent :QueryIntent 
    nodes :list [GraphNode ]
    edges :list [GraphEdge ]
    sources :list [SourceCard ]

_CYPHER_NEIGHBOURHOOD ="""
UNWIND $terms AS term
MATCH (s)
WHERE (toLower(s.name) CONTAINS toLower(term)
       OR toLower(coalesce(s.name_en,'')) CONTAINS toLower(term))
  AND NOT s:Chunk
WITH collect(DISTINCT s) AS seeds
UNWIND seeds AS s
OPTIONAL MATCH p = (s)-[*1..2]-(m)
WHERE none(x IN nodes(p) WHERE x:Chunk)
WITH seeds, collect(p) AS paths
CALL {
  WITH seeds, paths
  WITH seeds + apoc.coll.flatten([pp IN paths | nodes(pp)]) AS ns,
       apoc.coll.flatten([pp IN paths | relationships(pp)]) AS rs
  RETURN ns, rs
}
RETURN ns AS nodes, rs AS rels
"""

_CYPHER_NEIGHBOURHOOD_NOAPOC ="""
UNWIND $terms AS term
MATCH (s) WHERE (toLower(s.name) CONTAINS toLower(term)
       OR toLower(coalesce(s.name_en,'')) CONTAINS toLower(term)) AND NOT s:Chunk
WITH collect(DISTINCT s) AS seeds
UNWIND seeds AS s
OPTIONAL MATCH (s)-[r]-(m) WHERE NOT m:Chunk
RETURN s, r, m
LIMIT 300
"""

_CYPHER_VECTOR ="""
CALL db.index.vector.queryNodes('chunk_embedding', $k, $qvec)
YIELD node AS c, score
MATCH (pub:Publication)-[:HAS_CHUNK]->(c)
WHERE ($geo IS NULL OR pub.geography = $geo)
  AND ($year_from IS NULL OR coalesce(pub.year, 9999) >= $year_from)
  AND ($year_to IS NULL OR coalesce(pub.year, 0) <= $year_to)
RETURN c.text AS text, score,
       pub.name AS title, pub.author_or_org AS author,
       pub.year AS year, pub.geography AS geography
ORDER BY score DESC LIMIT $k
"""

_CYPHER_GAP ="""
MATCH (mat:Material)
MATCH (proc:Process)
WHERE NOT EXISTS {
  MATCH (e:Experiment)-[:USES_MATERIAL]->(mat)
  WHERE EXISTS { MATCH (e)-[:PRODUCES_OUTPUT|PRODUCED|USES_MATERIAL]-() }
}
WITH mat, proc LIMIT 40
OPTIONAL MATCH (proc)-[:REQUIRES_CONDITION]->(cond:Condition)
RETURN mat.name AS material, proc.name AS process,
       collect(DISTINCT cond.name)[..3] AS conditions
LIMIT 25
"""

class QueryOrchestrator :
    def __init__ (self ,driver ,client ,use_apoc :bool =False ):
        self .driver =driver 
        self .client =client 
        self .use_apoc =use_apoc 

    def parse_intent (self ,question :str )->QueryIntent :
        raw =self .client .complete (_INTENT_SYS ,question ,temperature =0.0 )
        cleaned =re .sub (r"^\s*```(?:json)?|```\s*$","",raw ,flags =re .MULTILINE ).strip ()
        try :
            data =json .loads (cleaned )
            if data .get ("geography")in ("null",""):
                data ["geography"]=None 
            return QueryIntent .model_validate (data )
        except (json .JSONDecodeError ,ValidationError ):

            words =[w for w in re .findall (r"[А-Яа-яЁёA-Za-z]{4,}",question )][:8 ]
            return QueryIntent (query_type ="lookup",terms =words )

    def _fetch_neighbourhood (self ,terms :list [str ])->tuple [list [GraphNode ],list [GraphEdge ]]:
        if not terms :
            return [],[]
        nodes :dict [str ,GraphNode ]={}
        edges :list [GraphEdge ]=[]
        with self .driver .session ()as s :
            res =s .run (_CYPHER_NEIGHBOURHOOD_NOAPOC ,terms =terms )
            for rec in res :
                for key in ("s","m"):
                    n =rec .get (key )
                    if n is None :
                        continue 
                    nid =n .element_id 
                    if nid not in nodes :
                        lbls =list (n .labels )
                        nodes [nid ]=GraphNode (
                        id =nid ,label =lbls [0 ]if lbls else "Node",
                        name =n .get ("name","?"),props =dict (n ),
                        )
                r =rec .get ("r")
                if r is not None :
                    edges .append (GraphEdge (
                    source =r .start_node .element_id ,
                    target =r .end_node .element_id ,type =r .type ,
                    ))
        return list (nodes .values ()),edges 

    def _vector_search (self ,question :str ,intent :QueryIntent ,k :int =5 )->list [SourceCard ]:
        qvec =self .client .embed (question ,is_query =True )
        cards :list [SourceCard ]=[]
        with self .driver .session ()as s :
            res =s .run (_CYPHER_VECTOR ,k =k ,qvec =qvec ,
            geo =intent .geography ,year_from =intent .year_from ,
            year_to =intent .year_to )
            for rec in res :
                snippet =(rec ["text"]or "")[:280 ]
                cards .append (SourceCard (
                title =rec ["title"]or "?",author =rec ["author"],
                year =rec ["year"],geography =rec ["geography"],
                snippet =snippet ,score =float (rec ["score"]),
                ))
        return cards 

    _SYNTH_SYS ="""Ты отвечаешь на технический вопрос СТРОГО по приведённым фрагментам источников.
Не добавляй фактов, которых нет во фрагментах. Если данных недостаточно — так и скажи.
В конце ответа перечисли использованные источники (название, автор, год, РФ/зарубеж).
Группируй по методу/году/географии, если это уместно. Пиши по-русски, кратко и по делу."""

    def _synthesize (self ,question :str ,cards :list [SourceCard ])->str :
        if not cards :
            return ("По этому вопросу в графе не нашлось релевантных источников. "
            "Возможно, стоит загрузить больше документов по теме.")
        ctx ="\n\n".join (
        f"[Источник {i +1 }] {c .title }"
        f"{', '+c .author if c .author else ''}"
        f"{', '+str (c .year )if c .year else ''}"
        f" ({c .geography or '?'}):\n{c .snippet }"
        for i ,c in enumerate (cards )
        )
        return self .client .complete (self ._SYNTH_SYS ,
        f"Вопрос: {question }\n\nФрагменты:\n{ctx }")

    def answer (self ,question :str )->QueryResult :
        intent =self .parse_intent (question )
        nodes ,edges =self ._fetch_neighbourhood (intent .search_terms ())
        cards =self ._vector_search (question ,intent )
        answer =self ._synthesize (question ,cards )
        return QueryResult (answer =answer ,intent =intent ,
        nodes =nodes ,edges =edges ,sources =cards )

    def gap_analysis (self )->list [dict ]:
        with self .driver .session ()as s :
            return [dict (r )for r in s .run (_CYPHER_GAP )]

    def duplicate_check (self ,description :str ,threshold :float =0.80 )->list [SourceCard ]:
        qvec =self .client .embed (description ,is_query =True )
        cards :list [SourceCard ]=[]
        with self .driver .session ()as s :
            res =s .run (_CYPHER_VECTOR ,k =5 ,qvec =qvec ,
            geo =None ,year_from =None ,year_to =None )
            for rec in res :
                score =float (rec ["score"])
                if score >=threshold :
                    cards .append (SourceCard (
                    title =rec ["title"]or "?",author =rec ["author"],
                    year =rec ["year"],geography =rec ["geography"],
                    snippet =(rec ["text"]or "")[:280 ],score =score ,
                    ))
        return cards 

_CYPHER_SAMPLE ="""
MATCH (n) WHERE NOT n:Chunk
WITH n LIMIT $limit
OPTIONAL MATCH (n)-[r]-(m) WHERE NOT m:Chunk
RETURN n, r, m LIMIT $limit
"""

def sample_subgraph (driver ,limit :int =150 )->tuple [list [GraphNode ],list [GraphEdge ]]:
    nodes :dict [str ,GraphNode ]={}
    edges :list [GraphEdge ]=[]
    with driver .session ()as s :
        for rec in s .run (_CYPHER_SAMPLE ,limit =limit ):
            for key in ("n","m"):
                n =rec .get (key )
                if n is None :
                    continue 
                if n .element_id not in nodes :
                    lbls =list (n .labels )
                    nodes [n .element_id ]=GraphNode (
                    id =n .element_id ,label =lbls [0 ]if lbls else "Node",
                    name =n .get ("name","?"),props =dict (n ))
            r =rec .get ("r")
            if r is not None :
                edges .append (GraphEdge (r .start_node .element_id ,
                r .end_node .element_id ,r .type ))
    return list (nodes .values ()),edges
