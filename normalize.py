from __future__ import annotations 

import re 
from dataclasses import dataclass ,field 

@dataclass 
class NormReport :
    temp_fixes :list [tuple [str ,str ]]=field (default_factory =list )
    decimal_fixes :int =0 
    dehyphenated :int =0 

    def summary (self )->str :
        parts =[]
        if self .temp_fixes :
            ex =", ".join (f"{a }->{b }"for a ,b in self .temp_fixes [:5 ])
            parts .append (f"температур: {len (self .temp_fixes )} ({ex })")
        if self .decimal_fixes :
            parts .append (f"десятичных запятых: {self .decimal_fixes }")
        if self .dehyphenated :
            parts .append (f"переносов склеено: {self .dehyphenated }")
        return "; ".join (parts )if parts else "без замен"

_RE_TEMP_OCR =re .compile (r"(?<![\d.,])(\d{2,5})0\s*([СC])(?![а-яa-z])")

_RE_HYPHEN_BREAK =re .compile (r"([а-яёa-z])-\s*\n\s*([а-яёa-z])",re .IGNORECASE )

_RE_DECIMAL_COMMA =re .compile (r"(\d),(\d)")

_RE_WS =re .compile (r"[ \t]+")
_RE_MULTINL =re .compile (r"\n{3,}")

def _fix_temperatures (text :str ,report :NormReport )->str :
    def repl (m :re .Match )->str :
        num =m .group (1 )
        fixed =f"{num } °C"
        report .temp_fixes .append ((m .group (0 ).strip (),fixed ))
        return fixed 
    return _RE_TEMP_OCR .sub (repl ,text )

def _dehyphenate (text :str ,report :NormReport )->str :
    def repl (m :re .Match )->str :
        report .dehyphenated +=1 
        return m .group (1 )+m .group (2 )
    return _RE_HYPHEN_BREAK .sub (repl ,text )

def _fix_decimal_comma (text :str ,report :NormReport )->str :
    count =len (_RE_DECIMAL_COMMA .findall (text ))
    report .decimal_fixes +=count 
    return _RE_DECIMAL_COMMA .sub (r"\1.\2",text )

def normalize (text :str ,lang :str ="ru")->tuple [str ,NormReport ]:
    report =NormReport ()
    text =_dehyphenate (text ,report )
    if lang =="ru":
        text =_fix_temperatures (text ,report )
        text =_fix_decimal_comma (text ,report )

    else :
        text =_fix_temperatures (text ,report )
    text =_RE_WS .sub (" ",text )
    text =_RE_MULTINL .sub ("\n\n",text )
    return text .strip (),report 

if __name__ =="__main__":
    sample =("Технологический воздух обогащен кислородом до 30-35% и подог-\n"
    "рет паром до 2600С. Температура газа на входе в котел составляет 14000С, "
    "температуры входа и выхода 11500С и 6000С. Содержание никеля 0,201%, "
    "никель+медь 8,85%. Проплавлено 860 тыс. т концен-\nтрата.")
    out ,rep =normalize (sample ,lang ="ru")
    print (out )
    print ("\nОтчёт:",rep .summary ())
