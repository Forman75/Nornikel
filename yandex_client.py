from __future__ import annotations 

import json 
import os 
import re 
import time 
from dataclasses import dataclass 

from openai import OpenAI 
from pydantic import ValidationError 

from extraction_schema import ChunkExtractionResult ,build_extraction_system_prompt 

BASE_URL ="https://llm.api.cloud.yandex.net/v1"
_FENCE =re .compile (r"^\s*```(?:json)?\s*|\s*```\s*$",re .MULTILINE )

@dataclass 
class ExtractStats :
    attempts :int =0 
    ok :bool =False 
    last_error :str |None =None 

class YandexClient :
    def __init__ (self ,api_key :str |None =None ,folder_id :str |None =None ,
    gpt_model :str ="yandexgpt/latest",
    doc_emb :str ="text-search-doc/latest",
    query_emb :str ="text-search-query/latest"):
        self .api_key =api_key or os .environ ["YANDEX_API_KEY"]
        self .folder =folder_id or os .environ ["YANDEX_FOLDER_ID"]
        self .gpt_uri =f"gpt://{self .folder }/{gpt_model }"
        self .doc_emb_uri =f"emb://{self .folder }/{doc_emb }"
        self .query_emb_uri =f"emb://{self .folder }/{query_emb }"
        self .client =OpenAI (api_key =self .api_key ,base_url =BASE_URL )
        self ._sys_prompt =build_extraction_system_prompt ()

    def complete (self ,system :str ,user :str ,temperature :float =0.2 )->str :
        resp =self .client .chat .completions .create (
        model =self .gpt_uri ,
        messages =[{"role":"system","content":system },
        {"role":"user","content":user }],
        temperature =temperature ,
        )
        return resp .choices [0 ].message .content or ""

    def embed (self ,text :str ,is_query :bool =False )->list [float ]:
        uri =self .query_emb_uri if is_query else self .doc_emb_uri 

        resp =self .client .embeddings .create (
        model =uri ,input =text ,encoding_format ="float",
        )
        return resp .data [0 ].embedding 

    def extract_chunk (self ,chunk_id :str ,chunk_text :str ,
    max_retries :int =2 )->tuple [ChunkExtractionResult |None ,ExtractStats ]:
        stats =ExtractStats ()
        messages =[
        {"role":"system","content":self ._sys_prompt },
        {"role":"user","content":f"chunk_id для ответа: {chunk_id }\n\nТЕКСТ:\n{chunk_text }"},
        ]
        for attempt in range (max_retries +1 ):
            stats .attempts =attempt +1 
            try :
                resp =self .client .chat .completions .create (
                model =self .gpt_uri ,messages =messages ,temperature =0.1 ,
                )
                raw =resp .choices [0 ].message .content or ""
                cleaned =_FENCE .sub ("",raw ).strip ()
                data =json .loads (cleaned )
                data .setdefault ("chunk_id",chunk_id )
                data ["chunk_id"]=chunk_id 
                result =ChunkExtractionResult .model_validate (data )
                stats .ok =True 
                return result ,stats 
            except (json .JSONDecodeError ,ValidationError )as e :
                stats .last_error =str (e )[:500 ]
                if attempt <max_retries :
                    messages .append ({"role":"assistant","content":raw if 'raw'in dir ()else ""})
                    messages .append ({
                    "role":"user",
                    "content":(
                    "Твой предыдущий ответ не прошёл валидацию со следующей ошибкой:\n"
                    f"{stats .last_error }\n\n"
                    "Верни ИСПРАВЛЕННЫЙ строго валидный JSON по той же схеме, "
                    "без markdown и без текста вокруг."
                    ),
                    })
                    time .sleep (0.5 )
            except Exception as e :

                stats .last_error =f"{type (e ).__name__ }: {e }"
                raise 
        return None ,stats 

class MockYandexClient :
    def __init__ (self ,dim :int =256 ):
        self .dim =dim 

    def embed (self ,text :str ,is_query :bool =False )->list [float ]:
        return [0.0 ]*self .dim 

    def complete (self ,system :str ,user :str ,temperature :float =0.2 )->str :
        return "{}"

    def extract_chunk (self ,chunk_id :str ,chunk_text :str ,max_retries :int =2 ):
        stats =ExtractStats (attempts =1 ,ok =True )
        return ChunkExtractionResult (chunk_id =chunk_id ,entities =[],relations =[]),stats
