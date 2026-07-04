from __future__ import annotations 

import logging 
import re 
from dataclasses import dataclass ,field 
from pathlib import Path 
from typing import Literal 

logging .getLogger ("pdfminer").setLevel (logging .ERROR )

import pdfplumber 
import docx as _docx 
from pptx import Presentation 

from graph_loader import DocMeta 

BlockKind =Literal ["paragraph","table"]

@dataclass 
class Block :
    kind :BlockKind 
    text :str 
    page :int |None =None 

@dataclass 
class LoadedDoc :
    meta :DocMeta 
    blocks :list [Block ]=field (default_factory =list )
    lang :str ="ru"

def _guess_lang (text :str )->str :
    cyr =len (re .findall (r"[а-яё]",text ,re .IGNORECASE ))
    lat =len (re .findall (r"[a-z]",text ,re .IGNORECASE ))
    return "ru"if cyr >=lat else "en"

def _guess_geography (text :str ,lang :str )->str :
    t =text .lower ()
    ru_markers =("гипроникель","норникель","россия","рф","цветмет")
    intl_markers =("barclays","outokumpu","johnson matthey","botswana","brook hunt")
    if any (m in t for m in ru_markers ):
        return "RU"
    if any (m in t for m in intl_markers ):
        return "INTL"
    return "RU"if lang =="ru"else "INTL"

def _guess_year (text :str )->int |None :
    yrs =[int (y )for y in re .findall (r"\b(19[89]\d|20[0-3]\d)\b",text )]
    return max (yrs )if yrs else None 

def _table_to_text (rows :list [list ])->str :
    clean =[[(c or "").strip ().replace ("\n"," ")for c in r ]for r in rows if r ]
    if not clean :
        return ""
    header =clean [0 ]
    lines =[" | ".join (header )]
    for r in clean [1 :]:

        pairs =[f"{h }: {v }"for h ,v in zip (header ,r )if v and v !=h ]
        lines .append ("; ".join (pairs )if pairs else " | ".join (r ))
    return "\n".join (lines )

def _load_pdf (path :Path )->LoadedDoc :
    blocks :list [Block ]=[]
    full_text_parts :list [str ]=[]
    with pdfplumber .open (path )as pdf :
        for i ,page in enumerate (pdf .pages ,start =1 ):

            for tbl in page .extract_tables ():
                txt =_table_to_text (tbl )
                if len (txt )>40 :
                    blocks .append (Block ("table",txt ,page =i ))
            txt =page .extract_text ()or ""
            full_text_parts .append (txt )
            for para in re .split (r"\n\s*\n",txt ):
                para =para .strip ()
                if len (para )>30 :
                    blocks .append (Block ("paragraph",para ,page =i ))
    full ="\n".join (full_text_parts )
    lang =_guess_lang (full )
    meta =DocMeta (
    doc_id =path .name ,title =path .stem ,
    year =_guess_year (full [:3000 ]),
    geography =_guess_geography (full [:3000 ],lang ),
    doc_type ="pdf",
    )
    return LoadedDoc (meta =meta ,blocks =blocks ,lang =lang )

def _load_docx (path :Path )->LoadedDoc :
    d =_docx .Document (str (path ))
    blocks :list [Block ]=[]
    all_text :list [str ]=[]
    for p in d .paragraphs :
        if p .text .strip ():
            all_text .append (p .text )
            if len (p .text .strip ())>30 :
                blocks .append (Block ("paragraph",p .text .strip ()))
    for tbl in d .tables :
        rows =[[c .text for c in row .cells ]for row in tbl .rows ]
        txt =_table_to_text (rows )
        if len (txt )>40 :
            blocks .append (Block ("table",txt ))
        all_text .append (txt )
    full ="\n".join (all_text )
    lang =_guess_lang (full )
    meta =DocMeta (
    doc_id =path .name ,title =path .stem ,
    year =_guess_year (full [:3000 ]),
    geography =_guess_geography (full [:3000 ],lang ),
    doc_type ="docx",
    )
    return LoadedDoc (meta =meta ,blocks =blocks ,lang =lang )

def _load_pptx (path :Path )->LoadedDoc :
    prs =Presentation (str (path ))
    blocks :list [Block ]=[]
    all_text :list [str ]=[]
    for slide in prs .slides :
        parts =[]
        for shape in slide .shapes :
            if shape .has_text_frame and shape .text_frame .text .strip ():
                parts .append (shape .text_frame .text .strip ())
        if parts :
            slide_text ="\n".join (parts )
            all_text .append (slide_text )
            blocks .append (Block ("paragraph",slide_text ))
    full ="\n".join (all_text )
    lang =_guess_lang (full )
    meta =DocMeta (
    doc_id =path .name ,title =path .stem ,
    year =_guess_year (full [:3000 ]),
    geography =_guess_geography (full [:3000 ],lang ),
    doc_type ="pptx",
    )
    return LoadedDoc (meta =meta ,blocks =blocks ,lang =lang )

_LOADERS ={".pdf":_load_pdf ,".docx":_load_docx ,".pptx":_load_pptx }

def load_document (path :str |Path )->LoadedDoc :
    path =Path (path )
    loader =_LOADERS .get (path .suffix .lower ())
    if loader is None :
        raise ValueError (f"Неподдерживаемый тип: {path .suffix }. Есть: {list (_LOADERS )}")
    return loader (path )

if __name__ =="__main__":
    import sys 
    for arg in sys .argv [1 :]:
        doc =load_document (arg )
        n_para =sum (b .kind =="paragraph"for b in doc .blocks )
        n_tbl =sum (b .kind =="table"for b in doc .blocks )
        print (f"{doc .meta .doc_id }: lang={doc .lang } geo={doc .meta .geography } "
        f"year={doc .meta .year } | {n_para } абз., {n_tbl } табл.")
