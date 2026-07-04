from __future__ import annotations 

import argparse 
import sys 
from pathlib import Path 
from glob import glob 

from ingest import load_document 
from chunker import chunk_document ,est_tokens 
from extraction_schema import sanitize_relations 

def _expand (paths :list [str ])->list [str ]:
    out :list [str ]=[]
    for p in paths :
        if any (ch in p for ch in "*?[]"):
            matched =sorted (glob (p ))
            if not matched :
                print (f"  ⚠ маска ничего не нашла: {p }")
            out .extend (matched )
        else :
            out .append (p )
    return out 

def run (paths :list [str ],dry_run :bool ,no_graph :bool )->None :
    paths =_expand (paths )
    if not paths :
        print ("Нет файлов для загрузки. Проверь путь/маску.")
        return 

    client =None 
    loader =None 
    if not dry_run :
        from yandex_client import YandexClient 
        client =YandexClient ()
        if not no_graph :
            from graph_loader import GraphLoader 
            loader =GraphLoader .from_env ()
            loader .ensure_schema ()

    total_chunks =total_entities =total_relations =skipped =0 

    for path in paths :
        doc =load_document (path )
        chunks =chunk_document (doc )
        print (f"\n=== {doc .meta .doc_id } === lang={doc .lang } geo={doc .meta .geography } "
        f"year={doc .meta .year } | {len (chunks )} чанков")

        for c in chunks :
            total_chunks +=1 
            if dry_run :
                print (f"  [{c .chunk_id }] {c .kind } ~{est_tokens (c .text )}tok :: "
                f"{c .text [:90 ].replace (chr (10 ),' ')}...")
                continue 

            result ,stats =client .extract_chunk (c .chunk_id ,c .text )
            if result is None :
                skipped +=1 
                print (f"  [{c .chunk_id }] ПРОПУЩЕН после {stats .attempts } попыток: "
                f"{stats .last_error }")
                continue 

            result ,dropped =sanitize_relations (result )
            if dropped :
                print (f"  [{c .chunk_id }] отброшено связей: {len (dropped )} "
                f"(напр. {dropped [0 ]})")

            total_entities +=len (result .entities )
            total_relations +=len (result .relations )

            if no_graph :
                ents =", ".join (f"{e .type .value }:{e .name }"for e in result .entities [:6 ])
                print (f"  [{c .chunk_id }] {len (result .entities )}E/{len (result .relations )}R "
                f":: {ents }")
                continue 

            embedding =client .embed (c .text ,is_query =False )
            loader .load_chunk (
            result ,doc .meta ,chunk_text =c .text ,
            embedding =embedding ,position =int (c .chunk_id .split ('#')[-1 ]),
            )
            print (f"  [{c .chunk_id }] загружен: {len (result .entities )}E/{len (result .relations )}R")

    if loader :
        loader .close ()

    print (f"\nИТОГО: чанков {total_chunks }, сущностей {total_entities }, "
    f"связей {total_relations }, пропущено {skipped }")

def main ()->None :
    ap =argparse .ArgumentParser (description ="Ingestion R&D-графа")
    ap .add_argument ("paths",nargs ="+",help ="файлы корпуса (.pdf/.docx/.pptx)")
    ap .add_argument ("--dry-run",action ="store_true",
    help ="только парсинг/чанкинг, без API и Neo4j")
    ap .add_argument ("--no-graph",action ="store_true",
    help ="экстракция через API, но без записи в граф")
    args =ap .parse_args ()
    if not args .dry_run :
        missing =[v for v in ("YANDEX_API_KEY","YANDEX_FOLDER_ID")
        if v not in __import__ ("os").environ ]
        if missing :
            sys .exit (f"Нет переменных окружения: {missing }. "
            f"Либо задай их, либо запусти с --dry-run.")
    run (args .paths ,args .dry_run ,args .no_graph )

if __name__ =="__main__":
    main ()
