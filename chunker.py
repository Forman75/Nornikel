from __future__ import annotations 

import re 
from dataclasses import dataclass 

from ingest import LoadedDoc ,Block 
from normalize import normalize 

CHUNK_TOKENS =600 
OVERLAP_TOKENS =80 
MAX_TABLE_TOKENS =700 

def est_tokens (text :str )->int :
    return max (1 ,round (len (text )/3.5 ))

@dataclass 
class Chunk :
    chunk_id :str 
    text :str 
    kind :str 
    page :int |None =None 

def _split_sentences (text :str )->list [str ]:

    parts =re .split (r"(?<=[.!?;])\s+",text )
    return [p for p in parts if p .strip ()]

def _pack_prose (paragraphs :list [tuple [str ,int |None ]])->list [tuple [str ,int |None ]]:
    out :list [tuple [str ,int |None ]]=[]
    buf :list [str ]=[]
    buf_tokens =0 
    buf_page :int |None =None 

    def flush ():
        nonlocal buf ,buf_tokens 
        if buf :
            out .append ((" ".join (buf ).strip (),buf_page ))
        buf ,buf_tokens =[],0 

    for text ,page in paragraphs :
        if buf_page is None :
            buf_page =page 
        sents =_split_sentences (text )
        for s in sents :
            st =est_tokens (s )
            if buf_tokens +st >CHUNK_TOKENS and buf :
                flush ()

                tail ,tail_tok =[],0 
                for prev in reversed (out [-1 ][0 ].split (". ")):
                    tail_tok +=est_tokens (prev )
                    tail .insert (0 ,prev )
                    if tail_tok >=OVERLAP_TOKENS :
                        break 
                buf =tail [:]
                buf_tokens =tail_tok 
                buf_page =page 
            buf .append (s )
            buf_tokens +=st 
    flush ()
    return out 

def _split_table (text :str )->list [str ]:
    lines =text .split ("\n")
    if not lines :
        return []
    header =lines [0 ]
    if est_tokens (text )<=MAX_TABLE_TOKENS :
        return [text ]
    chunks ,cur ,cur_tok =[],[header ],est_tokens (header )
    for line in lines [1 :]:
        lt =est_tokens (line )
        if cur_tok +lt >MAX_TABLE_TOKENS and len (cur )>1 :
            chunks .append ("\n".join (cur ))
            cur ,cur_tok =[header ],est_tokens (header )
        cur .append (line )
        cur_tok +=lt 
    if len (cur )>1 :
        chunks .append ("\n".join (cur ))
    return chunks 

def chunk_document (doc :LoadedDoc )->list [Chunk ]:
    prose :list [tuple [str ,int |None ]]=[]
    tables :list [tuple [str ,int |None ]]=[]

    for b in doc .blocks :
        norm ,_ =normalize (b .text ,lang =doc .lang )
        if not norm :
            continue 
        if b .kind =="table":
            tables .append ((norm ,b .page ))
        else :
            prose .append ((norm ,b .page ))

    chunks :list [Chunk ]=[]
    idx =0 
    for text ,page in _pack_prose (prose ):
        chunks .append (Chunk (f"{doc .meta .doc_id }#{idx :04d}",text ,"paragraph",page ))
        idx +=1 
    for text ,page in tables :
        for piece in _split_table (text ):
            chunks .append (Chunk (f"{doc .meta .doc_id }#{idx :04d}",piece ,"table",page ))
            idx +=1 
    return chunks 

if __name__ =="__main__":
    import sys 
    from ingest import load_document 
    doc =load_document (sys .argv [1 ])
    chunks =chunk_document (doc )
    print (f"{doc .meta .doc_id }: {len (chunks )} чанков "
    f"({sum (c .kind =='paragraph'for c in chunks )} проза, "
    f"{sum (c .kind =='table'for c in chunks )} таблицы)")
    for c in chunks [:2 ]:
        print (f"\n--- {c .chunk_id } [{c .kind }, ~{est_tokens (c .text )} tok] ---")
        print (c .text [:280 ])
