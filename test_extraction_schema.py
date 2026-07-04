import pytest 
from pydantic import ValidationError 

from extraction_schema import ChunkExtractionResult ,Condition ,sanitize_relations 
from graph_loader import entity_norm_key ,norm_unit 

def _entity (local_id ,etype ,name ,**kw ):
    return {
    "local_id":local_id ,"type":etype ,"name":name ,
    "source_span":"цитата из текста","confidence":"high",**kw ,
    }

def _cond_entity (local_id ,parameter ="сульфаты",operator ="<=",value =300.0 ,
unit ="мг/л",**cond_kw ):
    return _entity (
    local_id ,"Condition",parameter ,
    condition ={"parameter":parameter ,"operator":operator ,
    "value":value ,"unit":unit ,**cond_kw },
    )

def _result (entities ,relations =()):
    return {"chunk_id":"c1","entities":entities ,"relations":list (relations )}

def test_numeric_condition_without_unit_fails ():
    with pytest .raises (ValidationError ,match ="unit"):
        Condition (parameter ="температура",operator ="<=",value =80 )

def test_categorical_condition_without_value_text_fails ():
    with pytest .raises (ValidationError ,match ="value_text"):
        Condition (parameter ="климат",operator ="is")

def test_categorical_condition_ok_without_unit ():
    c =Condition (parameter ="климат",operator ="is",value_text ="холодный")
    assert c .unit is None 

def test_range_without_value_max_fails ():
    with pytest .raises (ValidationError ,match ="value_max"):
        Condition (parameter ="сульфаты",operator ="range",value =200 ,unit ="мг/л")

def test_range_swapped_bounds_are_fixed_deterministically ():
    c =Condition (parameter ="сульфаты",operator ="range",
    value =300 ,value_max =200 ,unit ="мг/л")
    assert (c .value ,c .value_max )==(200 ,300 )

def test_condition_entity_requires_condition_block ():
    with pytest .raises (ValidationError ,match ="condition"):
        ChunkExtractionResult .model_validate (
        _result ([_entity ("e1","Condition","сульфаты")])
        )

def test_non_condition_entity_must_not_carry_condition ():
    bad =_entity ("e1","Material","сульфаты",
    condition ={"parameter":"x","operator":"is","value_text":"y"})
    with pytest .raises (ValidationError ):
        ChunkExtractionResult .model_validate (_result ([bad ]))

def test_duplicate_local_id_fails ():
    with pytest .raises (ValidationError ,match ="Дубликат"):
        ChunkExtractionResult .model_validate (_result ([
        _entity ("e1","Material","никель"),
        _entity ("e1","Process","электроэкстракция"),
        ]))

def test_relation_to_unknown_local_id_fails ():
    rel ={"source_local_id":"e1","target_local_id":"e99",
    "type":"REQUIRES_CONDITION","source_span":"...","confidence":"high"}
    with pytest .raises (ValidationError ,match ="вне списка"):
        ChunkExtractionResult .model_validate (
        _result ([_entity ("e1","Process","электроэкстракция")],[rel ])
        )

def test_bad_endpoint_relation_is_dropped_not_fatal ():

    rel ={"source_local_id":"e1","target_local_id":"e2",
    "type":"VALIDATED_BY","source_span":"...","confidence":"high"}
    result =ChunkExtractionResult .model_validate (_result (
    [_entity ("e1","Material","никель"),
    _entity ("e2","Expert","Иванов И.И.")],
    [rel ],
    ))
    cleaned ,dropped =sanitize_relations (result )
    assert len (dropped )==1 
    assert len (cleaned .relations )==0 
    assert len (cleaned .entities )==2 

def test_valid_endpoint_relation_survives_sanitize ():
    rel ={"source_local_id":"e1","target_local_id":"e2",
    "type":"VALIDATED_BY","source_span":"...","confidence":"high"}
    result =ChunkExtractionResult .model_validate (_result (
    [_entity ("e1","Finding","оптимальная скорость потока 0.5 м/с"),
    _entity ("e2","Expert","Иванов И.И.")],
    [rel ],
    ))
    cleaned ,dropped =sanitize_relations (result )
    assert dropped ==[]
    assert len (cleaned .relations )==1 

def test_furnace_produces_output_material_is_valid ():

    rel ={"source_local_id":"e1","target_local_id":"e2",
    "type":"PRODUCES_OUTPUT","source_span":"ПВП производит штейн",
    "confidence":"high"}
    result =ChunkExtractionResult .model_validate (_result (
    [_entity ("e1","Equipment","печь взвешенной плавки"),
    _entity ("e2","Material","штейн")],
    [rel ],
    ))
    cleaned ,dropped =sanitize_relations (result )
    assert dropped ==[]
    assert len (cleaned .relations )==1 

def test_unit_normalization_merges_equivalent_units ():
    assert norm_unit ("мг/дм³")==norm_unit ("мг/л")=="мг/л"
    assert norm_unit ("mg/l")=="мг/л"

def test_equivalent_conditions_get_same_norm_key ():
    r1 =ChunkExtractionResult .model_validate (
    _result ([_cond_entity ("e1",unit ="мг/дм³")]))
    r2 =ChunkExtractionResult .model_validate (
    _result ([_cond_entity ("e1",unit ="мг/л")]))
    assert entity_norm_key (r1 .entities [0 ])==entity_norm_key (r2 .entities [0 ])

def test_name_normalization_key ():
    r1 =ChunkExtractionResult .model_validate (
    _result ([_entity ("e1","Process","Электроэкстракция  никеля")]))
    r2 =ChunkExtractionResult .model_validate (
    _result ([_entity ("e1","Process","электроэкстракция никеля")]))
    assert entity_norm_key (r1 .entities [0 ])==entity_norm_key (r2 .entities [0 ])
