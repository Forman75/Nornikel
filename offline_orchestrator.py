from __future__ import annotations 

import re 

from query_orchestrator import (
QueryIntent ,QueryResult ,SourceCard ,QueryOrchestrator ,
)

_TERM_TRIGGERS :dict [str ,list [str ]]={
"обессоливание":["обессолив","деминерализ","сухой остаток","водоподготов"],
"сульфаты":["сульфат"],
"хлориды":["хлорид"],
"обратный осмос":["осмос"],
"электроэкстракция":["электроэкстрак","electrowin","электролиз"],
"католит":["католит"],
"никель":["никел","nickel"],
"медь":["медь","медн","copper"],
"штейн":["штейн","matte"],
"шлак":["шлак","slag"],
"файнштейн":["файнштейн"],
"золото":["золот","gold"," au "],
"серебро":["серебр","silver"," ag "],
"МПГ":["мпг","платино","паллади","pgm"],
"шахтные воды":["шахтн","рудничн вод"],
"закачка":["закачк","нагнетан","глубок горизонт"],
"плавка":["плавк","плавильн"],
"печь взвешенной плавки":["пвп","взвешенн"],
"конвертер":["конвертер"],
"концентрат":["концентрат"],
"котел-утилизатор":["котел","котёл","утилизатор"],
"кислород":["кислород"],
"сера":["сера","серы","сернист","so2","диоксид серы"],
"извлечение":["извлечен"],
}

_GEO_RU =["росси"," рф","отечествен","у нас"]
_GEO_INTL =["зарубеж","мирово","иностран","за рубежом","международн"]

def parse_intent_rules (question :str )->QueryIntent :
    low =" "+question .lower ()+" "
    terms =[canon for canon ,trigs in _TERM_TRIGGERS .items ()
    if any (t in low for t in trigs )]
    if not terms :
        terms =re .findall (r"[а-яёa-z]{5,}",low )[:6 ]

    qtype ="lookup"
    if any (w in low for w in ["уже исследов","уже провод","было ли","дубл"]):
        qtype ="duplicate_check"
    elif any (w in low for w in ["пробел","не изучен","не исследован","чего нет"]):
        qtype ="gap_analysis"
    elif any (w in low for w in ["сравн","vs","против","или"])or (
    any (g in low for g in _GEO_RU )and any (g in low for g in _GEO_INTL )):
        qtype ="comparison"

    geo =None 
    if any (g in low for g in _GEO_RU )and not any (g in low for g in _GEO_INTL ):
        geo ="RU"
    elif any (g in low for g in _GEO_INTL )and not any (g in low for g in _GEO_RU ):
        geo ="INTL"

    years =[int (y )for y in re .findall (r"\b(19\d{2}|20\d{2})\b",question )]
    y_from ,y_to =(min (years ),max (years ))if years else (None ,None )
    m =re .search (r"за последние (\d+)",low )
    if m :
        y_to =2026 
        y_from =2026 -int (m .group (1 ))

    return QueryIntent (query_type =qtype ,terms =terms ,geography =geo ,
    year_from =y_from ,year_to =y_to )

_CYPHER_TEXT_SEARCH ="""
MATCH (pub:Publication)-[:HAS_CHUNK]->(c:Chunk)
WHERE ($geo IS NULL OR pub.geography = $geo)
WITH pub, c,
     size([t IN $terms WHERE toLower(c.text) CONTAINS toLower(t)]) AS hits
WHERE hits > 0
RETURN c.text AS text, toFloat(hits) / size($terms) AS score,
       pub.name AS title, pub.author_or_org AS author,
       pub.year AS year, pub.geography AS geography
ORDER BY hits DESC LIMIT $k
"""

class OfflineOrchestrator (QueryOrchestrator ):

    def __init__ (self ,driver ):
        super ().__init__ (driver ,client =None )

    def parse_intent (self ,question :str )->QueryIntent :
        return parse_intent_rules (question )

    def _text_search (self ,intent :QueryIntent ,k :int =5 )->list [SourceCard ]:
        terms =intent .search_terms ()
        if not terms :
            return []
        cards :list [SourceCard ]=[]
        with self .driver .session ()as s :
            res =s .run (_CYPHER_TEXT_SEARCH ,terms =terms ,geo =intent .geography ,k =k )
            for rec in res :
                cards .append (SourceCard (
                title =rec ["title"]or "?",author =rec ["author"],
                year =rec ["year"],geography =rec ["geography"],
                snippet =(rec ["text"]or "")[:300 ],score =float (rec ["score"]),
                ))
        return cards 

    def _synthesize_offline (self ,question :str ,cards :list [SourceCard ],
    intent :QueryIntent )->str :
        if not cards :
            return ("По запросу не нашлось релевантных фрагментов в загруженном "
            "корпусе. Попробуйте переформулировать или загрузить документы по теме.")
        lines =[f"Найдено по терминам: {', '.join (intent .search_terms ()[:6 ])}.",
        "Релевантные фрагменты из источников:\n"]
        for i ,c in enumerate (cards ,1 ):
            src =c .title +(f", {c .author }"if c .author else "")+(f", {c .year }"if c .year else "")+f" [{c .geography or '?'}]"
            lines .append (f"{i }. «…{c .snippet .strip ()}…»\n   — {src }")
        lines .append ("\n(демо-режим без LLM-синтеза: показаны дословные "
        "фрагменты источников с атрибуцией)")
        return "\n".join (lines )

    def answer (self ,question :str )->QueryResult :
        intent =self .parse_intent (question )
        nodes ,edges =self ._fetch_neighbourhood (intent .search_terms ())
        cards =self ._text_search (intent )
        answer =self ._synthesize_offline (question ,cards ,intent )
        return QueryResult (answer =answer ,intent =intent ,
        nodes =nodes ,edges =edges ,sources =cards )

    def duplicate_check (self ,description :str ,threshold :float =0.5 )->list [SourceCard ]:
        intent =parse_intent_rules (description )
        return [c for c in self ._text_search (intent ,k =5 )if c .score >=threshold ]
