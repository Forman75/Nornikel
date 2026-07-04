from __future__ import annotations 

import os 
from contextlib import asynccontextmanager 
from dataclasses import asdict 
from pathlib import Path 

from fastapi import FastAPI 
from fastapi .responses import FileResponse ,JSONResponse 
from fastapi .staticfiles import StaticFiles 
from pydantic import BaseModel 

from graph_loader import GraphLoader 
from yandex_client import YandexClient 
from query_orchestrator import QueryOrchestrator ,sample_subgraph 

STATIC_DIR =Path (__file__ ).parent /"static"

state :dict ={}

@asynccontextmanager 
async def lifespan (app :FastAPI ):
    loader =GraphLoader .from_env ()
    state ["driver"]=loader .driver 
    state ["loader"]=loader 
    if os .getenv ("OFFLINE_MODE")=="1":

        from offline_orchestrator import OfflineOrchestrator 
        state ["orch"]=OfflineOrchestrator (loader .driver )
        print (">> OFFLINE_MODE: работаем без Yandex API")
    else :
        client =YandexClient ()
        state ["orch"]=QueryOrchestrator (loader .driver ,client )
    yield 
    loader .close ()

app =FastAPI (title ="R&D Knowledge Graph",lifespan =lifespan )

class QueryBody (BaseModel ):
    question :str 

class DupBody (BaseModel ):
    description :str 

@app .get ("/api/stats")
def stats ():
    with state ["driver"].session ()as s :
        rows =s .run (
        "MATCH (n) WHERE NOT n:Chunk "
        "RETURN labels(n)[0] AS type, count(*) AS cnt ORDER BY cnt DESC"
        )
        by_type ={r ["type"]:r ["cnt"]for r in rows }
        rels =s .run ("MATCH ()-[r]->() RETURN count(r) AS c").single ()["c"]
        chunks =s .run ("MATCH (c:Chunk) RETURN count(c) AS c").single ()["c"]
    return {"nodes_by_type":by_type ,"relations":rels ,"chunks":chunks }

@app .get ("/api/subgraph")
def subgraph (limit :int =150 ):
    nodes ,edges =sample_subgraph (state ["driver"],limit =limit )
    return {"nodes":[asdict (n )for n in nodes ],"edges":[asdict (e )for e in edges ]}

@app .post ("/api/query")
def query (body :QueryBody ):
    r =state ["orch"].answer (body .question )
    return {
    "answer":r .answer ,
    "intent":r .intent .model_dump (),
    "nodes":[asdict (n )for n in r .nodes ],
    "edges":[asdict (e )for e in r .edges ],
    "sources":[asdict (c )for c in r .sources ],
    }

@app .post ("/api/duplicate-check")
def duplicate_check (body :DupBody ):
    cards =state ["orch"].duplicate_check (body .description )
    return {"found":len (cards )>0 ,"matches":[asdict (c )for c in cards ]}

@app .get ("/api/gap")
def gap ():
    return {"gaps":state ["orch"].gap_analysis ()}

@app .get ("/")
def index ():
    idx =STATIC_DIR /"index.html"
    if not idx .exists ():
        return JSONResponse ({"error":"static/index.html не найден"},status_code =500 )
    return FileResponse (idx )

if STATIC_DIR .exists ():
    app .mount ("/static",StaticFiles (directory =STATIC_DIR ),name ="static")
