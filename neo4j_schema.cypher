CREATE CONSTRAINT material_key    IF NOT EXISTS FOR (n:Material)    REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT process_key     IF NOT EXISTS FOR (n:Process)     REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT equipment_key   IF NOT EXISTS FOR (n:Equipment)   REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT condition_key   IF NOT EXISTS FOR (n:Condition)   REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT experiment_key  IF NOT EXISTS FOR (n:Experiment)  REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT publication_key IF NOT EXISTS FOR (n:Publication) REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT expert_key      IF NOT EXISTS FOR (n:Expert)      REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT facility_key    IF NOT EXISTS FOR (n:Facility)    REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT finding_key     IF NOT EXISTS FOR (n:Finding)     REQUIRE n.norm_key IS UNIQUE;
CREATE CONSTRAINT chunk_id        IF NOT EXISTS FOR (n:Chunk)       REQUIRE n.chunk_id IS UNIQUE;
CREATE INDEX condition_parameter IF NOT EXISTS FOR (n:Condition)   ON (n.parameter);
CREATE INDEX publication_year    IF NOT EXISTS FOR (n:Publication) ON (n.year);
CREATE INDEX experiment_year     IF NOT EXISTS FOR (n:Experiment)  ON (n.year);
CREATE INDEX chunk_doc           IF NOT EXISTS FOR (n:Chunk)       ON (n.doc_id);
CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 256,
  `vector.similarity_function`: 'cosine'
}};
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Material|Process|Equipment|Experiment|Publication|Expert|Facility|Finding)
ON EACH [n.name, n.name_en, n.aliases_text];
