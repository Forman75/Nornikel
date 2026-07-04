from __future__ import annotations 

import argparse 
import shutil 
from pathlib import Path 

import pdfplumber 
import docx as _docx 
from pptx import Presentation 

import logging 
logging .getLogger ("pdfminer").setLevel (logging .ERROR )

TOPICS :dict [str ,list [str ]]={
"обессоливание воды":["обессолив","сульфат","хлорид","сухой остаток",
"обратн осмос","ионообмен","водоподготов","минерализ","десалин",
"reverse osmosis","нанофильтр","умягчен"],
"католит/электроэкстракция Ni":["католит","электроэкстракц","electrowinning",
"электролиз никел","циркуляц","катодн","танкхаус","намывн катод"],
"Au/Ag/МПГ штейн-шлак":["штейн","шлак","драгмет","платин","палладий",
"золот","серебр","мпг","распределени металл","matte","slag","pgm",
"файнштейн","конвертер"],
"закачка шахтных вод":["закачк","шахтн вод","глубок горизонт","подземн захорон",
"нагнетан","инжекц","поглощающ скважин","рудничн вод"],
}

GENERAL =["плавк","металлург","обогащени","концентрат","гидрометаллург",
"пирометаллург","выщелачиван","флотац","руд","никел","медн"]

SAMPLE_CHARS =8000 
PDF_SAMPLE_PAGES =5 

def _sample_text (path :Path )->str :
    ext =path .suffix .lower ()
    try :
        if ext ==".pdf":
            parts =[]
            with pdfplumber .open (path )as pdf :
                for page in pdf .pages [:PDF_SAMPLE_PAGES ]:
                    parts .append (page .extract_text ()or "")
                    if sum (len (p )for p in parts )>SAMPLE_CHARS :
                        break 
            return " ".join (parts )[:SAMPLE_CHARS ]
        if ext ==".docx":
            d =_docx .Document (str (path ))
            buf =[]
            for p in d .paragraphs :
                buf .append (p .text )
                if sum (len (x )for x in buf )>SAMPLE_CHARS :
                    break 
            return " ".join (buf )[:SAMPLE_CHARS ]
        if ext ==".pptx":
            prs =Presentation (str (path ))
            buf =[]
            for slide in prs .slides :
                for sh in slide .shapes :
                    if sh .has_text_frame :
                        buf .append (sh .text_frame .text )
                if sum (len (x )for x in buf )>SAMPLE_CHARS :
                    break 
            return " ".join (buf )[:SAMPLE_CHARS ]
    except Exception as e :
        return f"__ERROR__ {e }"
    return ""

def _score (text :str )->tuple [float ,str ,int ]:
    low =text .lower ()
    topic_scores ={}
    for topic ,kws in TOPICS .items ():
        topic_scores [topic ]=sum (low .count (k )for k in kws )
    general =sum (low .count (k )for k in GENERAL )
    best_topic =max (topic_scores ,key =topic_scores .get )
    best_val =topic_scores [best_topic ]
    total =best_val *3 +sum (topic_scores .values ())+general *0.3 
    return total ,(best_topic if best_val >0 else "—"),len (text )

def main ()->None :
    ap =argparse .ArgumentParser ()
    ap .add_argument ("root",help ="папка с исходными данными (сканируется рекурсивно)")
    ap .add_argument ("--copy",type =int ,default =0 ,help ="скопировать топ-N в corpus/")
    ap .add_argument ("--min-chars",type =int ,default =200 ,
    help ="порог текста: файлы ниже считаем сканами/пустыми")
    args =ap .parse_args ()

    root =Path (args .root )
    files =[p for p in root .rglob ("*")if p .suffix .lower ()in (".pdf",".docx",".pptx")]
    print (f"Найдено файлов: {len (files )}. Сканирую образцы…\n")

    rows =[]
    for p in files :
        text =_sample_text (p )
        if text .startswith ("__ERROR__"):
            rows .append ((-1 ,"ОШИБКА",0 ,p ))
            continue 
        score ,topic ,ln =_score (text )
        rows .append ((score ,topic ,ln ,p ))

    rows .sort (key =lambda r :r [0 ],reverse =True )

    print (f"{'БАЛЛ':>6}  {'ТЕМА':<28} {'ТЕКСТ':>6}  ФАЙЛ")
    print ("-"*90 )
    for score ,topic ,ln ,p in rows :
        flag =""
        if ln <args .min_chars and score >=0 :
            flag ="  ⚠скан/мало текста"
        size_mb =p .stat ().st_size /1e6 
        print (f"{score :>6.0f}  {topic :<28} {ln :>6}  {p .name [:50 ]} [{size_mb :.1f}MB]{flag }")

    if args .copy >0 :
        corpus =Path ("corpus");corpus .mkdir (exist_ok =True )
        picked =[r for r in rows if r [0 ]>0 and r [2 ]>=args .min_chars ][:args .copy ]
        print (f"\nКопирую топ-{len (picked )} в {corpus .resolve ()}:")
        for score ,topic ,ln ,p in picked :
            dst =corpus /p .name 
            shutil .copy2 (p ,dst )
            print (f"  + {p .name }  ({topic }, балл {score :.0f})")
        print ("\nГотово. Проверь корпус:  python run_ingest.py --dry-run corpus/*.pdf")

if __name__ =="__main__":
    main ()
