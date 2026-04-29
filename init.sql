CREATE EXTENSION IF NOT EXISTS rdkit;
CREATE EXTENSION IF NOT EXISTS pg_trgm;


CREATE TABLE IF NOT EXISTS production_molecules (
    id               SERIAL PRIMARY KEY,
    "structureMol"   mol,                        -- RDKit mol type
    "casNumber"      TEXT,
    "alternativeNames" TEXT[],
    cid              BIGINT,
    "iupacName"      TEXT,
    "molWeight"      NUMERIC(12, 4),
    "inchiKey"       TEXT,
    fp_0  BIGINT, fp_1  BIGINT, fp_2  BIGINT, fp_3  BIGINT,
    fp_4  BIGINT, fp_5  BIGINT, fp_6  BIGINT, fp_7  BIGINT,
    fp_8  BIGINT, fp_9  BIGINT, fp_10 BIGINT, fp_11 BIGINT,
    fp_12 BIGINT, fp_13 BIGINT, fp_14 BIGINT, fp_15 BIGINT,
    fp_16 BIGINT, fp_17 BIGINT, fp_18 BIGINT, fp_19 BIGINT,
    fp_20 BIGINT, fp_21 BIGINT, fp_22 BIGINT, fp_23 BIGINT,
    fp_24 BIGINT, fp_25 BIGINT, fp_26 BIGINT, fp_27 BIGINT,
    fp_28 BIGINT, fp_29 BIGINT, fp_30 BIGINT, fp_31 BIGINT,
    popcnt INTEGER
);


CREATE UNIQUE INDEX IF NOT EXISTS idx_molecules_inchikey
    ON production_molecules ("inchiKey");


CREATE INDEX IF NOT EXISTS idx_molecules_mol_gist
    ON production_molecules USING gist ("structureMol");


CREATE INDEX IF NOT EXISTS idx_molecules_iupacname_norm_btree
    ON production_molecules
    (lower(replace(replace("iupacName", '-', ' '), '_', ' ')));

CREATE INDEX IF NOT EXISTS idx_molecules_iupacname_norm_trgm
    ON production_molecules
    USING gin (lower(replace(replace("iupacName", '-', ' '), '_', ' ')) gin_trgm_ops);


CREATE INDEX IF NOT EXISTS idx_molecules_casnumber_btree
    ON production_molecules (lower("casNumber"));

CREATE INDEX IF NOT EXISTS idx_molecules_casnumber_trgm
    ON production_molecules
    USING gin (lower("casNumber") gin_trgm_ops);


CREATE INDEX IF NOT EXISTS idx_molecules_cid_btree
    ON production_molecules (cid);

CREATE INDEX IF NOT EXISTS idx_molecules_cid_text_trgm
    ON production_molecules
    USING gin (CAST(cid AS TEXT) gin_trgm_ops);


CREATE INDEX IF NOT EXISTS idx_molecules_molweight_btree
    ON production_molecules ("molWeight");


CREATE INDEX IF NOT EXISTS idx_molecules_altnames_gin
    ON production_molecules USING gin ("alternativeNames");


CREATE INDEX IF NOT EXISTS idx_molecules_covering
    ON production_molecules (id, "molWeight", "inchiKey")
    INCLUDE ("casNumber", cid, "iupacName");


ALTER TABLE production_molecules
    ALTER COLUMN "inchiKey"   SET STATISTICS 500,
    ALTER COLUMN "iupacName"  SET STATISTICS 500,
    ALTER COLUMN "casNumber"  SET STATISTICS 300,
    ALTER COLUMN "molWeight"  SET STATISTICS 300,
    ALTER COLUMN cid          SET STATISTICS 300;


ALTER TABLE production_molecules
    SET (
        autovacuum_vacuum_scale_factor  = 0.01,
        autovacuum_analyze_scale_factor = 0.005,
        autovacuum_vacuum_cost_delay    = 2
    );
